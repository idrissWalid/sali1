# No-Code Data Intelligence

Une application complète pour l'analyse intelligente de données (Frontend Next.js + Backend FastAPI).

## Prérequis

- **Docker** (recommandé pour une exécution simplifiée)
- **Node.js** (v18+) et **npm** (si exécution locale du frontend)
- **Python** (3.10+) (si exécution locale du backend)
- **Clé API Gemini** (obligatoire pour les fonctionnalités d'analyse par l'IA)

## Configuration Initiale

Avant de lancer l'application, vous devez configurer vos variables d'environnement.

1. Créez un fichier `.env` dans le dossier `backend/` :
   ```bash
   # Dans le fichier backend/.env
   GEMINI_API_KEY=votre_cle_api_gemini_ici
   ```

2. **Avant tout déploiement hors localhost**, protégez l'API avec une clé partagée (aucun endpoint n'est authentifié sinon) :
   ```bash
   # Toujours dans backend/.env
   API_AUTH_KEY=une_valeur_secrete_longue_et_aleatoire
   ```
   Sans cette variable, l'API reste ouverte (comportement par défaut, pratique en local). Une fois définie, toute requête doit porter l'en-tête `X-API-Key` avec la même valeur — le frontend la lit depuis `NEXT_PUBLIC_API_KEY` (à définir côté frontend avec la même valeur) et l'ajoute automatiquement.

## Lancement avec Docker (Recommandé)

Le fichier `docker-compose.yml` est configuré avec les limites de mémoire adéquates pour faire tourner les modèles de Machine Learning du backend (ex: ydata-profiling, scikit-learn, statsmodels, etc).

À la racine du projet, exécutez simplement :

```bash
docker-compose up --build
```

- Le frontend sera accessible sur : `http://localhost:3000`
- Le backend sera accessible sur : `http://localhost:8000` (Documentation de l'API sur `http://localhost:8000/docs`)

## Lancement Local (Sans Docker)

### Option A — script PowerShell (Windows, recommandé)

`dev.ps1` fait tout ce que la procédure manuelle ci-dessous décrit : création du venv, installation des dépendances Python et npm quand elles ont changé, vérification des ports, propagation de `API_AUTH_KEY` vers le frontend, démarrage des deux serveurs et arrêt propre au `Ctrl+C`.

```powershell
.\dev.ps1
```

Options utiles :

| Option | Effet |
| --- | --- |
| `-Frontend frontend-redesign` | Lance une autre variante de frontend (`frontend`, `frontend-harmonized`, `frontend-redesign`) |
| `-BackendPort 8010 -FrontendPort 3010` | Change les ports (utile pour deux instances en parallèle) |
| `-Install` | Force la réinstallation des dépendances Python et npm |
| `-BackendOnly` / `-FrontendOnly` | Ne démarre qu'un seul des deux serveurs |
| `-Separate` | Ouvre chaque serveur dans sa propre fenêtre PowerShell |
| `-Force` | Tue le processus qui occupe un port au lieu de s'arrêter |
| `-NoBrowser` | N'ouvre pas le navigateur |

Si PowerShell refuse d'exécuter le script (politique d'exécution) :

```powershell
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

### Option B — manuellement, en deux terminaux

Si vous préférez exécuter l'application localement, suivez ces étapes dans deux terminaux séparés.

### 1. Démarrer le Backend (FastAPI)

Ouvrez un terminal et placez-vous dans le dossier `backend` :

```bash
cd backend
```

Créez et activez un environnement virtuel Python :

```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / MacOS
python3 -m venv venv
source venv/bin/activate
```

Installez les dépendances requises :

```bash
pip install -r requirements.txt
```

*(Note : le fichier `requirements.txt` a été optimisé avec des versions spécifiques de `numpy`, `numba` et `setuptools` pour garantir la compatibilité des librairies d'analyse).*

Lancez le serveur backend :

```bash
python run_server.py
```
Le backend tourne désormais sur `http://127.0.0.1:8000`.

### 2. Démarrer le Frontend (Next.js)

Ouvrez un deuxième terminal et placez-vous dans le dossier `frontend` :

```bash
cd frontend
```

Installez les packages npm :

```bash
npm install
```

Lancez le serveur de développement :

```bash
npm run dev
```
Le frontend est accessible sur `http://localhost:3000`.
