# 02 — Architecture technique

## 1. Vue d'ensemble

```
             Enable Banking (AIS)        Demo / CSV / Plaid… (futurs)
                     │                              │
                     ▼                              ▼
          ┌──────────────────── providers/ ────────────────────┐
          │ BankingProvider (Protocol) → DTO canoniques         │
          └─────────────────────────┬───────────────────────────┘
                                    ▼
                         services/sync.py  (idempotent)
                     transaction_raw (append-only, jsonb)
                                    │ upsert par dedup_key
                                    ▼
                    pipeline/  (rejouable, étapes pures)
       merchant resolution → transfers → classification → recurring
                                    │
                    PostgreSQL ─────┼───── domain_events (outbox)
                                    │              │
                                    ▼              ▼
                     engines/ (fonctions pures)   events/ dispatcher
     cashflow · safe_to_spend · timeline · what_changed · state_score
                     snapshots · detectors → insights (fingerprint)
                                    │
               ┌────────────────────┼──────────────────────┐
               ▼                    ▼                      ▼
        api/ (FastAPI)        ai/ (LLMProvider +       jobs/ (scheduler:
     Command Center, widgets   tools typés)             sync, snapshot)
               │
               ▼
        apps/web (Next.js) — affichage uniquement
```

## 2. Monorepo

```
bankboard/
├── docs/                      # PRD analysis, architecture, schéma, roadmap
├── apps/
│   ├── api/                   # Backend Python (FastAPI)
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── migrations/        # Alembic ; 0001 = schéma initial (SQL explicite)
│   │   ├── src/bankboard/
│   │   │   ├── core/          # config, db, crypto, security, clock, logging
│   │   │   ├── models/        # SQLAlchemy 2 (typed, Mapped[])
│   │   │   ├── providers/     # BankingProvider + enable_banking/ + demo/
│   │   │   ├── services/      # sync, auth, bank connections, snapshots
│   │   │   ├── pipeline/      # étapes de normalisation (rejouables)
│   │   │   ├── analytics/     # chargement Polars (centimes), helpers stats
│   │   │   ├── engines/       # moteurs déterministes (purs, testés)
│   │   │   ├── detectors/     # producteurs d'insights structurés
│   │   │   ├── events/        # bus + outbox + types d'événements
│   │   │   ├── modules/       # registry : widgets, métriques, détecteurs, routes
│   │   │   ├── ai/            # LLMProvider, tools, Ask Your Money
│   │   │   ├── api/           # routers FastAPI, schémas Pydantic
│   │   │   ├── jobs/          # CLI + scheduler
│   │   │   └── demo/          # générateur 12 mois
│   │   └── tests/
│   └── web/                   # Next.js 15 + TS strict + Tailwind + ECharts
└── docker-compose.yml         # postgres (dev)
```

Pas de package partagé TS↔Python en P0 : le contrat est l'OpenAPI de FastAPI (`/openapi.json`) ; génération de types TS possible plus tard (`openapi-typescript`).

## 3. Backend

- **FastAPI + Pydantic v2 + SQLAlchemy 2 (sync) + psycopg 3.** Le sync suffit pour un produit personnel ; les endpoints tournent dans le threadpool. Les moteurs sont CPU-bound (Polars/NumPy) : l'async n'apporterait rien.
- **Couches** : `api` → `services` → (`pipeline` | `engines`) → `models`. Les moteurs **ne touchent pas la base** : ils reçoivent des DataFrames/DTO et retournent des DTO Pydantic avec `explanation`. Cela les rend testables sans DB et réutilisables par le simulateur (P2).
- **Typage strict** : `mypy --strict`, `ruff`.

### 3.1 Montants
`NUMERIC(19,4)` ↔ `Decimal`. Dans `analytics/frames.py`, conversion en **centimes `Int64`** (Polars) : sommes et moyennes exactes ; reconversion `Decimal` en sortie.

### 3.2 Résultats explicables
Tout moteur retourne un objet incluant :
```python
class ExplainLine(BaseModel):
    label: str; amount: Decimal | None; detail: str | None; ref: str | None
class Explained(BaseModel):
    value: Decimal | float; lines: list[ExplainLine]; method: str; confidence: float
```
Le bouton **Why?** du frontend affiche simplement `lines` + `method`.

## 4. Intégration bancaire

