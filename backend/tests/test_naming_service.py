"""Le titre de session vient du contenu du fichier, pas de son nom : sans ça,
trois imports de `airline-passengers.csv` donnent trois entrées identiques dans
l'historique, et un document importé restait « Nouvelle session ».
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.naming_service as naming
from app.services.naming_service import MAX_TITRE, _nettoyer, _repli, _tronquer


def _reponse(texte):
    return lambda prompt, model, history=None: texte


class TestNettoyage:
    """Les modèles enrobent volontiers leur réponse ; on ne garde que le titre."""

    def test_titre_deja_propre_inchange(self):
        assert _nettoyer("Trafic aérien mensuel 1949-1960") == "Trafic aérien mensuel 1949-1960"

    def test_retire_guillemets_et_prefixe(self):
        assert _nettoyer('"Trafic aérien"') == "Trafic aérien"
        assert _nettoyer("Titre : Évolution du trafic") == "Évolution du trafic"
        assert _nettoyer("« Analyse des ventes »") == "Analyse des ventes"

    def test_retire_emphase_markdown_et_point_final(self):
        # Les deux se suivent : les traiter séparément laisserait les astérisques.
        assert _nettoyer("**Bilan 2024**.") == "Bilan 2024"
        assert _nettoyer("### Rapport annuel ###") == "Rapport annuel"

    def test_ne_garde_que_la_premiere_ligne(self):
        assert _nettoyer("Trafic aérien\n\nVoici pourquoi ce titre convient…") == "Trafic aérien"

    def test_nettoyage_ne_tronque_pas(self):
        """La troncature est séparée : sinon elle masquerait les réponses trop
        bavardes que `_demander` doit justement écarter."""
        long = "Un titre exagérément long qui dépasse largement la limite fixée et continue encore"
        assert _nettoyer(long) == long

    def test_troncature_au_mot_sans_couper(self):
        out = _tronquer("Un titre exagérément long qui dépasse largement la limite fixée et continue")
        assert len(out) <= MAX_TITRE + 1
        assert out.endswith("…")
        # La troncature tombe sur une frontière de mot, pas au milieu.
        assert not out[:-1].rstrip().endswith(" ")

    def test_troncature_laisse_un_titre_court_intact(self):
        assert _tronquer("Ventes T4 2024") == "Ventes T4 2024"


class TestRepli:
    def test_nom_de_fichier_rendu_presentable(self):
        assert _repli("airline-passengers.csv") == "Airline passengers"
        assert _repli("rapport_annuel_2024.pdf") == "Rapport annuel 2024"

    def test_sans_fichier(self):
        assert _repli(None) == "Nouvelle session"


class TestGenerationTitre:
    def test_utilise_la_reponse_du_llm(self, monkeypatch):
        monkeypatch.setattr(naming, "complete_text", _reponse("Trafic aérien mensuel"))
        titre = naming.titre_depuis_donnees(
            "airline-passengers.csv", {"column_names": ["Month", "Passengers"], "n_rows": 144}
        )
        assert titre == "Trafic aérien mensuel"

    def test_repli_sur_le_nom_de_fichier_si_le_llm_echoue(self, monkeypatch):
        """Un titre est un confort : il ne doit jamais faire échouer un import."""
        def boum(*a, **k):
            raise RuntimeError("API indisponible")

        monkeypatch.setattr(naming, "complete_text", boum)
        assert naming.titre_depuis_donnees("airline-passengers.csv", {}) == "Airline passengers"
        assert naming.titre_depuis_document("rapport_annuel_2024.pdf", "texte") == "Rapport annuel 2024"

    def test_repli_si_le_llm_repond_un_paragraphe(self, monkeypatch):
        """Mieux vaut le nom de fichier qu'une phrase tronquée en plein milieu."""
        bavard = ("Bien sûr ! Voici une proposition de titre pour ce jeu de données, "
                  "en tenant compte de ses colonnes et de sa période de couverture, "
                  "ainsi que des tendances observées dans la série temporelle.")
        monkeypatch.setattr(naming, "complete_text", _reponse(bavard))
        assert naming.titre_depuis_donnees("airline-passengers.csv", {}) == "Airline passengers"

    def test_repli_si_le_llm_repond_vide(self, monkeypatch):
        monkeypatch.setattr(naming, "complete_text", _reponse("   "))
        assert naming.titre_depuis_donnees("ventes.csv", {}) == "Ventes"

    def test_document_utilise_l_extrait(self, monkeypatch):
        recu = {}

        def capture(prompt, model, history=None):
            recu["prompt"] = prompt
            return "Rapport annuel BCEAO"

        monkeypatch.setattr(naming, "complete_text", capture)
        titre = naming.titre_depuis_document("doc_final_v2.pdf", "Rapport de la Banque Centrale…")
        assert titre == "Rapport annuel BCEAO"
        assert "Banque Centrale" in recu["prompt"]
