import pandas as pd
import numpy as np
import json
import math
import re
from app.services.gemini_service import ask_gemini
from app.services.profiling_service import generate_profiling_stats

# ── Choix des graphiques du dashboard ────────────────────────────────────────
# Le type de graphique est déduit des propriétés mesurées de chaque colonne
# (cardinalité, continuité, lien réel au temps) et non de son seul dtype : c'est
# ce qui évite les camemberts à dix parts ou les « séries temporelles » tracées
# sur des variables qui n'ont aucun rapport avec le temps.

MAX_DISCRETE_VALUES = 12     # au-delà, une numérique est traitée comme continue
MAX_DONUT_SLICES = 5         # un anneau reste lisible jusqu'à ~5 parts
MAX_BAR_CATEGORIES = 25      # au-delà, on agrège la traîne dans « Autres »
TOP_CATEGORIES = 15
IDENTIFIER_NAME_PATTERN = re.compile(r"(^|_)(id|uuid|guid|code|ref|reference|email|mail|url|slug)($|_)", re.I)


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
    decimals = 0 if step >= 1 else min(6, int(abs(math.floor(math.log10(step)))) + 1)
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
    """Effectifs par catégorie, la traîne étant regroupée dans « Autres »."""
    counts = series.astype(str).value_counts()
    if len(counts) > MAX_BAR_CATEGORIES:
        head = counts.head(TOP_CATEGORIES)
        data = [{"name": str(k), "value": int(v)} for k, v in head.items()]
        data.append({"name": "Autres", "value": int(counts.iloc[TOP_CATEGORIES:].sum())})
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


def build_analysis_prompt(profile: dict, stats: dict) -> str:
    """
    Construit le prompt d'analyse à partir du profil de base
    et des statistiques ydata-profiling.
    """
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
{json.dumps(profile['preview'], ensure_ascii=False, indent=2)}

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


async def analyze_tabular(file_bytes: bytes, filename: str, model: str = "gemini-3.1-flash-lite-preview") -> dict:
    from app.services.ingestion_service import load_tabular
    import pandas as pd

    result = load_tabular(file_bytes, filename)
    if result["status"] == "error":
        return result

    profile = result["profile"]

    ext = filename.split(".")[-1].lower()
    if ext == "csv":
        df = pd.read_csv(pd.io.common.BytesIO(file_bytes))
    else:
        df = pd.read_excel(pd.io.common.BytesIO(file_bytes))

    # Utilisation de ydata-profiling pour les statistiques descriptives
    stats = generate_profiling_stats(df)
    prompt = build_analysis_prompt(profile, stats)
    interpretation = ask_gemini(prompt, model=model)

    from app.services.session_service import save_initial_analysis
    return {
        "status": "ok",
        "profile": profile,
        "stats": stats,
        "interpretation": interpretation
    }

async def get_dashboard_data(session_id: str, dataset_id: str | None = None) -> dict:
    import pandas as pd
    import numpy as np
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

    # Replace NaN with None for JSON serialization
    df = df.replace({np.nan: None})

    # L'aperçu doit correspondre au dataset affiché, pas systématiquement à
    # celui de la session : on ne retombe sur `data_preview` que pour le
    # fichier principal.
    from app.services.session_service import MAIN_DATASET_ID
    preview = embedded_preview or (
        session.get("data_preview") if dataset_id == MAIN_DATASET_ID else None
    ) or df.head(5).to_dict(orient="records")
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
        series = df[col].dropna()
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

        series = df[col].dropna()
        if series.empty:
            continue

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
                    distributions[col] = {"type": "timeseries", "chart": "line", **built}
                    continue

            if n_distinct <= MAX_DISCRETE_VALUES:
                # Numérique discrète (note, indicateur 0/1, effectif…) : des
                # classes fractionnaires n'auraient aucun sens.
                counts = series.value_counts().sort_index()
                distributions[col] = {
                    "type": "categorical",
                    "chart": "donut" if n_distinct <= MAX_DONUT_SLICES else "bar",
                    "data": [{"name": str(k), "value": int(v)} for k, v in counts.items()],
                }
            else:
                distributions[col] = {
                    "type": "numeric",
                    "chart": "histogram",
                    "data": _build_histogram(series),
                }

        # ── Dates (hors axe principal) ────────────────────────────────────
        elif is_datetime:
            # Nombre d'enregistrements par période, avec le même choix de
            # granularité que les autres séries temporelles.
            frame = pd.DataFrame({col: series, "_count": 1})
            built = _build_time_series(frame, col, "_count", how="count")
            if built is not None:
                distributions[col] = {"type": "datetime", "chart": "line", **built}

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