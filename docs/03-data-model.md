# 03 — Modèle de données

Le schéma initial exécutable est dans [`apps/api/migrations/sql/0001_initial.sql`](../apps/api/migrations/sql/0001_initial.sql), appliqué par la migration Alembic `0001_initial`. Les modèles SQLAlchemy (`apps/api/src/bankboard/models/`) en sont le miroir ; les tests tournent sur une base migrée, ce qui détecte toute divergence.

## Principes

- **Montants** `NUMERIC(19,4)` signés (`< 0` = sortie), devise ISO à côté.
- **Brut immuable** : `transaction_raw.payload` = première observation, révisions ultérieures dans `payload_history`. `transactions` est une projection rejouable.
- **Classification traçable** : `kind`/`category_key` + `*_confidence` + `*_source ∈ {bank, rule, historical, model, manual}`. `manual` gagne toujours.
- **Isolation** : `user_id` sur toute table possédée ; `ON DELETE CASCADE` depuis `users` ⇒ « supprimer toutes mes données » = `DELETE FROM users WHERE id = …`.
- **Contraintes CHECK** plutôt que types ENUM PostgreSQL (évolution plus simple).
- **Secrets** : seul `bank_sessions.session_ref_enc` contient un secret, chiffré (Fernet). IBAN : masqué + hash.

## Tables P0 (migration 0001)

| Domaine | Tables |
|---|---|
| Identité | `users`, `user_sessions`, `user_preferences` |
| Banque | `bank_auth_requests` (state anti-CSRF), `bank_connections`, `bank_sessions`, `accounts`, `balances`, `sync_jobs` |
| Ledger | `transaction_raw`, `transactions`, `tags`, `transaction_tags` |
| Référentiel | `categories`, `merchants`, `merchant_aliases`, `classification_rules` |
| Prédiction | `recurring_patterns`, `expected_transactions` |
| Objectifs | `goals`, `goal_contributions` |
| État | `financial_snapshots` |
| Moteur | `domain_events`, `insights`, `recommendations`, `feed_items` |
| IA | `advisor_conversations`, `advisor_messages` |
| UI | `dashboard_layouts` |
| Sécurité | `audit_logs` |

### Clés d'idempotence

| Table | Unicité |
|---|---|
| `transaction_raw` | `(account_id, dedup_key)` |
| `transactions` | `raw_id` |
| `balances` | `(account_id, balance_type, reference_date)` |
| `accounts` | `(connection_id, provider_account_ref)` |
| `recurring_patterns` | `(user_id, series_key)` |
| `financial_snapshots` | `(user_id, snapshot_date)` |
| `insights` | `(user_id, fingerprint)` |
| `feed_items` | `(user_id, dedup_key)` |

## Tables prévues (migrations futures, par module)

| Migration | Module | Tables |
|---|---|---|
| 0002 | projects / people | `projects` (budget, dates, tag lié), `people` (tag lié) — les liens transaction passent par `transaction_tags` |
| 0003 | income | `income_sources`, `income_events` |
| 0004 | wealth / investments | `assets`, `liabilities`, `investment_accounts`, `investment_positions`, `investment_transactions`, `market_prices` |
| 0005 | budgets | `budgets` |
| 0006 | financial_twin / memory | `financial_metrics` (série temporelle clé/valeur), `financial_events`, `financial_memory`, `twin_profiles` |
| 0007 | forecasting / simulator | `predictions`, `forecast_runs`, `forecast_scenarios`, `simulations`, `simulation_inputs`, `simulation_results` |
| 0008 | advisor | `recommendation_outcomes`, `decision_journal` |
| 0009 | P3 | `transaction_ratings` (regret/value), `purchase_lifetimes` |

## Vocabulaire `kind`

| kind | Revenu | Dépense | Épargne | Patrimoine |
|---|---|---|---|---|
| `income` | ✔ | | | + |
| `consumption` | | ✔ | | − |
| `fee` | | ✔ | | − |
| `debt_payment` | | ✔ (P0) | | neutre quand les passifs seront suivis |
| `refund` | | réduit la dépense de sa catégorie | | + |
| `transfer` | | | | neutre (interne) |
| `investment` | | | ✔ | neutre (déplacement d'actif) quand le compte investissement est suivi ; sinon sortie du périmètre suivi, signalée |
