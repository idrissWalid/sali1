import pandas as pd
import numpy as np
import json
from app.services.gemini_service import ask_gemini
from app.services.profiling_service import generate_profiling_stats

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


async def analyze_tabular(file_bytes: bytes, filename: str) -> dict:
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
    interpretation = ask_gemini(prompt)

    from app.services.session_service import save_initial_analysis
    return {
        "status": "ok",
        "profile": profile,
        "stats": stats,
        "interpretation": interpretation
    }

async def get_dashboard_data(session_id: str) -> dict:
    import pandas as pd
    import numpy as np
    import io
    from app.services.session_service import get_session, get_file_bytes
    
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found"}
        
    file_bytes, filename = get_file_bytes(session_id)
    if not file_bytes:
        return {"error": "File not found"}
        
    ext = filename.split(".")[-1].lower()
    if ext == "csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))
        
    # Replace NaN with None for JSON serialization
    df = df.replace({np.nan: None})
    
    preview = session.get("data_preview", df.head(5).to_dict(orient="records"))
    stats = session.get("data_stats", {})
    overview = stats.get("dataset_overview", {})
    variables = stats.get("variables", {})
    
    # 1. Identification de la colonne temporelle
    time_col = None
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            time_col = col
            break
        if col.lower() in ["date", "month", "year", "time", "timestamp"]:
            try:
                # Attempt to parse
                parsed = pd.to_datetime(df[col])
                # If parsed successfully without all being NaT
                if not parsed.isna().all():
                    df[col] = parsed
                    time_col = col
                    break
            except:
                pass
                
    # 2. Identification des colonnes ID
    id_cols = []
    for col in df.columns:
        if col.lower() in ["id", "index"] or "id_" in col.lower() or "_id" in col.lower():
            id_cols.append(col)
        elif df[col].nunique() == len(df) and pd.api.types.is_numeric_dtype(df[col]):
            id_cols.append(col)
            
    distributions = {}
    
    for col in df.columns:
        # Ignorer l'index temporel et les IDs de la liste des variables à analyser
        if col == time_col or col in id_cols:
            continue
            
        col_type = variables.get(col, {}).get("type", "Unknown")
        
        # Categorical, Boolean or text variables
        if col_type in ("Categorical", "Boolean") or df[col].dtype == 'object':
            # Get top 10 value counts
            value_counts = df[col].value_counts().head(10).to_dict()
            distributions[col] = {
                "type": "categorical",
                "data": [{"name": str(k), "value": int(v)} for k, v in value_counts.items()]
            }
        # Numeric variables
        elif pd.api.types.is_numeric_dtype(df[col]):
            if time_col is not None:
                # Timeseries chart: grouper par time_col
                df_clean = df.dropna(subset=[col, time_col]).copy()
                if not df_clean.empty:
                    df_clean = df_clean.sort_values(by=time_col)
                    if len(df_clean) > 500:
                        # Group by month
                        grouped = df_clean.groupby(df_clean[time_col].dt.to_period("M"))[col].mean()
                        line_data = [{"name": str(k), "value": float(v)} for k, v in grouped.items()]
                    else:
                        # Convert date to string (format YYYY-MM-DD or YYYY-MM)
                        line_data = []
                        for _, row in df_clean.iterrows():
                            val = row[time_col]
                            name = str(val.date()) if hasattr(val, 'date') else str(val)
                            line_data.append({"name": name, "value": float(row[col])})
                            
                    distributions[col] = {
                        "type": "timeseries",
                        "data": line_data
                    }
                else:
                    distributions[col] = {"type": "timeseries", "data": []}
            else:
                # Histogram (10 bins)
                df_col_clean = df[col].dropna()
                if not df_col_clean.empty:
                    counts, bin_edges = np.histogram(df_col_clean, bins=10)
                    hist_data = []
                    for i in range(len(counts)):
                        bin_name = f"{format_axis_number(bin_edges[i])} - {format_axis_number(bin_edges[i+1])}"
                        hist_data.append({"name": bin_name, "value": int(counts[i])})
                    distributions[col] = {
                        "type": "numeric",
                        "data": hist_data
                    }
                else:
                    distributions[col] = {"type": "numeric", "data": []}
        # Datetime variables (if not chosen as time_col)
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            df_col_clean = df[col].dropna()
            if not df_col_clean.empty:
                counts = df_col_clean.dt.to_period("M").value_counts().sort_index()
                line_data = [{"name": str(k), "value": int(v)} for k, v in counts.items()]
                distributions[col] = {
                    "type": "datetime",
                    "data": line_data
                }
            else:
                distributions[col] = {
                    "type": "datetime",
                    "data": []
                }
                
    return {
        "filename": filename,
        "overview": overview,
        "preview": preview,
        "variables": variables,
        "distributions": distributions
    }