### 4.1 Abstraction
```python
class BankingProvider(Protocol):
    key: ClassVar[str]
    def list_institutions(self, country: str) -> list[Institution]: ...
    def start_authorization(self, institution: InstitutionRef, *, state: str,
                            redirect_url: str, valid_until: datetime) -> AuthorizationStart: ...
    def complete_authorization(self, code: str) -> ProviderSession: ...
    def get_accounts(self, session: SessionRef) -> list[ProviderAccount]: ...
    def get_balances(self, session: SessionRef, account_ref: str) -> list[ProviderBalance]: ...
    def get_transactions(self, session: SessionRef, account_ref: str,
                         date_range: DateRange) -> list[ProviderTransaction]: ...
    def revoke(self, session: SessionRef) -> None: ...
```
Contrairement à l'interface indicative du PRD, l'état (session) est **passé explicitement** : un provider est sans état et peut servir plusieurs connexions.

Chaque `ProviderTransaction` porte `provider_transaction_id | None`, montant signé, dates, contrepartie, libellés, MCC, statut, et **le payload brut**.

### 4.2 Enable Banking (AIS)
```
GET /aspsps?country=FR         → choix Revolut
POST /auth                     → {url, authorization_id}  (state = jeton aléatoire stocké en base, TTL 15 min, usage unique)
   redirect navigateur → banque → callback ?code&state
GET /api/bank/callback         → vérifie state (existence, user, expiration, non consommé) puis
POST /sessions {code}          → session_id (chiffré Fernet en base), comptes, valid_until
GET /accounts/{uid}/balances
GET /accounts/{uid}/transactions?date_from&date_to (pagination continuation_key)
```
- JWT RS256 signé **côté backend uniquement** : header `{typ, alg: RS256, kid: APP_ID}`, claims `{iss: enablebanking.com, aud: api.enablebanking.com, iat, exp ≤ 1h}` ; cache en mémoire jusqu'à expiration − 60 s.
- Clé privée : `ENABLE_BANKING_PRIVATE_KEY` (PEM ou chemin `ENABLE_BANKING_PRIVATE_KEY_PATH`), type `SecretStr`, jamais loggée, jamais sérialisée.
- Erreurs HTTP mappées vers `ProviderError(kind=auth|consent_expired|rate_limited|unavailable|invalid)` ; `consent_expired` passe la connexion en `reauth_required`.

### 4.3 Sync idempotente
Pour chaque compte : fenêtre `[last_synced_booking_date − 10 jours, today]` (chevauchement volontaire pour capter les écritures tardives), bornée à minuit. Première sync : 730 jours (limite ASPSP).
1. Insertion `transaction_raw` `ON CONFLICT (account_id, dedup_key) DO UPDATE SET last_seen_at` (le payload initial est conservé, une révision différente est stockée dans `payload_history`).
2. Upsert `transactions` par `raw_id`.
3. Suppression des *pending* de la fenêtre non ré-observées.
4. Balances : upsert par `(account_id, balance_type, reference_date)`.
5. `sync_jobs` trace début/fin/compteurs/erreur ; `bank_connections.last_synced_at`, `accounts.last_synced_booking_date`.
6. Émission `bank.sync.completed` → pipeline + recurring + snapshot + détecteurs.

Un verrou consultatif PostgreSQL (`pg_advisory_xact_lock(hash(connection_id))`) empêche deux syncs concurrentes de la même connexion.

## 5. Pipeline de normalisation (rejouable)

| Étape | Entrée → sortie | Rejouable car… |
|---|---|---|
| `normalize` | raw → champs canoniques | fonction pure du payload |
| `merchants` | libellé/contrepartie → `merchant_id` via `merchant_aliases` (exact, préfixe, regex), sinon marchand auto | règles en base, ordre déterministe |
| `transfers` | paires `(-x, +x)` entre comptes de l'utilisateur à ±3 j, ou libellés de virement interne | annule puis recalcule les groupes non manuels |
| `classify` | `kind` + `category` avec `confidence` et `source ∈ {bank, rule, historical, model, manual}` | ne modifie jamais `source = manual` |
| `recurring` | séries par (marchand, sens) → `recurring_patterns` + `expected_transactions` | recalcul complet par utilisateur |

`pipeline.run(user_id, scope)` rejoue tout ou une fenêtre. Version de pipeline stockée (`transactions.pipeline_version`) pour savoir quoi rejouer.

## 6. Moteurs analytiques (P0)

