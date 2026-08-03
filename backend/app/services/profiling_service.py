"""
Service de profilage de données basé sur ydata-profiling.
Génère des statistiques descriptives complètes pour les fichiers tabulaires.
"""
import pandas as pd
import numpy as np
import json
import re
import unicodedata
import warnings
from ydata_profiling import ProfileReport


# ── Rôle des colonnes ────────────────────────────────────────────────────────
# Sans cette distinction, un numéro d'ordre et un patronyme reçoivent le même
# traitement qu'une note ou un montant : moyenne, écart-type, asymétrie,
# corrélations. Ces chiffres ne veulent rien dire — la moyenne d'un compteur de
# lignes vaut la moitié du nombre de lignes, et rien d'autre — mais ils
# encombrent le dashboard et le modèle les interprète comme des résultats.

ROLE_IDENTIFIANT_LIGNE = "identifiant_ligne"
ROLE_NOMINATIF = "nominatif"
ROLE_IDENTIFIANT = "identifiant"
ROLE_ANALYSABLE = "analysable"

# Jetons comparés au nom de colonne découpé, jamais en sous-chaîne : « nom »
# cherché dans « nombre » classerait une vraie variable comme patronyme.
_JETONS_NOMINATIFS = {
    "nom", "noms", "prenom", "prenoms", "patronyme", "patronymes",
    "name", "names", "firstname", "lastname", "surname", "civilite",
}
_JETONS_IDENTIFIANT_LIGNE = {"n", "no", "num", "numero", "ordre", "rang", "index", "id"}
_JETONS_IDENTIFIANT = {"id", "code", "matricule", "reference", "ref", "cin", "immatriculation"}

# Statistiques conservées pour une colonne non analysable : de quoi repérer un
# trou dans la numérotation ou un doublon de nom, sans les moments statistiques.
_STATS_HORS_ANALYSE = {
    "type", "role", "n_valeurs_distinctes", "pct_valeurs_distinctes",
    "n_manquantes", "pct_manquantes", "min", "max",
}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", str(texte).strip().lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _jetons(nom: str) -> set:
    """Nom de colonne découpé en mots, ponctuation et accents retirés."""
    return {jeton for jeton in re.split(r"[^a-z0-9]+", _sans_accents(nom)) if jeton}


def _est_suite_de_numerotation(serie: pd.Series) -> bool:
    """La colonne est-elle un simple compteur de lignes ?

    Exigé en plus du nom : « Numéro de téléphone » contient bien « numero » mais
    ses valeurs ne forment aucune suite, et c'est une vraie variable.
    """
    valeurs = pd.to_numeric(serie, errors="coerce").dropna()
    if len(valeurs) < 3 or len(valeurs) < len(serie) * 0.9:
        return False
    if (valeurs % 1 != 0).any() or valeurs.duplicated().any():
        return False
    ordonnees = np.sort(valeurs.to_numpy())
    etendue = ordonnees[-1] - ordonnees[0] + 1
    # Quasi continue : quelques trous restent normaux (lignes retirées du
    # document d'origine, numérotation qui reprend d'une section à l'autre).
    return etendue > 0 and len(ordonnees) / etendue >= 0.8


def _valeurs_de_type_identifiant(serie: pd.Series) -> bool:
    """Valeurs courtes et sans espace — un code, pas une phrase.

    Garde-fou contre une colonne de texte libre (« Observations ») dont chaque
    valeur serait unique : elle n'a pas de distribution à montrer, mais la
    ranger parmi les identifiants induirait en erreur.
    """
    textes = serie.dropna().astype(str)
    if textes.empty:
        return False
    return bool((textes.str.len() <= 24).mean() >= 0.9
                and (~textes.str.contains(r"\s")).mean() >= 0.9)


