# Bankboard — Personal Finance OS

Cockpit financier personnel : jumeau financier, moteurs déterministes explicables, IA qui explique sans jamais calculer.

| Doc | Contenu |
|---|---|
| [01 — Analyse du PRD](docs/01-prd-analysis.md) | invariants, décisions, risques |
| [02 — Architecture](docs/02-architecture.md) | monorepo, couches, banking, pipeline, moteurs, modules, events, IA, PWA |
| [03 — Modèle de données](docs/03-data-model.md) · [schéma SQL](apps/api/migrations/sql/0001_initial.sql) | |
| [04 — Roadmap](docs/04-roadmap.md) | P0 → P3, dépendances, statut |
| [05 — Déploiement Railway + PWA](docs/05-deployment-railway.md) | |

## Structure

```
apps/api   FastAPI · SQLAlchemy 2 · Alembic · Polars — sync bancaire, pipeline, moteurs, API
apps/web   Next.js 15 PWA · Tailwind · ECharts — Command Center, explorer, Ask, réglages
docs/      conception
```

## Démarrage local

```bash
docker compose up -d postgres
```

```bash
cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cp .env.example .env   # renseigner APP_ENCRYPTION_KEY (et OpenRouter / Enable Banking si dispo)
```

```bash
alembic upgrade head && python -m bankboard.jobs seed-demo --email demo@bankboard.local --password demo-password-1
```

```bash
uvicorn bankboard.main:app --reload --port 8000
```

```bash
cd apps/web && npm install && BACKEND_URL=http://localhost:8000 npm run dev
```

Ouvrir http://localhost:3000 et se connecter avec le compte démo (12 mois de données synthétiques passant par le même chemin de code que la banque).

## Qualité

```bash
cd apps/api && ruff check src tests && mypy && pytest
```

```bash
cd apps/web && npm run typecheck && npm run build
```

## Principes non négociables

- Aucun chiffre calculé par le LLM : tools typés → moteurs déterministes ; garde-fou qui signale tout nombre absent des sorties d'outils.
- Données bancaires brutes conservées (`transaction_raw`, append-only) ; tout le reste est rejouable.
- Sync idempotente ; une transaction n'est jamais dupliquée.
- Correction manuelle toujours prioritaire.
- Chaque métrique complexe a son « Why? », chaque prédiction sa confiance.
- Ni Revolut, ni Enable Banking, ni OpenRouter ne sont des dépendances structurelles (abstractions `BankingProvider`, `LLMProvider`).
