import asyncio
import pandas as pd
import numpy as np
import json
import math
import re
from app.services.gemini_service import ask_gemini
from app.services.profiling_service import generate_profiling_stats
from app.core import config

# ── Choix des graphiques du dashboard ────────────────────────────────────────
# Le type de graphique est déduit des propriétés mesurées de chaque colonne
# (cardinalité, continuité, lien réel au temps) et non de son seul dtype : c'est
# ce qui évite les camemberts à dix parts ou les « séries temporelles » tracées
# sur des variables qui n'ont aucun rapport avec le temps.

MAX_DISCRETE_VALUES = 12     # au-delà, une numérique est traitée comme continue
MAX_DONUT_SLICES = 5         # un anneau reste lisible jusqu'à ~5 parts
MAX_BAR_CATEGORIES = 25      # au-delà, on agrège la traîne dans « Autres catégories »
TOP_CATEGORIES = 15
IDENTIFIER_NAME_PATTERN = re.compile(r"(^|_)(id|uuid|guid|code|ref|reference|email|mail|url|slug)($|_)", re.I)

# ── Valeurs manquantes ───────────────────────────────────────────────────────
# Une donnée absente n'est PAS une modalité : elle ne doit apparaître ni comme
# une part du camembert, ni comme une barre, ni dans la traîne « Autres ». Le
# graphique décrit la distribution des valeurs observées ; le volume manquant est
# rapporté à part (`n_missing`), pas mélangé aux catégories réelles.
#
# `read_csv` neutralise déjà ces écritures, mais pas les valeurs venues d'un
# Excel, d'un OCR ou d'un tableau extrait d'un PDF : elles y arrivent sous forme
# de chaînes. On applique donc la même règle qu'au CSV, à l'identique — la liste
# se limite à des écritures purement techniques du « vide ». Les placeholders
# ambigus (« - », « ? », « inconnu ») restent des modalités : les traiter comme
# manquants ferait disparaître sans trace une catégorie potentiellement réelle.
MISSING_TOKENS = frozenset({
    "", "#n/a", "#n/a n/a", "#na", "-1.#ind", "-1.#qnan", "-nan", "1.#ind",
    "1.#qnan", "<na>", "n/a", "na", "nan", "nat", "none", "null",
})


def _drop_missing(series: pd.Series) -> pd.Series:
    """Retire les valeurs manquantes, y compris celles écrites en toutes lettres.

    `dropna` seul laisse passer les manquants stockés comme texte (« N/A »,
    « NULL », cellule contenant une espace) : ils deviendraient alors une
    modalité à part entière dans le dashboard.
    """
    series = series.dropna()
    if series.empty or not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return series
    blank = series.map(lambda value: isinstance(value, str) and value.strip().lower() in MISSING_TOKENS)
    return series[~blank]


def _null_if_missing(value):
    """`None` pour tout manquant pandas (NaN, NaT, pd.NA), la valeur sinon."""
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        # `pd.isna` renvoie un tableau sur une valeur composite : pas un manquant.
        pass
    return convert_types(value)


