# 04 — Plan de développement

Développement **vertical** : chaque étape livre un incrément utilisable et testé.

## Graphe de dépendances (P0)

```
[1 Fondations] ─┬─> [2 Auth] ─┐
                └─> [3 Schéma/Migrations] ─┬─> [4 Provider abstraction + Demo] ─> [5 Enable Banking]
                                           │                │
                                           │                ▼
                                           └──────────> [6 Sync idempotente]
                                                            │
                                                            ▼
                                     [7 Pipeline: merchants → transfers → classify]
                                                            │
                                                            ▼
                                     [8 Recurring + expected timeline]
                                                            │
                                      ┌─────────────────────┼─────────────────────┐
                                      ▼                     ▼                     ▼
                              [9 Métriques/cashflow] [10 Safe-to-spend]   [11 Snapshots + score]
                                      └─────────────┬───────┴─────────────────────┘
                                                    ▼
                                     [12 What Changed + détecteurs + insights]
                                                    │
                                ┌───────────────────┼─────────────────────┐
                                ▼                   ▼                     ▼
                       [13 API Command Center] [14 Ask basique]   [15 Jobs + events]
                                └───────────────────┬─────────────────────┘
                                                    ▼
                                     [16 Frontend: grille, Command Center, explorer, Data Health]
```

## Étapes P0

| # | Livrable | Critère de fin | Statut |
|---|---|---|---|
| 1 | Monorepo, config typée, logging filtré, Postgres dev | `make test` vert | ✅ |
| 2 | Auth (register/login/logout, sessions cookie, Origin check) | tests auth | ✅ |
| 3 | Schéma 0001 + modèles SQLAlchemy + Alembic | `alembic upgrade head` OK, tests sur base migrée | ✅ |
| 4 | `BankingProvider`, DTO, `DemoProvider` + générateur 12 mois | démo seedée via le même chemin que EB | ✅ |
| 5 | `EnableBankingProvider` (JWT RS256, aspsps, auth, sessions, comptes, soldes, transactions paginées), flux callback avec state | tests avec transport HTTP mocké | ✅ code + tests mockés — **à valider contre le sandbox Enable Banking réel** (nécessite tes identifiants) |
| 6 | Sync idempotente (raw + projection + pending + balances + sync_jobs) | rejouer 3× = même état | ✅ |
| 7 | Pipeline marchands / virements / classification | tests virements, remboursements, revenus, catégories, priorité manuelle | ✅ |
| 8 | Récurrences + `expected_transactions` | tests cadence mensuelle/hebdo, salaire | ✅ |
| 9 | Cashflow | tests exacts au centime | ✅ |
| 10 | Safe-to-spend 4 horizons + explication | tests | ✅ |
| 11 | Snapshots quotidiens + backfill + Financial State Score explicable | tests | ✅ |
| 12 | What Changed + détecteurs + insights dédupliqués | tests | ✅ |
| 13 | API Command Center (NOW / NEXT / ATTENTION / OPPORTUNITIES) + widgets | tests API | ✅ |
| 14 | Ask Your Money basique (LLMProvider, OpenRouter, tools, mode offline, garde-fou sur les nombres) | tests tools | ✅ (OpenRouter testé avec transport mocké) |
| 15 | Event outbox + CLI jobs + scheduler | tests | ✅ |
| 16 | Frontend Next.js PWA : Command Center en grille personnalisable, explorer, Data Health, connexion banque, Ask, ⌘K | build OK + parcours vérifié dans Chromium (desktop/mobile, clair/sombre) | ✅ |
| 17 | Déploiement Railway (api, worker, web, Postgres) + CI GitHub Actions | Dockerfiles + config-as-code | ✅ fichiers prêts — images non construites dans cet environnement (pas de démon Docker) |

### Prochaines étapes immédiates (avant P1)
1. Brancher les vrais identifiants Enable Banking (sandbox puis production) et valider le flux Revolut de bout en bout.
2. Déployer sur Railway, installer la PWA sur le téléphone.
3. Passer 2-3 semaines d'usage réel : corriger les règles de classification / marchands sur tes données (c'est là que la qualité se joue).

## P1 — Intelligence (ordre conseillé)

1. Data Confidence Score complet + écran Data Health enrichi (doublons possibles, catégories incertaines) — *prérequis de confiance de l'Advisor*.
2. Burn rate + runway (dépend : classification essentiel/lifestyle).
3. Cash Buffer Intelligence (remplace le buffer par défaut du safe-to-spend).
4. Shadow recurring (extension du détecteur de récurrence aux habitudes quasi périodiques).
5. Financial Drift + Lifestyle Creep (dépend : snapshots mensuels ≥ 6 mois).
6. Salary anchoring + spending velocity (dépend : `is_salary`).
7. Personal / merchant inflation.
8. Goals intelligents (date estimée, probabilité — version déterministe avant Monte Carlo).
9. Flexibility / Fragility / Income dependency.
10. Financial Twin : agrégation des profils + historique + confiance.
11. Financial Memory (événements significatifs détectés + manuels).
12. Advisor (daily / weekly / monthly closing) + Advisor memory + recommendation tracking.

## P2 — Simulation

Monte Carlo (moteur vectorisé NumPy réutilisant les distributions des récurrences et de la dépense variable) → Decision Lab (baseline vs décision sur le même moteur) → Opportunity cost → Goal conflict → Stress tests / Resilience matrix (scénarios = transformations des entrées du moteur) → Capital allocation / Unexpected money → Time Machine (lecture des snapshots).

## P3 — Expérimental

Modules désactivés par défaut : regret/value, half-life, entropy, merchant dependency, fingerprint, weather, people ledger.