def _ressemble_a_des_dates(serie: pd.Series) -> bool:
    """La colonne contient-elle des dates ?

    Une date de naissance réunit tous les signaux du faux positif : valeurs
    toutes distinctes, format court, sans espace. C'est pourtant une variable à
    part entière — c'est d'elle que se déduit la répartition des âges. Sans ce
    garde-fou elle était rangée parmi les identifiants et disparaissait du
    dashboard.
    """
    textes = serie.dropna().astype(str)
    if textes.empty:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converties = pd.to_datetime(textes, errors="coerce", dayfirst=True)
    return bool(converties.notna().mean() >= 0.9)


def detecter_role(nom: str, serie: pd.Series) -> str:
    """Rôle d'une colonne : variable d'analyse, ou simple étiquette de ligne.

    Le classement est volontairement prudent : écarter à tort une vraie variable
    la ferait disparaître du dashboard, ce qui est bien plus grave que laisser
    passer un identifiant.
    """
    jetons = _jetons(nom)

    if jetons & _JETONS_NOMINATIFS:
        return ROLE_NOMINATIF
    if jetons & _JETONS_IDENTIFIANT_LIGNE and _est_suite_de_numerotation(serie):
        return ROLE_IDENTIFIANT_LIGNE

    non_vides = serie.dropna()
    if len(non_vides) < 5 or non_vides.nunique() != len(non_vides):
        return ROLE_ANALYSABLE

    # À partir d'ici, toutes les valeurs sont distinctes.
    if pd.api.types.is_numeric_dtype(non_vides):
        # Sur du numérique, l'unicité ne prouve rien : un montant, une durée ou
        # un salaire n'ont aucune raison d'avoir des ex æquo. Les ranger parmi
        # les identifiants les ferait disparaître du dashboard alors que ce sont
        # les variables les plus intéressantes. On n'écarte donc que ce qui est
        # démontrablement un compteur, ou nommé comme un identifiant.
        if _est_suite_de_numerotation(serie):
            return ROLE_IDENTIFIANT_LIGNE
        return ROLE_IDENTIFIANT if jetons & _JETONS_IDENTIFIANT else ROLE_ANALYSABLE

    # Sur du texte en revanche, des valeurs toutes distinctes n'ont pas de
    # distribution à tracer — à condition qu'elles ressemblent à des codes, et
    # non à des phrases (voir `_valeurs_de_type_identifiant`) ni à des dates.
    if _ressemble_a_des_dates(non_vides):
        return ROLE_ANALYSABLE
    if jetons & _JETONS_IDENTIFIANT or _valeurs_de_type_identifiant(serie):
        return ROLE_IDENTIFIANT
    return ROLE_ANALYSABLE


def detecter_roles(df: pd.DataFrame) -> dict:
    return {str(colonne): detecter_role(colonne, df[colonne]) for colonne in df.columns}


# Au-delà, une colonne de texte n'est plus une nomenclature mais du texte libre :
# sa « valeur dominante » n'apprendrait rien.
_MAX_MODALITES_CATEGORIELLES = 30


