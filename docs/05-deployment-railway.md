# 05 — Déploiement Railway + PWA

## Option A — 1 service, détection automatique (recommandé)

Le `Dockerfile` et le `railway.json` à la racine du repo sont détectés automatiquement par Railway.
Une seule image lance les trois processus (`deploy/start.sh`) : le web Next.js (public, sur `$PORT`),
l'API FastAPI (privée, `127.0.0.1:8000`) et le worker (sync toutes les 6 h, snapshot quotidien).
Si l'un des trois s'arrête, le conteneur s'arrête et Railway le redémarre.

1. *New Project* → *Deploy from GitHub repo* → `bankboard` (branche `main`). Aucun Root Directory à régler.
2. Dans le projet : *New* → *Database* → *PostgreSQL*.
3. Variables du service `bankboard` (onglet *Variables*) — seules 2 sont obligatoires :
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   APP_ENCRYPTION_KEY=<n'importe quelle chaîne aléatoire de 32+ caractères>
   OPENROUTER_API_KEY=<ta clé>                 # optionnel : active automatiquement l'IA OpenRouter
   ENABLE_BANKING_APP_ID=<app id>              # optionnel tant que tu utilises la démo
   ENABLE_BANKING_PRIVATE_KEY=<PEM, \n échappés>
   ```
   ⚠ Ne change jamais `APP_ENCRYPTION_KEY` ensuite : les sessions bancaires stockées deviendraient illisibles
   (la connexion passerait en « reconnexion nécessaire »).
4. *Settings* → *Networking* → *Generate Domain*.

Le reste est déduit automatiquement de `RAILWAY_PUBLIC_DOMAIN` : `FRONTEND_URL`, `APP_BASE_URL`,
`ALLOWED_ORIGINS`, `ENABLE_BANKING_REDIRECT_URL` (`https://<domaine>/api/bank/callback`) et `APP_ENV=production`
(cookie `Secure`). Les migrations s'exécutent à chaque démarrage. Toute valeur définie explicitement reste prioritaire.

5. Enable Banking : ajouter `https://<domaine>/api/bank/callback` aux redirect URLs de l'application.

## Option B — services séparés (si tu veux scaler indépendamment)

### Topologie

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

### Étapes

1. **Projet Railway** → *New Project* → *Deploy from GitHub repo* (`bankboard`).
2. **PostgreSQL** : *New* → *Database* → *PostgreSQL*.
3. **Service `api`**
   - Settings → Source → **Root Directory : `/apps/api`**
   - Settings → Config-as-code → **Railway Config File : `/apps/api/railway.json`** (chemin absolu depuis la racine du repo : le fichier n'est pas cherché dans le Root Directory)
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
4. **Service `worker`** : même repo, Root Directory `/apps/api`, Railway Config File `/apps/api/railway.worker.json`, **mêmes variables** que `api` (Railway : *Shared variables*).
5. **Service `web`**
   - Root Directory : `/apps/web` · Railway Config File : `/apps/web/railway.json`
   - *Generate domain* (c'est l'URL de l'app).
   - Variable : `BACKEND_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`
6. **Enable Banking** : dans le Control Panel, ajouter `https://<web>.up.railway.app/api/bank/callback` aux redirect URLs autorisées de l'application.
7. **Premier compte** : ouvrir l'URL, *Créer un compte*, puis *Connecter Revolut* (ou *Données démo*).

## Dépannage

- **« Railpack could not determine how to build the app »** : le service build la racine du repo. Renseigner Root Directory + Railway Config File comme ci-dessus ; le log de build doit alors afficher « Using Dockerfile ».

## Installer la PWA sur le téléphone

- **iOS (Safari)** : Partager → *Sur l'écran d'accueil*.
- **Android (Chrome)** : menu ⋮ → *Installer l'application*.

L'app s'ouvre en plein écran avec une barre de navigation basse. Le service worker ne met **jamais** en cache les données financières : hors ligne, seule une page d'information s'affiche.

## Sécurité en production

- Le backend n'a pas de domaine public ; seul `web` est exposé, en HTTPS (Railway).
- `APP_ENV=production` active le cookie `Secure`.
- Clé privée Enable Banking, clé OpenRouter et clé de chiffrement : uniquement dans les variables Railway du backend, jamais dans Git ni dans le bundle frontend.
- Sauvegardes : activer les backups du plugin PostgreSQL.
