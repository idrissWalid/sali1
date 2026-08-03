# No-Code Data Intelligence - Serveur Backend (FastAPI)

Ce répertoire contient les services backend de l'application **No-Code Data Intelligence**, conçue pour l'analyse intelligente de données pour les institutions.

Il comporte deux services FastAPI distincts :
1. **API Principale (Port 8000)** : Gère le chat intelligent, l'upload de données et la génération de rapports d'analyse.
2. **API d'Évaluation (Port 8001)** : Évalue la qualité des résumés de documents PDF en mesurant des métriques comme ROUGE, BERTScore et le taux de compression.

---

## Prérequis

- **Python 3.10+**
- Une clé API Gemini (Google AI Studio).

---

## Configuration

1. **Création et activation de l'environnement virtuel :**
   Depuis la racine du projet ou le dossier `backend` :
   ```bash
   # Création
   python3 -m venv venv
   
   # Activation (Linux/macOS)
   source venv/bin/activate
   
   # Activation (Windows)
   venv\Scripts\activate
   ```

2. **Installation des dépendances :**
   Installez toutes les bibliothèques requises (y compris celles pour l'évaluation textuelle et sémantique) :
   ```bash
   pip install -r requirements.txt
   ```

3. **Variables d'environnement :**
   Créez un fichier `.env` dans le dossier `backend/` (s'il n'existe pas déjà) et renseignez votre clé Gemini :
   ```env
   GEMINI_API_KEY=votre_cle_api_ici
   ```

   Les autres fournisseurs (OpenAI, Anthropic, Mistral, Groq) se configurent
   depuis l'interface — *Préférences → Modèle IA → Configurer l'API* — qui teste
   la clé avant de l'écrire ici.

### Fournisseur « Autre » (compatible OpenAI)

La même boîte de dialogue propose une catégorie **Autre**, pour tout point
d'entrée qui parle le protocole d'OpenAI : vLLM, LM Studio, OpenRouter,
Together, un proxy interne… Trois champs à saisir — **URL**, **modèle**,
**clé API** — au lieu d'un modèle choisi dans un catalogue.

Trois variables sont alors écrites dans `.env` :

```env
CUSTOM_API_BASE_URL=https://api.exemple.com/v1
CUSTOM_API_MODEL=nom-exact-du-modele
CUSTOM_API_KEY=votre_cle
```

L'URL est la **racine** du point d'entrée : `/chat/completions` est ajouté par
le code. Si vous collez l'URL complète, le slash final ou le suffixe sont
retirés automatiquement (`normaliser_base_url`).

Le modèle apparaît ensuite dans les listes sous la forme `custom/<modèle>`, et
n'est proposé que si les trois réglages sont présents — sinon la première
question échouerait. La clé est testée par une requête minimale avant d'être
enregistrée, et rien n'est écrit si le test échoue.

La lecture d'images fonctionne aussi via ce fournisseur, mais seulement si le
nom du modèle contient un marqueur multimodal connu (`gpt-4o`, `claude-3`,
`pixtral`, `qwen2.5-vl`…) : `supporte_vision` refuse en cas de doute plutôt que
d'échouer au milieu d'un appel payant.

---

## Lancement des Serveurs

Les deux services peuvent être lancés séparément depuis le dossier `backend/` :

### 1. Démarrer l'API Principale (Port 8000)
Ce service est indispensable pour le frontend Next.js et pour générer les résumés analysés par le module d'évaluation.
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- **Documentation Swagger :** `http://127.0.0.1:8000/docs`
- **Endpoints clés :**
  - `POST /api/upload` : Upload et analyse de fichiers (CSV, Excel, PDF).
  - `POST /api/chat` : Agent de chat interactif.
  - `POST /api/report` : Génération automatique de rapports d'analyse.

### 2. Démarrer l'API d'Évaluation (Port 8001)
Ce service permet de tester et comparer la qualité des résumés générés par rapport au document original.
```bash
python3 evaluate_app.py
```
*(ou `uvicorn evaluate_app:app --host 0.0.0.0 --port 8001 --reload`)*

- **Interface Web intégrée :** `http://127.0.0.1:8001/` (Interface d'évaluation interactive).
- **Documentation Swagger :** `http://127.0.0.1:8001/docs`
- **Endpoints clés :**
  - `POST /evaluate` : Prend un fichier PDF, appelle l'API principale pour le résumer, extrait le texte source et calcule les scores ROUGE (1, 2, L) et BERTScore.
