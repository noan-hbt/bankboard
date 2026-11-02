# 05 — Déploiement Railway + PWA

## Topologie

```
                 Internet (HTTPS)
                       │
                ┌──────▼──────┐   seul service avec domaine public
                │  web (Next) │   PWA + proxy /api/* → BACKEND_URL
                └──────┬──────┘
          réseau privé │ http://api.railway.internal:8000
                ┌──────▼──────┐        ┌──────────────┐
                │ api (FastAPI)│◄──────►│  PostgreSQL  │
                └─────────────┘        └──────▲───────┘
                ┌─────────────┐               │
                │ worker      │───────────────┘  sync 6 h, snapshot quotidien, events
                └─────────────┘
```

## Étapes

1. **Projet Railway** → *New Project* → *Deploy from GitHub repo* (`bankboard`).
2. **PostgreSQL** : *New* → *Database* → *PostgreSQL*.
3. **Service `api`**
   - Root directory : `apps/api` · config file : `apps/api/railway.json`
   - Pas de domaine public (réseau privé uniquement).
   - Variables :
     ```
     DATABASE_URL=${{Postgres.DATABASE_URL}}        # converti automatiquement en postgresql+psycopg://
     APP_ENV=production
     APP_ENCRYPTION_KEY=<Fernet key>                  # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
     FRONTEND_URL=https://<web>.up.railway.app
     APP_BASE_URL=https://<web>.up.railway.app
     ALLOWED_ORIGINS=https://<web>.up.railway.app
     ENABLE_BANKING_APP_ID=<app id>
     ENABLE_BANKING_PRIVATE_KEY=<PEM, retours ligne échappés en \n>
     ENABLE_BANKING_ENV=production
     ENABLE_BANKING_REDIRECT_URL=https://<web>.up.railway.app/api/bank/callback
     LLM_PROVIDER=openrouter
     OPENROUTER_API_KEY=<ta clé OpenRouter>
     OPENROUTER_MODEL=anthropic/claude-opus-5.5
     PORT=8000
     ```
   - Les migrations Alembic s'exécutent au démarrage (`alembic upgrade head`, idempotent).
4. **Service `worker`** : même repo, root `apps/api`, config file `apps/api/railway.worker.json`, **mêmes variables** que `api` (Railway : *Shared variables*).
5. **Service `web`**
   - Root directory : `apps/web` · config file : `apps/web/railway.json`
   - *Generate domain* (c'est l'URL de l'app).
   - Variable : `BACKEND_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`
6. **Enable Banking** : dans le Control Panel, ajouter `https://<web>.up.railway.app/api/bank/callback` aux redirect URLs autorisées de l'application.
7. **Premier compte** : ouvrir l'URL, *Créer un compte*, puis *Connecter Revolut* (ou *Données démo*).

## Installer la PWA sur le téléphone

- **iOS (Safari)** : Partager → *Sur l'écran d'accueil*.
- **Android (Chrome)** : menu ⋮ → *Installer l'application*.

L'app s'ouvre en plein écran avec une barre de navigation basse. Le service worker ne met **jamais** en cache les données financières : hors ligne, seule une page d'information s'affiche.

## Sécurité en production

- Le backend n'a pas de domaine public ; seul `web` est exposé, en HTTPS (Railway).
- `APP_ENV=production` active le cookie `Secure`.
- Clé privée Enable Banking, clé OpenRouter et clé de chiffrement : uniquement dans les variables Railway du backend, jamais dans Git ni dans le bundle frontend.
- Sauvegardes : activer les backups du plugin PostgreSQL.