def _est_categorielle(var_type: str, n_distinct: int, n_lignes: int) -> bool:
    """La colonne se comporte-t-elle comme une variable catégorielle ?

    `ydata-profiling` en mode `minimal` ne produit JAMAIS le type
    « Categorical » : toute colonne de texte ressort en « Text », sans valeur
    dominante ni fréquence. La branche catégorielle du profilage était donc
    morte, le compteur « variables catégorielles » du dashboard affichait 0, et
    le modèle recevait un motif ou une année dépourvus de toute statistique —
    d'où son incapacité à en dire quoi que ce soit. On retrouve la nature réelle
    à partir de la cardinalité.
    """
    if var_type in ("Categorical", "Boolean"):
        return True
    if var_type != "Text" or n_lignes <= 0 or n_distinct <= 0:
        return False
    return n_distinct <= min(_MAX_MODALITES_CATEGORIELLES, max(2, n_lignes // 2))


def _safe_convert(obj):
    """Convertit les types numpy en types Python natifs pour la sérialisation JSON."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _clean_dict(d: dict) -> dict:
    """Nettoie récursivement un dict pour la sérialisation JSON."""
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, dict):
            cleaned[k] = _clean_dict(v)
        elif isinstance(v, list):
            cleaned[k] = [_safe_convert(item) if not isinstance(item, dict) else _clean_dict(item) for item in v]
        else:
            cleaned[k] = _safe_convert(v)
    return cleaned


def generate_profiling_stats(df: pd.DataFrame) -> dict:
    """
    Génère les statistiques descriptives complètes via ydata-profiling.
    
    Retourne un dict structuré avec :
    - dataset_overview : infos globales (nb lignes, colonnes, doublons, valeurs manquantes)
    - variables : stats détaillées par colonne (type, distribution, outliers, etc.)
    - correlations : matrice de corrélation (Pearson) pour les colonnes numériques
    - missing : analyse des valeurs manquantes
    """
    # Génération du rapport ydata-profiling (mode minimal pour la performance)
    profile = ProfileReport(
        df,
        title="Profiling Report",
        minimal=True,          # Mode rapide, adapté aux gros fichiers
        explorative=False,
        progress_bar=False,
    )

    # Extraction du JSON complet
    report_json = json.loads(profile.to_json())

    # ── 1. Vue d'ensemble du dataset ──────────────────────────────
    table_info = report_json.get("table", {})
    n_lignes = table_info.get("n", 0) or len(df)
    dataset_overview = {
        "n_lignes": table_info.get("n", 0),
        "n_colonnes": table_info.get("n_var", 0),
        "n_doublons": table_info.get("n_duplicates", 0),
        "pct_doublons": round(table_info.get("p_duplicates", 0) * 100, 2),
        "n_valeurs_manquantes_total": table_info.get("n_cells_missing", 0),
        "pct_valeurs_manquantes_total": round(table_info.get("p_cells_missing", 0) * 100, 2),
        "n_variables_numeriques": table_info.get("types", {}).get("Numeric", 0),
        "n_variables_categorielles": table_info.get("types", {}).get("Categorical", 0),
        "n_variables_booleennes": table_info.get("types", {}).get("Boolean", 0),
        "taille_memoire": table_info.get("memory_size", 0),
    }

    # ── 2. Stats par variable ─────────────────────────────────────
    variables = {}
    raw_variables = report_json.get("variables", {})
    roles = detecter_roles(df)

    for col_name, col_data in raw_variables.items():
        var_type = col_data.get("type", "Unknown")
        role = roles.get(str(col_name), ROLE_ANALYSABLE)
        var_stats = {
            "type": var_type,
            "role": role,
            "n_valeurs_distinctes": col_data.get("n_distinct", 0),
            "pct_valeurs_distinctes": round(col_data.get("p_distinct", 0) * 100, 2),
            "n_manquantes": col_data.get("n_missing", 0),
            "pct_manquantes": round(col_data.get("p_missing", 0) * 100, 2),
        }

        # Stats numériques
        if var_type in ("Numeric",):
            var_stats.update({
                "moyenne": _safe_convert(col_data.get("mean")),
                "ecart_type": _safe_convert(col_data.get("std")),
                "variance": _safe_convert(col_data.get("variance")),
                "min": _safe_convert(col_data.get("min")),
                "max": _safe_convert(col_data.get("max")),
                "mediane": _safe_convert(col_data.get("median")),
                "q1": _safe_convert(col_data.get("25%")),
                "q3": _safe_convert(col_data.get("75%")),
                "iqr": _safe_convert(col_data.get("iqr")),
                "skewness": _safe_convert(col_data.get("skewness")),
                "kurtosis": _safe_convert(col_data.get("kurtosis")),
                "coefficient_variation": _safe_convert(col_data.get("cv")),
                "somme": _safe_convert(col_data.get("sum")),
                "n_zeros": col_data.get("n_zeros", 0),
            })

        # Stats catégorielles
        elif _est_categorielle(var_type, col_data.get("n_distinct", 0), n_lignes):
            dominante = col_data.get("top")
            frequence = col_data.get("freq")
            # `minimal=True` ne renseigne ni `top` ni `freq` sur une colonne
            # typée « Text » : on les recalcule, c'est une passe sur une seule
            # colonne.
            if dominante is None and col_name in df.columns:
                comptes = df[col_name].dropna().astype(str).value_counts()
                if not comptes.empty:
                    dominante, frequence = comptes.index[0], int(comptes.iloc[0])
            var_stats.update({
                # Nature réelle plutôt que le « Text » de ydata : c'est ce que
                # lisent le badge du dashboard et le modèle.
                "type": "Categorical",
                "valeur_dominante": str(dominante if dominante is not None else ""),
                "frequence_dominante": frequence or 0,
            })

        # Une colonne qui n'est pas une variable d'analyse ne garde que de quoi
        # la contrôler (trou dans la numérotation, doublon, valeur manquante).
        # Le reste — moyenne d'un compteur, valeur dominante d'un patronyme —
        # serait lu comme un résultat par le modèle comme par l'utilisateur.
        if role != ROLE_ANALYSABLE:
            var_stats = {k: v for k, v in var_stats.items() if k in _STATS_HORS_ANALYSE}

        variables[col_name] = var_stats

    # Comptes recalculés sur les types corrigés ci-dessus : ceux de ydata
    # annonçaient systématiquement 0 variable catégorielle, puisque le mode
    # minimal ne produit que « Numeric » et « Text ».
    dataset_overview["n_variables_numeriques"] = sum(
        1 for v in variables.values() if v.get("type") == "Numeric")
    dataset_overview["n_variables_categorielles"] = sum(
        1 for v in variables.values() if v.get("type") == "Categorical")

    # ── 3. Corrélations ───────────────────────────────────────────
    correlations = {}
    raw_correlations = report_json.get("correlations", {})
    analysables = {nom for nom, role in roles.items() if role == ROLE_ANALYSABLE}

    def sans_identifiants(matrice: dict) -> dict:
        """Matrice restreinte aux variables d'analyse.

        Un compteur de lignes corrèle mécaniquement avec tout ce qui suit
        l'ordre du document : la corrélation est réelle, son interprétation
        n'existe pas. La laisser, c'est inviter le modèle à y voir un résultat.
        """
        return {
            ligne: {col: valeur for col, valeur in valeurs.items() if col in analysables}
            for ligne, valeurs in matrice.items()
            if ligne in analysables and isinstance(valeurs, dict)
        }

    # Extraire la matrice de Pearson si disponible
    for corr_type in ("pearson", "spearman", "auto"):
        if corr_type in raw_correlations:
            corr_data = raw_correlations[corr_type]
            if isinstance(corr_data, dict):
                correlations[corr_type] = _clean_dict(sans_identifiants(corr_data))
            break

    # ── 4. Analyse des valeurs manquantes ─────────────────────────
    missing = {}
    for col_name, col_data in raw_variables.items():
        n_missing = col_data.get("n_missing", 0)
        if n_missing > 0:
            missing[col_name] = {
                "n_manquantes": n_missing,
                "pct_manquantes": round(col_data.get("p_missing", 0) * 100, 2),
            }

    return {
        "dataset_overview": dataset_overview,
        "variables": _clean_dict(variables),
        "correlations": correlations,
        "missing": _clean_dict(missing),
    }


def generate_profiling_html(df: pd.DataFrame) -> str:
    """
    Génère le rapport HTML complet de ydata-profiling.
    Utile si on veut l'afficher directement dans le frontend.
    """
    profile = ProfileReport(
        df,
        title="Rapport de Profilage",
        minimal=True,
        explorative=False,
        progress_bar=False,
    )
    return profile.to_html()
