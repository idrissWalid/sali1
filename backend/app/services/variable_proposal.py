"""variable_proposal.py — Le LLM propose les colonnes à modéliser, l'utilisateur tranche.

Jusqu'ici, la modale d'entraînement présélectionnait `candidates[0]`, c'est-à-dire
la première colonne dans l'ordre du fichier : sur un CSV qui commence par `id`, la
cible proposée était `id`. Le LLM n'intervenait que dans un seul cas — le supervisé
lancé depuis le chat — et sans jamais demander confirmation.

Ce module comble les deux trous à la fois : une proposition argumentée pour les
trois familles (régression, classification, séries temporelles), rendue à
l'interface comme *présélection* et non comme décision.

Règle qui vaut pour les deux familles : **la réponse du modèle est contrainte à la
liste des candidates**. Une colonne inventée, ou écartée par les heuristiques, est
refusée — sinon l'interface présélectionnerait une valeur que son propre sélecteur
ne propose pas, et l'entraînement échouerait plus loin sur un nom inconnu.
"""

import json
import logging

from app.core import config

logger = logging.getLogger("app.variables")

# Au-delà, une colonne numérique est traitée comme continue (régression) plutôt
# que comme un ensemble de classes. Même seuil que l'endpoint historique.
MAX_MODALITES_CLASSIFICATION = 20


def cibles_supervisees(df) -> list[dict]:
    """Colonnes utilisables comme cible, avec la famille qui en découlerait.

    Source unique de vérité : l'endpoint `supervised-candidates` et la
    proposition du LLM doivent s'accorder sur ce qui compte comme une cible.
    """
    import pandas as pd

    from app.services.supervised_specs import SEUIL_DESEQUILIBRE

    cibles = []
    for col in df.columns:
        serie = df[col].dropna()
        if serie.empty or serie.nunique() < 2:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) and serie.nunique() > MAX_MODALITES_CLASSIFICATION:
            famille, ratio = "regression", None
        else:
            ratio = float(serie.value_counts(normalize=True).min())
            famille = ("classification_desequilibree"
                       if ratio < SEUIL_DESEQUILIBRE else "classification")
        cibles.append({
            "colonne": str(col),
            "famille": famille,
            "n_modalites": int(serie.nunique()),
            "ratio_minoritaire": ratio,
        })
    return cibles


def _repondre_json(prompt: str, model: str | None) -> dict:
    """Appelle le LLM et lit sa réponse JSON, sans jamais lever.

    Une proposition est un confort : si le modèle est injoignable ou bavard, on
    rend une proposition vide et l'interface retombe sur son comportement
    antérieur. Faire échouer l'ouverture de la modale serait hors de proportion.
    """
    from app.services.gemini_service import complete_text

    try:
        texte = complete_text(prompt, model or config.get_default_model()).strip()
    except Exception as exc:
        logger.info("Proposition de variables indisponible (%s)", exc)
        return {}

    if texte.startswith("```"):
        lignes = texte.split("\n")
        texte = "\n".join(lignes[1:-1] if lignes[-1].strip().startswith("```") else lignes[1:])

    try:
        valeur = json.loads(texte)
    except json.JSONDecodeError:
        logger.info("Proposition de variables non-JSON, ignorée.")
        return {}
    return valeur if isinstance(valeur, dict) else {}


def _colonne_valide(proposee, autorisees: list[str]) -> str | None:
    """Ramène une réponse du modèle à une colonne réellement sélectionnable."""
    if not isinstance(proposee, str):
        return None
    nom = proposee.strip().strip('"\'`').strip()
    if nom in autorisees:
        return nom
    for colonne in autorisees:
        if str(colonne).strip().lower() == nom.lower():
            return colonne
    return None


def proposer_cible_supervisee(df, model: str | None = None) -> dict:
    """Cible que le LLM juge la plus plausible, parmi les candidates admissibles.

    Retourne `{"colonne", "motif", "famille", "candidates"}` — `colonne` à None
    si aucune proposition exploitable, l'interface gardant alors la main.
    """
    candidates = cibles_supervisees(df)
    if not candidates:
        return {"colonne": None, "motif": "", "famille": None, "candidates": []}

    description = "\n".join(
        f"- {c['colonne']} (famille : {c['famille']}, {c['n_modalites']} modalités)"
        for c in candidates
    )
    prompt = (
        f"Voici les colonnes d'un jeu de données pouvant servir de variable cible "
        f"à un modèle prédictif :\n{description}\n\n"
        f"Laquelle est la plus plausible comme variable à PRÉDIRE dans une étude "
        f"réelle sur ce jeu de données ?\n"
        f"Écarte les identifiants, les codes techniques et les colonnes qui ne "
        f"représentent rien de métier.\n\n"
        f"Réponds UNIQUEMENT par ce JSON, sans markdown :\n"
        f'{{"colonne": "<nom exact d\'une colonne de la liste>", '
        f'"motif": "<une phrase expliquant pourquoi>"}}'
    )

    reponse = _repondre_json(prompt, model)
    autorisees = [c["colonne"] for c in candidates]
    colonne = _colonne_valide(reponse.get("colonne"), autorisees)
    famille = next((c["famille"] for c in candidates if c["colonne"] == colonne), None)

    return {
        "colonne": colonne,
        "motif": str(reponse.get("motif") or "").strip() if colonne else "",
        "famille": famille,
        "candidates": candidates,
    }


def proposer_colonnes_serie(df, model: str | None = None) -> dict:
    """Couple (axe temporel, valeur à prévoir) proposé par le LLM.

    Retourne `{"date", "valeur", "motif", "date_columns", "value_columns"}`.
    """
    from app.services.timeseries_service import detect_timeseries_columns

    dates, valeurs = detect_timeseries_columns(df)
    # Une colonne d'années est à la fois une date plausible et un numérique : elle
    # ne peut pas être les deux à la fois dans un même modèle.
    valeurs_possibles = [v for v in valeurs if v not in dates] or valeurs
    if not dates or not valeurs_possibles:
        return {"date": None, "valeur": None, "motif": "",
                "date_columns": dates, "value_columns": valeurs}

    prompt = (
        f"Jeu de données à modéliser en série temporelle.\n"
        f"Colonnes utilisables comme axe temporel : {', '.join(dates)}\n"
        f"Colonnes numériques utilisables comme valeur à prévoir : "
        f"{', '.join(valeurs_possibles)}\n\n"
        f"Quel couple (axe temporel, valeur à prévoir) a le plus de sens ?\n"
        f"Écarte les identifiants et les compteurs de lignes comme valeur à prévoir.\n\n"
        f"Réponds UNIQUEMENT par ce JSON, sans markdown :\n"
        f'{{"date": "<nom exact>", "valeur": "<nom exact>", '
        f'"motif": "<une phrase expliquant pourquoi>"}}'
    )

    reponse = _repondre_json(prompt, model)
    date = _colonne_valide(reponse.get("date"), dates)
    valeur = _colonne_valide(reponse.get("valeur"), valeurs_possibles)
    # Une proposition incomplète ou qui prévoit l'axe lui-même n'est pas exploitable.
    if not date or not valeur or date == valeur:
        date = valeur = None

    return {
        "date": date,
        "valeur": valeur,
        "motif": str(reponse.get("motif") or "").strip() if date else "",
        "date_columns": dates,
        "value_columns": valeurs,
    }
