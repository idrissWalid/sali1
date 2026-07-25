from app.services.gemini_service import complete_text
from app.services.model_specs import ModelFamily, MODEL_SPECS
from app.core import config

ML_KEYWORDS = [
    "prédis", "prédit", "prédire", "prédiction", "modèle", "entraîne",
    "classification", "régression", "clustering", "cluster", "segmentation",
    "anomalie", "détecte", "série temporelle", "prévision", "forecast",
    "machine learning", "ml", "random forest", "xgboost", "kmeans",
]

def is_ml_request(message: str) -> bool:
    message_lower = message.lower()
    return any(kw in message_lower for kw in ML_KEYWORDS)

def detect_model_family(question: str, model: str | None = None) -> ModelFamily:
    model = model or config.get_default_model()
    prompt = f"""
Analyse la requête utilisateur suivante : '{question}'
Détermine la famille de modèle Machine Learning la plus appropriée.
Réponds UNIQUEMENT avec l'une des valeurs suivantes, sans aucun autre texte :
logistic_regression
linear_regression
tree_ensemble
clustering
factor_analysis

Si c'est pour prédire une catégorie/classe (classification) -> tree_ensemble (par défaut) ou logistic_regression
Si c'est pour prédire une valeur continue (régression) -> tree_ensemble (par défaut) ou linear_regression
Si c'est pour grouper/segmenter -> clustering
Si c'est pour réduire la dimension ou faire une ACP -> factor_analysis
    """
    try:
        val = complete_text(prompt, model).strip().lower()

        if val in [f.value for f in ModelFamily]:
            return ModelFamily(val)
    except Exception:
        pass
    
    # Fallback par défaut (Random Forest etc. peuvent faire classif ou regression)
    return ModelFamily.TREE_ENSEMBLE


def generate_ml_code(question: str, data_context: str, family: ModelFamily, history: list = [], model: str | None = None) -> str:
    model = model or config.get_default_model()
    spec = MODEL_SPECS[family]

    prompt = f"""
Tu es un expert en machine learning Python.

{data_context}

Demande utilisateur : {question}

{spec.prompt_fragment}

Le dataframe est dans la variable `df`.
Ne mets aucun commentaire ni markdown. Code Python pur uniquement.

IMPORTANT: Tu dois PRIVILÉGIER les courbes et visualisations (matplotlib/seaborn) pour illustrer les résultats du modèle de façon claire.

CRITIQUE: Si tu entraînes un modèle prédictif (Classification, Régression, etc.), tu DOIS OBLIGATOIREMENT :
1. Le sauvegarder avec `joblib.dump(model, "nom_du_modele.pkl")`
2. Créer un fichier `"nom_du_modele_metadata.json"` contenant un dictionnaire JSON strict avec :
   - "model_type": (ex: "RandomForestRegressor")
   - "features": liste des noms exacts des colonnes d'entrée (ex: ["Age", "Revenu"])
   - "metrics": dictionnaire des performances (ex: {{ "Accuracy": 0.85 }})

Bibliothèques disponibles : pandas, numpy, matplotlib, seaborn, 
statsmodels, scikit-learn, joblib.
"""
    try:
        code = complete_text(prompt, model, history).strip()
        if code.startswith("```"):
            lines = code.split("\n")
            if lines[-1].startswith("```"):
                code = "\n".join(lines[1:-1])
            else:
                code = "\n".join(lines[1:])
        return code
    except Exception as e:
        return ""


def generate_timeseries_code(
    question: str,
    data_context: str,
    history: list = [],
    model: str | None = None,
    date_col: str | None = None,
    value_col: str | None = None,
    horizon: int | None = None,
) -> str:
    """Génère le code Python du pipeline ARIMA/SARIMA rigoureux (méthodologie A–H).

    L'agent choisit ARIMA vs SARIMA selon la saisonnalité. Les colonnes date/valeur
    et l'horizon peuvent être imposés (bouton Entraîner) ou déduits (chat)."""
    model = model or config.get_default_model()
    spec = MODEL_SPECS[ModelFamily.TIME_SERIES]

    col_hint = ""
    if date_col or value_col:
        col_hint = (
            f"\nColonnes imposées par l'utilisateur : "
            f"colonne DATE = '{date_col}', colonne VALEUR = '{value_col}'. Utilise-les telles quelles."
        )
    horizon_hint = f"\nHorizon de prévision future demandé : {horizon} périodes." if horizon else ""

    prompt = f"""
Tu es un expert en séries temporelles Python (statsmodels).

{data_context}

Demande utilisateur : {question}{col_hint}{horizon_hint}

{spec.prompt_fragment}

Le dataframe est dans la variable `df`.
Ne mets aucun commentaire superflu ni markdown. Code Python pur uniquement.
Bibliothèques disponibles : pandas, numpy, matplotlib, statsmodels, scipy, scikit-learn.
"""
    code = complete_text(prompt, model, history).strip()
    if code.startswith("```"):
        lines = code.split("\n")
        if lines[-1].startswith("```"):
            code = "\n".join(lines[1:-1])
        else:
            code = "\n".join(lines[1:])
    return code


def generate_ml_interpretation(question: str, output: str, data_context: str, has_images: bool, history: list = [], model: str | None = None) -> str:
    model = model or config.get_default_model()
    prompt = f"""
{data_context}

L'utilisateur a demandé : {question}

Voici les métriques produites par le modèle :
{output or "Aucune sortie texte."}
{"Des visualisations ont été générées et sont affichées." if has_images else ""}

Rédige une interprétation structurée en trois parties :
1. **Modèle utilisé** : donne TOUJOURS les détails spécifiques du modèle utilisé (type exact, paramètres importants, pourquoi il est adapté).
2. **Performance** : interprétation des métriques générées (coefficients, R², p-values, variables importantes, clusters, etc.). Mentionne explicitement les courbes générées s'il y en a.
3. **Recommandations** : ce que les résultats impliquent concrètement

Sois précis, concis, et accessible à un utilisateur standard.
Réponds en français.
"""
    try:
        return complete_text(prompt, model, history).strip()
    except Exception as e:
        return "Interprétation indisponible."