def _preview_records(frame: pd.DataFrame, limit: int = 5) -> list[dict]:
    """Aperçu sérialisable en JSON, les manquants devenant `null`.

    La neutralisation est faite ICI, sur la seule copie destinée à l'affichage.
    L'appliquer au DataFrame d'analyse (`df.replace({np.nan: None})`) basculerait
    en dtype `object` toute colonne contenant un manquant : une numérique ou une
    date cesserait alors d'être reconnue comme telle et serait tracée comme une
    catégorielle, chaque valeur devenant une modalité.
    """
    return [
        {key: _null_if_missing(value) for key, value in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def _discrete_label(value) -> str:
    """Libellé d'une modalité numérique discrète.

    Une colonne 0/1 comportant des manquants est typée `float64` par pandas :
    sans ça, ses modalités s'afficheraient « 0.0 » et « 1.0 ».
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _nice_step(raw_step: float) -> float:
    """Arrondit un pas au multiple « rond » 1/2/5 × 10ⁿ immédiatement supérieur.

    C'est ce qui donne des bornes de classes lisibles (0–5, 5–10…) au lieu des
    bornes brutes de numpy (2.37–4.81).
    """
    if raw_step <= 0 or not math.isfinite(raw_step):
        return 1.0
    exponent = math.floor(math.log10(raw_step))
    magnitude = 10.0 ** exponent
    for multiple in (1, 2, 2.5, 5, 10):
        if raw_step <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude


def _format_bound(value: float, step: float) -> str:
    """Formate une borne avec juste assez de décimales pour rester distincte."""
    decimals = 0 if step >= 1 else min(2, int(abs(math.floor(math.log10(step)))) + 1)
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _build_histogram(series: pd.Series, target_bins: int = 10) -> list[dict]:
    """Histogramme à bornes rondes. Renvoie aussi les bornes numériques pour que
    le frontend puisse formater/échelonner lui-même."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return []

    vmin, vmax = float(values.min()), float(values.max())
    if vmin == vmax:
        return [{"name": _format_bound(vmin, 1), "value": int(values.size),
                 "bin_start": vmin, "bin_end": vmin}]

    step = _nice_step((vmax - vmin) / target_bins)
    start = math.floor(vmin / step) * step
    end = math.ceil(vmax / step) * step
    edges = np.arange(start, end + step / 2, step)
    if len(edges) < 2:
        edges = np.array([start, start + step])

    counts, edges = np.histogram(values, bins=edges)
    return [
        {
            "name": f"{_format_bound(edges[i], step)} – {_format_bound(edges[i + 1], step)}",
            "value": int(counts[i]),
            "bin_start": float(edges[i]),
            "bin_end": float(edges[i + 1]),
        }
        for i in range(len(counts))
    ]


def _category_counts(series: pd.Series) -> list[dict]:
    """Effectifs par catégorie, la traîne étant regroupée séparément.

    Le nettoyage est refait ici, APRÈS `astype(str)`, plutôt que supposé fait par
    l'appelant : la conversion en texte transforme tout manquant résiduel en
    « nan » / « NaT » / « None », qui passerait ensuite pour une modalité
    ordinaire — voire irait grossir « Autres », où plus rien ne permettrait de la
    distinguer.
    """
    counts = _drop_missing(series.astype(str)).value_counts()
    if len(counts) > MAX_BAR_CATEGORIES:
        head = counts.head(TOP_CATEGORIES)
        data = [{"name": str(k), "value": int(v)} for k, v in head.items()]
        # Ce libellé ne désigne que les catégories observées les moins fréquentes.
        # Les valeurs manquantes ont été retirées avant ce comptage.
        data.append({"name": "Autres catégories", "value": int(counts.iloc[TOP_CATEGORIES:].sum())})
        return data
    return [{"name": str(k), "value": int(v)} for k, v in counts.items()]


def _aggregation_period(span_days: float) -> tuple[str, str]:
    """Granularité d'agrégation temporelle adaptée à l'amplitude couverte."""
    if span_days <= 2:
        return "h", "%d/%m %Hh"
    if span_days <= 90:
        return "D", "%d/%m/%Y"
    if span_days <= 1095:
        return "M", "%m/%Y"
    return "Y", "%Y"


# Granularités proposées à l'utilisateur, de la plus fine à la plus grossière.
GRANULARITIES = [
    {"key": "h", "label": "Heure", "format": "%d/%m %Hh"},
    {"key": "D", "label": "Jour", "format": "%d/%m/%Y"},
    {"key": "W", "label": "Semaine", "format": "%d/%m/%Y"},
    {"key": "M", "label": "Mois", "format": "%m/%Y"},
    {"key": "Q", "label": "Trimestre", "format": "T%q %Y"},
    {"key": "Y", "label": "Année", "format": "%Y"},
]
# Au-delà, la courbe devient illisible et la réponse inutilement lourde : la
# granularité n'est alors pas proposée.
MAX_SERIES_POINTS = 600
# Granularité retenue par défaut : la plus fine qui reste confortable à lire.
PREFERRED_DEFAULT_POINTS = 400


def _format_period(period, date_format: str) -> str:
    """Formate un pandas.Period ; %q n'existe pas en strftime, on l'injecte."""
    timestamp = period.to_timestamp()
    if "%q" in date_format:
        return date_format.replace("%q", str(timestamp.quarter)).replace("%Y", str(timestamp.year))
    return timestamp.strftime(date_format)


def _build_time_series(frame: pd.DataFrame, time_col: str, value_col: str, how: str = "mean") -> dict | None:
    """Construit une série temporelle à plusieurs granularités.

    Toutes les granularités pertinentes sont calculées d'un coup : l'utilisateur
    bascule ainsi de « mensuel » à « annuel » sans recharger quoi que ce soit.
    Le défaut est la granularité la plus FINE qui reste lisible — remplacer un
    historique mensuel par 12 points annuels ferait disparaître la saisonnalité.
    """
    frame = frame.dropna(subset=[time_col, value_col]).sort_values(time_col)
    if frame.empty:
        return None

    span_days = (frame[time_col].max() - frame[time_col].min()).total_seconds() / 86400
    series_by_granularity = {}

    for granularity in GRANULARITIES:
        key = granularity["key"]
        # Une granularité plus fine que le pas réel des données n'apporte rien.
        if key == "h" and span_days > 10:
            continue
        if key == "D" and span_days > 1500:
            continue
        if key == "W" and span_days > 5000:
            continue

        try:
            periods = frame[time_col].dt.to_period(key)
        except Exception:
            continue

        grouped = frame.groupby(periods)[value_col]
        aggregated = grouped.mean() if how == "mean" else grouped.size()
        if aggregated.empty or len(aggregated) > MAX_SERIES_POINTS or len(aggregated) < 2:
            continue

        series_by_granularity[key] = {
            "label": granularity["label"],
            "points": [
                {
                    "name": _format_period(period, granularity["format"]),
                    "ts": int(period.to_timestamp().timestamp() * 1000),
                    "value": float(value),
                }
                for period, value in aggregated.items()
            ],
        }

    if not series_by_granularity:
        return None

    ordered = [g["key"] for g in GRANULARITIES if g["key"] in series_by_granularity]

    # Une granularité plus fine qui produit autant de points qu'une plus
    # grossière ne subdivise rien : des relevés mensuels regroupés « par
    # semaine » donnent toujours un point par mois, avec des libellés trompeurs.
    informative = []
    for index, key in enumerate(ordered):
        point_count = len(series_by_granularity[key]["points"])
        if any(len(series_by_granularity[coarser]["points"]) == point_count for coarser in ordered[index + 1:]):
            continue
        informative.append(key)
    ordered = informative or ordered[-1:]

    # La plus fine qui reste sous le seuil de confort, sinon la plus fine dispo.
    default_key = next(
        (k for k in ordered if len(series_by_granularity[k]["points"]) <= PREFERRED_DEFAULT_POINTS),
        ordered[0],
    )

    return {
        "granularities": [
            {"key": k, "label": series_by_granularity[k]["label"], "points": len(series_by_granularity[k]["points"])}
            for k in ordered
        ],
        "default_granularity": default_key,
        "series": {k: series_by_granularity[k]["points"] for k in ordered},
        "data": series_by_granularity[default_key]["points"],
    }

def format_axis_number(x: float) -> str:
    """Formate une valeur numérique pour l'affichage sur un axe de graphique
    (évite les libellés à rallonge du type '123456.7' qui se chevauchent une
    fois l'axe des abscisses tourné à -45°)."""
    abs_x = abs(x)
    if abs_x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    if abs_x >= 1_000:
        return f"{x / 1_000:.1f}k"
    if float(x).is_integer():
        return f"{int(x)}"
    return f"{x:.2f}"


def convert_types(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def build_analysis_prompt(profile: dict, stats: dict, model: str | None = None) -> str:
    """
    Construit le prompt d'analyse à partir du profil de base
    et des statistiques ydata-profiling.

    L'aperçu est borné au budget du modèle choisi (voir `prompt_budget`) : c'est de
    loin le poste le plus lourd du prompt — 83,5 % sur le pire cas du corpus, où
    cinq corps d'articles pèsent 17 836 caractères sans rien apprendre de plus sur
    la structure du fichier.
    """
    from app.services.prompt_budget import bloc_apercu, profil_modele

    overview = stats.get("dataset_overview", {})
    variables = stats.get("variables", {})
    missing = stats.get("missing", {})
    correlations = stats.get("correlations", {})
    
    n_rows = profile.get("rows", 0)

    # Détection des colonnes ID
    id_cols = []
    for col in profile.get("column_names", []):
        col_lower = str(col).lower()
        if col_lower in ["id", "index"] or "id_" in col_lower or "_id" in col_lower:
            id_cols.append(col)
        else:
            col_stats = variables.get(col, {})
            n_distinct = col_stats.get("n_valeurs_distinctes", 0)
            var_type = col_stats.get("type", "")
            if n_rows > 0 and n_distinct == n_rows and var_type == "Numeric":
                id_cols.append(col)

    id_text = ""
    if id_cols:
        id_text = f"\nATTENTION : Les colonnes suivantes sont des identifiants (IDs) : {', '.join(id_cols)}.\nElles ne sont pas des variables statistiques. Ne l'oublie pas dans tes analyses (ne cherche pas de corrélation, de moyenne ou d'interprétation quantitative sur ces colonnes)."

    ambiguous = profile.get("ambiguous_columns", [])
    ambiguous_text = ""
    if ambiguous:
        ambiguous_text = f"\nATTENTION: Les colonnes suivantes ont des noms très ambigus : {', '.join(ambiguous)}.\nTu DOIS essayer de deviner au maximum ce qu'elles représentent en analysant leur contenu, leurs statistiques et les autres colonnes.\nDemande ensuite explicitement à l'utilisateur de clarifier ou de confirmer ton hypothèse dans le chat."

    # Résumé des variables numériques
    numeric_summary = {}
    categorical_summary = {}
    for col, col_stats in variables.items():
        if col_stats.get("type") == "Numeric":
            numeric_summary[col] = {
                k: col_stats[k] for k in [
                    "moyenne", "mediane", "ecart_type", "min", "max",
                    "q1", "q3", "skewness", "kurtosis", "n_manquantes",
                    "n_zeros", "n_valeurs_distinctes"
                ] if k in col_stats
            }
        elif col_stats.get("type") in ("Categorical", "Boolean"):
            categorical_summary[col] = {
                k: col_stats[k] for k in [
                    "n_valeurs_distinctes", "valeur_dominante",
                    "frequence_dominante", "n_manquantes"
                ] if k in col_stats
            }

    return f"""
Tu as reçu un jeu de données avec les caractéristiques suivantes :

PROFIL DU FICHIER :
- Nombre de lignes : {profile['rows']}
- Nombre de colonnes : {profile['columns']}
- Colonnes : {', '.join(profile['column_names'])}
- Doublons détectés : {overview.get('n_doublons', profile.get('duplicates', 0))} ({overview.get('pct_doublons', 0)}%)
- Variables numériques : {overview.get('n_variables_numeriques', 0)}
- Variables catégorielles : {overview.get('n_variables_categorielles', 0)}
- Valeurs manquantes totales : {overview.get('n_valeurs_manquantes_total', 0)} ({overview.get('pct_valeurs_manquantes_total', 0)}%)

STATISTIQUES DESCRIPTIVES DES VARIABLES NUMÉRIQUES :
{json.dumps(numeric_summary, ensure_ascii=False, indent=2)}

STATISTIQUES DES VARIABLES CATÉGORIELLES :
{json.dumps(categorical_summary, ensure_ascii=False, indent=2)}

VALEURS MANQUANTES PAR COLONNE :
{json.dumps(missing, ensure_ascii=False, indent=2) if missing else "Aucune valeur manquante détectée."}

CORRÉLATIONS :
{json.dumps(correlations, ensure_ascii=False, indent=2) if correlations else "Non calculées."}

APERÇU DES DONNÉES (5 premières lignes) :
{bloc_apercu(profile.get('preview'), budget=profil_modele(model).budget_contexte // 3)}

Rédige une analyse en français de manière claire et accessible.
Ne commence JAMAIS l'analyse par des formules d'introduction ou des salutations clichées/répétitives (par exemple : "Bonjour", "En tant qu'expert en analyse de données, voici...", "En tant qu'agent...", "Voici le résultat de..."). Rentre directement dans le sujet.
{id_text}
{ambiguous_text}

Ta réponse doit comporter EXACTEMENT trois sections :

1. RÉSUMÉ
Décris en 3 à 5 phrases ce que contient ce jeu de données, sa nature, sa taille et les premières tendances visibles. Parle à l'utilisateur directement, sans préambule.

2. POINTS CLÉS
Liste 3 à 5 observations statistiques importantes issues des données (valeurs remarquables, distributions, anomalies, corrélations potentielles, asymétrie, aplatissement).

3. PROPOSITIONS
Propose 3 analyses concrètes et spécifiques que tu peux réaliser sur ces données. Formule chaque proposition comme une action directe.
"""


async def analyze_tabular(
    file_bytes: bytes,
    filename: str,
    model: str | None = None,
    with_interpretation: bool = True,
) -> dict:
    """Profil + statistiques d'un fichier tabulaire, et son interprétation LLM.

    `with_interpretation=False` conserve tout le calcul déterministe (profil,
    ydata-profiling) mais saute l'appel au LLM. C'est ce que demandent les
    campagnes d'évaluation, qui posent leurs propres questions et n'ont que
    faire du texte d'accueil : ce dernier coûte un appel par fichier sans entrer
    dans le contexte que `/api/chat` exploite (`get_data_context` ne lit que le
    profil et les stats).
    """
    from app.services.ingestion_service import load_tabular
    import pandas as pd

    model = model or config.get_default_model()
    result = await asyncio.to_thread(load_tabular, file_bytes, filename)
    if result["status"] == "error":
        return result

    profile = result["profile"]

    ext = filename.split(".")[-1].lower()
    if ext == "csv":
        df = await asyncio.to_thread(pd.read_csv, pd.io.common.BytesIO(file_bytes))
    else:
        df = await asyncio.to_thread(pd.read_excel, pd.io.common.BytesIO(file_bytes))

    # Utilisation de ydata-profiling pour les statistiques descriptives
    stats = await asyncio.to_thread(generate_profiling_stats, df)
    if with_interpretation:
        prompt = build_analysis_prompt(profile, stats, model=model)
        interpretation = await asyncio.to_thread(ask_gemini, prompt, model=model)
    else:
        interpretation = ""

    from app.services.session_service import save_initial_analysis
    return {
        "status": "ok",
        "profile": profile,
        "stats": stats,
        "interpretation": interpretation
    }

# Cache des interprétations générées, clé = (session_id, dataset_id, variable).
# Évite de rappeler le LLM à chaque fois qu'on revient sur une même variable.
_variable_interpretation_cache: dict[tuple[str, str, str], str] = {}


def _build_variable_interpretation_prompt(var_name: str, var_stats: dict, overview: dict) -> str:
    """Construit le prompt d'interprétation d'UNE variable pour le dashboard."""
    n_rows = overview.get("n_lignes") or overview.get("n_rows") or "?"
    return f"""Tu es un analyste de données. Rédige une interprétation claire et accessible, en français, de la distribution de la variable ci-dessous. Cette interprétation accompagne le graphique de la variable dans un tableau de bord.

Variable analysée : « {var_name} »
Nombre total de lignes du jeu de données : {n_rows}

Statistiques disponibles pour cette variable :
{json.dumps(var_stats, ensure_ascii=False, indent=2)}

Consignes STRICTES :
- 2 à 4 phrases courtes maximum. Va droit au but, AUCUNE formule d'introduction ("Voici", "Cette variable...", "En tant que...").
- Mets en avant ce qui est réellement notable selon le type : tendance centrale et dispersion, asymétrie (skewness), valeurs extrêmes, catégorie dominante et déséquilibre, valeurs manquantes.
- Si une valeur manquante est élevée (>10%) ou un déséquilibre marqué existe, signale-le.
- Termine par une courte implication analytique concrète si pertinent (ex: "à normaliser avant modélisation", "catégorie sur-représentée à surveiller").
- N'invente aucun chiffre : appuie-toi uniquement sur les statistiques fournies.
- Arrondis toute valeur décimale à deux chiffres maximum après la virgule.
"""


async def interpret_variable(
    session_id: str,
    variable: str,
    dataset_id: str | None = None,
    model: str | None = None,
) -> dict:
    """Génère (ou renvoie depuis le cache) une interprétation textuelle d'une
    variable pour le dashboard. Le résultat change donc avec la variable
    sélectionnée côté frontend."""
    from app.services.session_service import get_dataset, list_datasets
    from app.services.gemini_service import complete_text

    model = model or config.get_default_model()

    available = list_datasets(session_id)
    if not available:
        return {"error": "Session ou jeu de données introuvable."}

    known_ids = {item["id"] for item in available}
    if dataset_id not in known_ids:
        dataset_id = available[0]["id"]

    cache_key = (session_id, dataset_id, variable)
    if cache_key in _variable_interpretation_cache:
        return {"variable": variable, "interpretation": _variable_interpretation_cache[cache_key], "cached": True}

    _, _, _, stats = get_dataset(session_id, dataset_id)
    stats = stats or {}
    variables = stats.get("variables", {})
    overview = stats.get("dataset_overview", {})

    var_stats = variables.get(variable)
    if var_stats is None:
        return {"error": f"Variable « {variable} » introuvable dans ce jeu de données."}

    prompt = _build_variable_interpretation_prompt(variable, var_stats, overview)
    try:
        interpretation = (await asyncio.to_thread(complete_text, prompt, model)).strip()
    except Exception as exc:
        return {"error": f"Impossible de générer l'interprétation : {exc}"}

    _variable_interpretation_cache[cache_key] = interpretation
    return {"variable": variable, "interpretation": interpretation, "cached": False}


async def answer_dashboard_question(
    session_id: str,
    variable: str,
    question: str,
    dataset_id: str | None = None,
    model: str | None = None,
) -> dict:
    """Répond à une question en restant strictement dans le contexte du graphique."""
    from app.services.session_service import get_dataset, list_datasets
    from app.services.gemini_service import complete_text

    question = question.strip()
    if not question:
        return {"error": "La question ne peut pas être vide."}
    if len(question) > 1000:
        return {"error": "La question est trop longue (1 000 caractères maximum)."}

    available = list_datasets(session_id)
    if not available:
        return {"error": "Session ou jeu de données introuvable."}

    known_ids = {item["id"] for item in available}
    if dataset_id not in known_ids:
        dataset_id = available[0]["id"]

    _, _, _, stats = get_dataset(session_id, dataset_id)
    stats = stats or {}
    variables = stats.get("variables", {})
    var_stats = variables.get(variable)
    if var_stats is None:
        return {"error": f"Variable « {variable} » introuvable dans ce jeu de données."}

    overview = stats.get("dataset_overview", {})
    interpretation_result = await interpret_variable(
        session_id, variable, dataset_id=dataset_id, model=model
    )
    interpretation = interpretation_result.get("interpretation", "")
    prompt = f"""Tu es un analyste de données. Réponds en français à la question de l'utilisateur au sujet du graphique affiché dans son dashboard.

Variable représentée : « {variable} »
Nombre total de lignes : {overview.get("n_lignes") or overview.get("n_rows") or "?"}
Statistiques qui ont servi à construire le graphique :
{json.dumps(var_stats, ensure_ascii=False, indent=2)}

Interprétation déjà affichée :
{interpretation or "Aucune interprétation disponible."}

Question : {question}

Consignes STRICTES :
- Réponds directement et clairement en 2 à 5 phrases.
- Appuie-toi uniquement sur les informations fournies ci-dessus et n'invente aucun chiffre.
- Si le graphique et les statistiques ne permettent pas de répondre, dis-le explicitement et indique brièvement quelle donnée serait nécessaire.
- Ne prétends pas voir d'autres variables ou éléments du jeu de données.
- Arrondis toute valeur décimale à deux chiffres maximum après la virgule.
"""
    try:
        answer = (await asyncio.to_thread(
            complete_text, prompt, model or config.get_default_model()
        )).strip()
    except Exception as exc:
        return {"error": f"Impossible de répondre à la question : {exc}"}

    return {"variable": variable, "question": question, "answer": answer}


async def get_dashboard_data(session_id: str, dataset_id: str | None = None) -> dict:
    import pandas as pd
    import io
    from app.services.session_service import get_session, list_datasets, get_dataset

    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    # Une session peut porter plusieurs jeux de données (fichier principal,
    # tableau extrait d'un PDF, fichiers ajoutés ensuite) : on charge celui
    # demandé, ou le premier disponible par défaut.
    available_datasets = list_datasets(session_id)
    if not available_datasets:
        return {"error": "File not found"}

    known_ids = {item["id"] for item in available_datasets}
    if dataset_id not in known_ids:
        dataset_id = available_datasets[0]["id"]

    file_bytes, filename, dataset_profile, dataset_stats = get_dataset(session_id, dataset_id)
    if not file_bytes:
        return {"error": "File not found"}

    stats = dataset_stats or {}
    embedded_preview = dataset_profile.get("preview") if dataset_profile else None

    ext = filename.split(".")[-1].lower()
    if ext == "csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    # L'aperçu doit correspondre au dataset affiché, pas systématiquement à
    # celui de la session : on ne retombe sur `data_preview` que pour le
    # fichier principal. Seul l'aperçu est neutralisé pour JSON — `df` conserve
    # ses dtypes, dont dépend tout le choix des graphiques ci-dessous.
    from app.services.session_service import MAIN_DATASET_ID
    preview = embedded_preview or (
        session.get("data_preview") if dataset_id == MAIN_DATASET_ID else None
    ) or _preview_records(df)
    overview = stats.get("dataset_overview", {})
    variables = stats.get("variables", {})
    
    n_rows = len(df)

    # 1. Colonne temporelle servant d'axe. On n'en retient une que si elle se
    #    parse réellement en dates et couvre plusieurs instants distincts : une
    #    colonne constante ou quasi vide ne fait pas un axe temporel.
    time_col = None
    for col in df.columns:
        parsed = None
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            parsed = df[col]
        elif re.search(r"date|mois|month|year|annee|time|timestamp|jour", str(col), re.I):
            try:
                parsed = pd.to_datetime(df[col], errors="coerce")
            except Exception:
                parsed = None
        if parsed is not None and parsed.notna().sum() >= max(3, 0.5 * n_rows) and parsed.nunique() >= 3:
            df[col] = parsed
            time_col = col
            break

    # 2. Colonnes identifiantes : par le nom, ou parce que leurs valeurs sont
    #    quasi toutes distinctes (quel que soit le type, pas seulement numérique).
    id_cols = set()
    for col in df.columns:
        series = _drop_missing(df[col])
        if series.empty:
            id_cols.add(col)
            continue
        if str(col).lower() in ("id", "index") or IDENTIFIER_NAME_PATTERN.search(str(col)):
            id_cols.add(col)
        elif n_rows > 20 and series.nunique() / len(series) > 0.95 and not pd.api.types.is_float_dtype(series):
            # Presque autant de valeurs que de lignes : un graphique n'apprend rien.
            id_cols.add(col)

    distributions = {}

    for col in df.columns:
        if col == time_col or col in id_cols:
            continue

        # Les manquants sont écartés une fois pour toutes : ils ne comptent ni
        # dans la cardinalité, ni dans les classes, ni dans les catégories. Leur
        # volume est reporté à part sur chaque distribution.
        series = _drop_missing(df[col])
        if series.empty:
            continue

        n_missing = n_rows - int(series.size)
        missing_meta = {
            "n_missing": n_missing,
            "pct_missing": round(100 * n_missing / n_rows, 2) if n_rows else 0.0,
        }

        n_distinct = series.nunique()
        col_type = variables.get(col, {}).get("type", "Unknown")
        is_numeric = pd.api.types.is_numeric_dtype(df[col])
        is_datetime = pd.api.types.is_datetime64_any_dtype(df[col])

        # ── Numériques ────────────────────────────────────────────────────
        if is_numeric and not is_datetime:
            # Série temporelle : uniquement si un axe temporel existe et que la
            # variable est continue. Les valeurs sont TOUJOURS agrégées par
            # période, sinon plusieurs points partageant une même date font
            # zigzaguer la courbe sans signification.
            if time_col is not None and n_distinct > MAX_DISCRETE_VALUES:
                built = _build_time_series(df[[time_col, col]], time_col, col, how="mean")
                if built is not None:
                    distributions[col] = {"type": "timeseries", "chart": "line", **missing_meta, **built}
                    continue

            if n_distinct <= MAX_DISCRETE_VALUES:
                # Numérique discrète (note, indicateur 0/1, effectif…) : des
                # classes fractionnaires n'auraient aucun sens.
                counts = series.value_counts().sort_index()
                distributions[col] = {
                    "type": "categorical",
                    "chart": "donut" if n_distinct <= MAX_DONUT_SLICES else "bar",
                    **missing_meta,
                    "data": [{"name": _discrete_label(k), "value": int(v)} for k, v in counts.items()],
                }
            else:
                distributions[col] = {
                    "type": "numeric",
                    "chart": "histogram",
                    **missing_meta,
                    "data": _build_histogram(series),
                }

        # ── Dates (hors axe principal) ────────────────────────────────────
        elif is_datetime:
            # Nombre d'enregistrements par période, avec le même choix de
            # granularité que les autres séries temporelles.
            frame = pd.DataFrame({col: series, "_count": 1})
            built = _build_time_series(frame, col, "_count", how="count")
            if built is not None:
                distributions[col] = {"type": "datetime", "chart": "line", **missing_meta, **built}

        # ── Catégorielles / booléennes / texte ────────────────────────────
        else:
            data = _category_counts(series)
            if n_distinct <= MAX_DONUT_SLICES:
                chart = "donut"          # proportions d'un tout, lisible
            elif len(data) <= MAX_BAR_CATEGORIES:
                chart = "hbar"           # barres horizontales : libellés lisibles
            else:
                chart = "hbar"
            distributions[col] = {
                "type": "categorical",
                "chart": chart,
                **missing_meta,
                "data": data,
            }

    return {
        "filename": filename,
        "overview": overview,
        "preview": preview,
        "variables": variables,
        "distributions": distributions,
        "datasets": available_datasets,
        "dataset_id": dataset_id,
    }
