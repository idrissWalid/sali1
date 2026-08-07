"""Le LLM propose les colonnes à modéliser, l'utilisateur garde la décision.

La règle que ces tests verrouillent : une proposition n'est retenue que si elle
désigne une colonne réellement sélectionnable dans l'interface. Sinon la modale
présélectionnerait une valeur absente de son propre sélecteur, et l'entraînement
échouerait plus loin sur un nom inconnu.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.variable_proposal as vp


@pytest.fixture
def df():
    return pd.DataFrame({
        "id": range(1, 61),
        "date_mesure": pd.date_range("2020-01-01", periods=60, freq="MS"),
        "rendement": [1.0 + i * 0.1 for i in range(60)],
        "region": ["Centre", "Nord", "Sud"] * 20,
        "constante": [1] * 60,
    })


def _reponse(monkeypatch, charge):
    """Force la réponse du LLM, sans appel réseau."""
    texte = charge if isinstance(charge, str) else json.dumps(charge, ensure_ascii=False)
    monkeypatch.setattr(
        "app.services.gemini_service.complete_text",
        lambda prompt, model, **kw: texte,
    )


class TestCiblesSupervisees:
    def test_ecarte_les_colonnes_constantes(self, df):
        colonnes = [c["colonne"] for c in vp.cibles_supervisees(df)]
        assert "constante" not in colonnes  # une seule modalité : rien à prédire
        assert "rendement" in colonnes

    def test_famille_deduite_du_type_et_du_nombre_de_modalites(self, df):
        familles = {c["colonne"]: c["famille"] for c in vp.cibles_supervisees(df)}
        assert familles["rendement"] == "regression"       # continue
        assert familles["region"].startswith("classification")


class TestPropositionSupervisee:
    def test_retient_une_colonne_valide_et_son_motif(self, df, monkeypatch):
        _reponse(monkeypatch, {"colonne": "rendement", "motif": "Variable métier continue."})
        p = vp.proposer_cible_supervisee(df, "modele-test")
        assert p["colonne"] == "rendement"
        assert p["famille"] == "regression"
        assert "métier" in p["motif"]

    def test_tolere_une_casse_differente(self, df, monkeypatch):
        _reponse(monkeypatch, {"colonne": "RENDEMENT", "motif": "x"})
        assert vp.proposer_cible_supervisee(df, "m")["colonne"] == "rendement"

    @pytest.mark.parametrize("charge", [
        {"colonne": "chiffre_affaires", "motif": "inventée"},  # colonne inexistante
        {"colonne": "constante", "motif": "écartée des candidates"},
        {"motif": "sans colonne"},
        "je ne sais pas répondre en JSON",
    ])
    def test_refuse_une_proposition_inexploitable(self, df, monkeypatch, charge):
        _reponse(monkeypatch, charge)
        p = vp.proposer_cible_supervisee(df, "m")
        assert p["colonne"] is None
        assert p["candidates"], "les candidates restent servies à l'interface"

    def test_un_llm_injoignable_ne_casse_pas_l_ouverture_de_la_modale(self, df, monkeypatch):
        def boum(*a, **k):
            raise RuntimeError("LLM injoignable")
        monkeypatch.setattr("app.services.gemini_service.complete_text", boum)
        assert vp.proposer_cible_supervisee(df, "m")["colonne"] is None


class TestPropositionSerie:
    def test_retient_un_couple_valide(self, df, monkeypatch):
        _reponse(monkeypatch, {"date": "date_mesure", "valeur": "rendement", "motif": "Série mensuelle."})
        p = vp.proposer_colonnes_serie(df, "m")
        assert (p["date"], p["valeur"]) == ("date_mesure", "rendement")

    def test_refuse_de_prevoir_l_axe_temporel_lui_meme(self, df, monkeypatch):
        _reponse(monkeypatch, {"date": "date_mesure", "valeur": "date_mesure", "motif": "x"})
        p = vp.proposer_colonnes_serie(df, "m")
        assert p["date"] is None and p["valeur"] is None

    def test_refuse_un_couple_incomplet(self, df, monkeypatch):
        _reponse(monkeypatch, {"date": "date_mesure", "motif": "valeur manquante"})
        assert vp.proposer_colonnes_serie(df, "m")["valeur"] is None

    def test_sert_toujours_les_candidates(self, df, monkeypatch):
        _reponse(monkeypatch, "pas du JSON")
        p = vp.proposer_colonnes_serie(df, "m")
        assert "date_mesure" in p["date_columns"]
        assert "rendement" in p["value_columns"]