| Moteur | Sortie |
|---|---|
| `cashflow` | revenus, dépenses, épargne, taux d'épargne, ventilation catégories, par période |
| `safe_to_spend` | 4 horizons, décomposition complète |
| `timeline` | événements attendus (date, montant, intervalle, confiance, source) + solde projeté jour par jour + point bas |
| `what_changed` | comparaison de deux périodes : delta total, contributions par catégorie / kind, part de la hausse expliquée ; variation de patrimoine décomposée en flux + résidu non expliqué |
| `state_score` | score 0-100, sous-scores pondérés, contributions, diff vs snapshot précédent |
| `snapshots` | état quotidien persistant (`financial_snapshots`) avec backfill historique reconstruit à partir des soldes |

Détecteurs P0 (→ `insights`) : hausse de catégorie, grosse sortie attendue sous 7 j, cash dormant, double débit potentiel, nouvelle récurrence, connexion à renouveler.

## 7. Système de modules

```python
@dataclass(frozen=True)
class Module:
    key: str; title: str; tier: Literal["P0","P1","P2","P3"]
    router: APIRouter | None
    widgets: Sequence[WidgetSpec]          # id, titre, taille par défaut, endpoint de données
    detectors: Sequence[Detector]          # (ctx) -> list[InsightDraft]
    event_handlers: Mapping[str, Sequence[Handler]]
    enabled_by_default: bool = True
```
`modules/registry.py` collecte les modules ; l'API monte leurs routers, expose `GET /api/widgets` (catalogue), et le bus abonne leurs handlers. Activation par utilisateur : `user_preferences.modules`. Ajouter un module = un dossier + une ligne dans le registry ; le dashboard l'affiche sans modification (le frontend rend les widgets par `kind` générique : `metric`, `breakdown`, `timeline`, `series`, `list`, `insights`).

## 8. Event system

- Table `domain_events(id, user_id, type, payload jsonb, occurred_at, processed_at, attempts, last_error)`.
- `events.publish(session, type, payload)` écrit dans la même transaction que le changement (outbox).
- `events.dispatch_pending()` traite les événements (in-process après commit en P0 ; worker en P1). Handlers idempotents.
- Types : `transaction.created`, `transaction.updated`, `bank.sync.completed`, `income.detected`, `salary.received`, `goal.updated`, `month.closed`, `financial_state.changed`, `anomaly.detected`.

## 9. Jobs

`python -m bankboard.jobs <cmd>` : `sync-all`, `snapshot`, `replay-pipeline --user`, `seed-demo`, `scheduler` (boucle : sync toutes les 6 h, snapshot quotidien à 03:00, dispatch des événements). Remplaçable par cron/systemd ou un worker sans modifier le code métier.

## 10. Couche IA

```python
class LLMProvider(Protocol):
    def complete(self, *, system: str, messages: list[ChatMessage],
                 tools: list[ToolSpec]) -> LLMResponse: ...
```
- Implémentations : `AnthropicProvider` (HTTP, sans SDK imposé), `OfflineProvider` (routage par intention vers les tools, réponse templatée — sert aux tests et en l'absence de clé).
- **Tools typés** (`ai/tools.py`) : `get_financial_state`, `query_transactions` (filtres, limite 50 lignes, agrégats), `query_metrics`, `compare_periods`, `get_predictions`, `get_insights`, `get_safe_to_spend`. Chaque tool retourne du JSON issu des moteurs.
- Le prompt système interdit tout calcul : le modèle ne cite que des nombres présents dans les sorties de tools ; une vérification post-réponse signale les nombres absents des sorties (garde-fou).
- Conversations persistées (`advisor_conversations`, `advisor_messages`, avec les appels de tools).

## 11. Frontend

Next.js 15 (App Router) + TypeScript strict + Tailwind + ECharts + `react-grid-layout`. Composants style shadcn (Radix-free minimal en P0). Pages P0 : Command Center (grille de widgets persistée), Transactions (explorer), Data Health, Connexion bancaire, Ask. Palette ⌘K. Toutes les données viennent de l'API ; pas de calcul financier côté client.

## 12. Sécurité

- Secrets uniquement via variables d'environnement backend (`SecretStr`), `.env` ignoré par Git, `.env.example` sans valeurs.
- `session_id` bancaire chiffré (Fernet, `APP_ENCRYPTION_KEY`).
- `state` OAuth : 32 octets aléatoires, lié à l'utilisateur, TTL 15 min, usage unique ; callback refusé sinon.
- Cookies `HttpOnly; Secure (prod); SameSite=Lax` ; contrôle `Origin`/`Referer` pour méthodes mutantes.
- Logs : filtre qui masque IBAN, montants et libellés ; jamais de payload brut loggé.
- `audit_logs` : connexions, consentements, suppressions, exports.
- `DELETE /api/me` : suppression de toutes les données (cascade).
- Toutes les requêtes repository filtrent par `user_id`.
