"""Un classeur à plusieurs feuilles est un dossier de tableaux, pas un tableau.

`pd.read_excel` sans `sheet_name` ne lit que la première feuille, en silence.
Sur un classeur institutionnel qui commence par une page de garde, tout — le
profil, le contexte du modèle, le tableau de bord, le sandbox — portait alors
sur la couverture, sans que rien ne le signale.
"""

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.upload import _phrase_feuilles, _resume_feuilles
from app.services.ingestion_service import MAX_FEUILLES, decouper_classeur


def _classeur(feuilles: dict) -> bytes:
    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as writer:
        for nom, df in feuilles.items():
            df.to_excel(writer, sheet_name=nom, index=False)
    return tampon.getvalue()


_DONNEES = pd.DataFrame({"region": ["Dakar", "Thiès"], "ventes": [120, 90]})
_COUVERTURE = pd.DataFrame({"Rapport annuel": ["Direction des statistiques", "Version 2026"]})


def test_un_fichier_a_une_seule_feuille_suit_le_chemin_inchange():
    """Le découpage ne doit rien changer au cas courant."""
    assert decouper_classeur(_classeur({"Feuille1": _DONNEES}), "simple.xlsx") is None


def test_un_csv_n_est_pas_un_classeur():
    assert decouper_classeur(b"a,b\n1,2\n", "donnees.csv") is None


def test_la_page_de_garde_ne_devient_pas_le_jeu_principal():
    """Le cœur du problème : la première feuille n'est pas la bonne."""
    octets = _classeur({
        "Couverture": _COUVERTURE,
        "Donnees 2024": _DONNEES,
        "Donnees 2025": _DONNEES,
    })
    resultat = decouper_classeur(octets, "rapport_2026.xlsx")

    assert [f["nom"] for f in resultat["feuilles"]] == ["Donnees 2024", "Donnees 2025"]
    assert resultat["ignorees"] == ["Couverture"]
    assert resultat["total"] == 3


def test_chaque_feuille_devient_un_csv_lisible_par_toute_la_chaine():
    """L'extension n'est pas cosmétique : elle choisit le lecteur en aval."""
    octets = _classeur({"Donnees": _DONNEES, "Autre": _DONNEES})
    feuille = decouper_classeur(octets, "rapport.xlsx")["feuilles"][0]

    assert feuille["filename"].endswith(".csv")
    relu = pd.read_csv(io.BytesIO(feuille["bytes"]))
    assert list(relu.columns) == ["region", "ventes"]
    assert len(relu) == 2


def test_le_nom_affiche_porte_le_classeur_et_la_feuille():
    octets = _classeur({"Donnees": _DONNEES, "Autre": _DONNEES})
    feuilles = decouper_classeur(octets, "rapport_2026.xlsx")["feuilles"]
    assert feuilles[0]["nom_affichage"] == "rapport_2026 — Donnees"


def test_les_feuilles_vides_sont_ecartees():
    octets = _classeur({"Donnees": _DONNEES, "Vide": pd.DataFrame()})
    resultat = decouper_classeur(octets, "rapport.xlsx")
    assert [f["nom"] for f in resultat["feuilles"]] == ["Donnees"]
    assert "Vide" in resultat["ignorees"]


def test_une_colonne_unique_mais_longue_reste_un_tableau():
    """Une liste de 10 valeurs et plus est une donnée, pas un titre."""
    longue = pd.DataFrame({"matricule": [f"M{i:03d}" for i in range(12)]})
    octets = _classeur({"Matricules": longue, "Donnees": _DONNEES})
    resultat = decouper_classeur(octets, "rapport.xlsx")
    assert [f["nom"] for f in resultat["feuilles"]] == ["Matricules", "Donnees"]


def test_si_l_heuristique_ecarte_tout_la_premiere_feuille_est_conservee():
    """Filet de sécurité : mieux vaut un tableau discutable que rien du tout."""
    octets = _classeur({"Couverture": _COUVERTURE, "Note": _COUVERTURE})
    resultat = decouper_classeur(octets, "rapport.xlsx")

    assert len(resultat["feuilles"]) == 1
    assert resultat["feuilles"][0]["nom"] == "Couverture"
    assert "Couverture" not in resultat["ignorees"]


def test_le_nombre_de_feuilles_importees_est_plafonne():
    octets = _classeur({f"F{i}": _DONNEES for i in range(MAX_FEUILLES + 4)})
    resultat = decouper_classeur(octets, "gros.xlsx")

    assert len(resultat["feuilles"]) == MAX_FEUILLES
    assert len(resultat["ignorees"]) == 4
    assert resultat["total"] == MAX_FEUILLES + 4


def test_le_resume_expose_la_feuille_retenue_au_client():
    octets = _classeur({"Couverture": _COUVERTURE, "Donnees": _DONNEES, "Autre": _DONNEES})
    classeur = decouper_classeur(octets, "rapport.xlsx")
    resume = _resume_feuilles(classeur, ["rapport — Autre"])

    assert resume["principale"] == "Donnees"
    assert resume["principale_affichage"] == "rapport — Donnees"
    assert resume["ajoutees"] == ["rapport — Autre"]
    assert resume["ignorees"] == ["Couverture"]


def test_sans_classeur_aucun_resume_n_est_produit():
    assert _resume_feuilles(None, []) is None


def test_la_phrase_dit_ce_qui_a_ete_importe_et_ce_qui_a_ete_ecarte():
    """Importer trois jeux de données en silence est exactement ce qu'il ne
    faut pas faire : la conversation doit le nommer."""
    octets = _classeur({"Couverture": _COUVERTURE, "Donnees": _DONNEES, "Autre": _DONNEES})
    classeur = decouper_classeur(octets, "rapport.xlsx")
    phrase = _phrase_feuilles(classeur, ["rapport — Autre"])

    assert "3 feuilles" in phrase
    assert "Donnees" in phrase
    assert "rapport — Autre" in phrase
    assert "Couverture" in phrase
