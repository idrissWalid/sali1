"""naming_service.py — Titre de session déduit du contenu du fichier.

Nommer une session d'après son seul nom de fichier rend l'historique illisible :
trois analyses de `airline-passengers.csv` donnent trois entrées identiques, et un
document importé restait carrément « Nouvelle session ».

On demande donc au LLM un intitulé court décrivant *ce que contient* le fichier
(« Trafic aérien mensuel 1949-1960 ») plutôt que son nom. Le nom de fichier reste
le repli : un titre est un confort, il ne doit jamais faire échouer un import.
"""

import re
from pathlib import Path

from app.core import config
from app.services.gemini_service import complete_text

# Au-delà, le titre est tronqué dans la barre latérale : autant le cadrer ici.
MAX_TITRE = 60
# Un dépassement modéré se rattrape en tronquant ; au-delà, le modèle a répondu
# par une phrase et non par un titre — mieux vaut alors le nom du fichier qu'un
# début de paragraphe coupé net.
MAX_TITRE_TOLERE = 90


def _nettoyer(brut: str) -> str:
    """Réduit la réponse du LLM à une seule ligne de titre exploitable.

    Les modèles ajoutent volontiers des guillemets, un « Titre : » ou une phrase
    d'introduction ; on ne garde que la substance.
    """
    titre = (brut or "").strip()
    # Ne conserver que la première ligne non vide.
    for ligne in titre.splitlines():
        if ligne.strip():
            titre = ligne.strip()
            break
    titre = re.sub(r"^\s*(titre|title)\s*[:\-–]\s*", "", titre, flags=re.I)
    titre = titre.strip().strip('"\'«»').strip()
    # Puces et emphase Markdown, que les modèles ajoutent spontanément. Le point
    # final est retiré dans la même passe : sur « **Bilan 2024**. » les deux se
    # suivent, et les traiter séparément laisserait les astérisques.
    titre = re.sub(r"^[-*#>\s]+", "", titre)
    titre = re.sub(r"[*_#.\s]+$", "", titre)
    return re.sub(r"\s+", " ", titre)


def _tronquer(titre: str) -> str:
    """Ramène un titre un peu trop long à `MAX_TITRE`, sans couper un mot."""
    if len(titre) <= MAX_TITRE:
        return titre
    coupe = titre[:MAX_TITRE].rsplit(" ", 1)[0]
    return (coupe or titre[:MAX_TITRE]).rstrip(",;:-") + "…"


def _repli(filename: str | None) -> str:
    """Nom de fichier rendu présentable, à défaut de mieux."""
    if not filename:
        return "Nouvelle session"
    base = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    base = re.sub(r"\s+", " ", base)
    return (base[:MAX_TITRE] or Path(filename).name).capitalize()


def _demander(prompt: str, model: str | None) -> str | None:
    try:
        titre = _nettoyer(complete_text(prompt, model or config.get_default_model()))
    except Exception:
        return None
    # La validation porte sur le titre NON tronqué : tronquer d'abord masquerait
    # justement les réponses trop bavardes qu'on veut écarter.
    if not (3 <= len(titre) <= MAX_TITRE_TOLERE):
        return None
    return _tronquer(titre)


def titre_depuis_donnees(
    filename: str,
    profile: dict | None,
    apercu_interpretation: str = "",
    model: str | None = None,
) -> str:
    """Titre d'une session tabulaire, déduit des colonnes et d'un aperçu."""
    colonnes = (profile or {}).get("column_names") or []
    n_lignes = (profile or {}).get("n_rows") or (profile or {}).get("rows")

    details = [f"Nom du fichier : {filename}"]
    if colonnes:
        details.append(f"Colonnes : {', '.join(map(str, colonnes[:25]))}")
    if n_lignes:
        details.append(f"Nombre de lignes : {n_lignes}")
    if apercu_interpretation:
        details.append(f"Résumé de l'analyse : {apercu_interpretation[:600]}")

    prompt = (
        "Voici un jeu de données qui vient d'être importé dans une application "
        "d'analyse :\n\n" + "\n".join(details) + "\n\n"
        "Donne-lui un titre court et parlant, en français, qui décrit CE QUE "
        "CONTIENT ce jeu de données (son sujet), et non le nom du fichier.\n"
        "Contraintes : 3 à 7 mots, pas de guillemets, pas de point final, pas "
        "d'extension de fichier, pas de préfixe comme « Titre : ».\n"
        "Exemple attendu : Trafic aérien mensuel 1949-1960\n"
        "Réponds UNIQUEMENT par le titre."
    )
    return _demander(prompt, model) or _repli(filename)


def titre_depuis_document(
    filename: str,
    extrait: str = "",
    model: str | None = None,
) -> str:
    """Titre d'une session document, déduit du texte (ou du résumé) du fichier."""
    details = [f"Nom du fichier : {filename}"]
    if extrait.strip():
        details.append(f"Extrait du document :\n{extrait.strip()[:1500]}")

    prompt = (
        "Voici un document qui vient d'être importé dans une application "
        "d'analyse :\n\n" + "\n".join(details) + "\n\n"
        "Donne-lui un titre court et parlant, en français, qui décrit SON SUJET, "
        "et non le nom du fichier.\n"
        "Contraintes : 3 à 8 mots, pas de guillemets, pas de point final, pas "
        "d'extension de fichier, pas de préfixe comme « Titre : ».\n"
        "Réponds UNIQUEMENT par le titre."
    )
    return _demander(prompt, model) or _repli(filename)
