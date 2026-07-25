"""Tournoi supervisé : régression, classification, classification déséquilibrée.

Un modèle n'est validé que si TROIS conditions tiennent — exécution sans erreur,
hypothèses bloquantes respectées, performances au-dessus d'une baseline triviale.
Ces tests verrouillent surtout la troisième : sans elle, un R² de 0,03 passait
pour un « modèle validé ».
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.supervised_code import build_supervised_code
from app.services.supervised_specs import (
    BUDGET_SECONDES, Famille, MCC_MIN_UTILE, MODELES, R2_MIN_UTILE,
    SEUIL_DESEQUILIBRE, STATUT_HYPOTHESES, VIF_BLOQUANT,
)


class TestSpecifications:
    def test_trois_modeles_par_famille(self):
        """L'utilisateur ne choisit pas : chaque famille engage exactement trois
        modèles complémentaires."""
        assert set(MODELES) == set(Famille)
        for famille, liste in MODELES.items():
            assert len(liste) == 3, famille

    def test_normalite_non_bloquante(self):
        """Shapiro rejette la normalité dès n>500 sur des données réelles. La
        rendre bloquante condamnerait le tournoi à épuiser son budget pour rien."""
        assert STATUT_HYPOTHESES["normalite_residus"] == "informative"
        assert STATUT_HYPOTHESES["points_influents"] == "informative"

    def test_hypotheses_invalidant_l_inference_restent_bloquantes(self):
        for cle in ("multicolinearite", "linearite", "independance_residus",
                    "separation_complete", "epv_suffisant"):
            assert STATUT_HYPOTHESES[cle] == "bloquante", cle

    def test_heteroscedasticite_remediee_et_non_bloquante(self):
        """Elle se corrige par des erreurs-types robustes : bloquer serait inutile."""
        assert STATUT_HYPOTHESES["homoscedasticite"] == "remediee"

    def test_budget_de_dix_minutes(self):
        assert BUDGET_SECONDES == 600

    def test_seuils_d_utilite_non_triviaux(self):
        """« Battre la baseline » au sens strict (R²>0) laisse passer du bruit."""
        assert R2_MIN_UTILE > 0
        assert MCC_MIN_UTILE > 0
        assert VIF_BLOQUANT > 5


class TestGenerationDuScript:
    def test_script_syntaxiquement_valide(self):
        import ast

        ast.parse(build_supervised_code("cible", ["a", "b"]))

    def test_budget_personnalisable(self):
        assert "BUDGET = 42" in build_supervised_code("y", ["a"], budget=42)
        assert f"BUDGET = {BUDGET_SECONDES}" in build_supervised_code("y", ["a"])

    def test_noms_de_colonnes_echappes(self):
        """Une colonne contenant une apostrophe ne doit pas casser le script."""
        import ast

        code = build_supervised_code("l'âge", ["nom \"complet\"", "x"])
        ast.parse(code)


# ── Tests d'exécution réelle dans le sandbox ────────────────────────────────
# Marqués `sandbox` (déclaré dans pytest.ini) : ils lancent Docker et sont donc
# plus lents. Ils vérifient ce qu'aucun test unitaire ne peut garantir — que les
# seuils rejettent bien les modèles inutiles sur de vraies données.


def _executer(df, cible, feats, budget=120):
    from app.services.sandbox_service import execute_code

    code = build_supervised_code(cible, feats, budget=budget)
    r = execute_code(code, dataframe_bytes=df.to_csv(index=False).encode(), filename="t.csv")
    assert not r.get("error"), r.get("error")
    return r["metrics"]


@pytest.fixture(scope="module")
def jeu_ads():
    import pandas as pd

    chemin = next(
        Path(__file__).resolve().parents[2].joinpath("data/uploads").glob("*Social_Network_Ads.csv"),
        None,
    )
    if chemin is None:
        pytest.skip("Jeu de données Social_Network_Ads absent.")
    return pd.read_csv(chemin)


@pytest.mark.sandbox
class TestExecutionReelle:
    def test_classification_detectee_et_validee(self, jeu_ads):
        m = _executer(jeu_ads, "Purchased", ["Age", "EstimatedSalary", "Gender"])
        assert m["famille"] == "classification"
        assert m["statut_final"] == "MODELE_VALIDE"
        perf = m["modele_retenu"]["performances"]
        # Le modèle doit battre la classe majoritaire, pas seulement l'égaler.
        assert perf["accuracy_test"] > perf["accuracy_baseline"]
        assert perf["mcc"] >= MCC_MIN_UTILE

    def test_sortie_anticipee_quand_le_premier_convient(self, jeu_ads):
        """Le budget ne doit pas être consommé si les normes sont déjà tenues."""
        m = _executer(jeu_ads, "Purchased", ["Age", "EstimatedSalary", "Gender"])
        assert m["sortie_anticipee"] is True
        assert len(m["candidats"]) < len(MODELES[Famille.CLASSIFICATION])

    def test_regression_sans_pouvoir_predictif_rejetee(self, jeu_ads):
        """Le salaire ne s'explique pas par l'âge et le genre : R² ≈ 0,04. Ce
        modèle était livré comme « validé » avant l'ajout des seuils d'utilité."""
        m = _executer(jeu_ads, "EstimatedSalary", ["Age", "Gender"])
        assert m["famille"] == "regression"
        assert m["statut_final"] == "AUCUN_MODELE_UTILE"
        # Les trois modèles ont été essayés avant de conclure.
        assert len(m["candidats"]) == 3
        assert any("negligeable" in v.lower() for v in m["violations"])

    def test_normalite_signalee_sans_bloquer(self, jeu_ads):
        m = _executer(jeu_ads, "EstimatedSalary", ["Age", "Gender"])
        avert = " ".join(m["candidats"][0].get("avertissements") or [])
        assert "Normalite" in avert or "normalite" in avert
        # Elle apparaît en avertissement, jamais en violation.
        assert not any("normalit" in v.lower() for v in m["candidats"][0]["violations"])

    def test_desequilibre_detecte_et_route(self, jeu_ads):
        d = jeu_ads.copy()
        d["Rare"] = ((d["Purchased"] == 1) & (d["Age"] > 48)).astype(int)
        assert d["Rare"].mean() < SEUIL_DESEQUILIBRE  # sinon le test ne teste rien
        m = _executer(d, "Rare", ["Age", "EstimatedSalary", "Gender"])
        assert m["famille"] == "classification_desequilibree"
        assert m["ratio_minoritaire"] < SEUIL_DESEQUILIBRE
        # Sur cette famille, le seuil de décision est optimisé, pas laissé à 0,5.
        assert m["modele_retenu"]["seuil_decision"] is not None


@pytest.mark.sandbox
class TestArtefactDeployable:
    """Le tournoi encode X en one-hot avant d'entraîner : l'estimateur brut est
    donc inutilisable tel quel. On réajuste un Pipeline qui accepte les colonnes
    d'origine — c'est lui qui alimente la simulation et l'export."""

    def test_pipeline_accepte_les_colonnes_brutes(self, jeu_ads):
        import base64
        import io as _io
        import tempfile

        import joblib
        import pandas as pd

        from app.services.sandbox_service import execute_code

        code = build_supervised_code("Purchased", ["Age", "EstimatedSalary", "Gender"], budget=120)
        r = execute_code(code, dataframe_bytes=jeu_ads.to_csv(index=False).encode(), filename="t.csv")
        assert not r.get("error"), r.get("error")

        art = r["metrics"].get("artefact") or {}
        assert art.get("disponible") is True
        # Colonnes BRUTES, pas les colonnes encodées : c'est ce que le formulaire
        # de simulation présente à l'utilisateur.
        assert "Gender" in art["colonnes_attendues"]
        assert art["modalites"]["Gender"]

        artefacts = r.get("models") or []
        assert artefacts, "aucun .pkl remonté par le sandbox"

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fh:
            fh.write(base64.b64decode(artefacts[0]["model_b64"]))
            chemin = fh.name
        pipe = joblib.load(chemin)

        # Le pipeline doit prédire à partir d'un DataFrame de colonnes d'origine,
        # catégorielle comprise, sans encodage manuel.
        entree = pd.DataFrame([{"Age": 48, "EstimatedSalary": 95000, "Gender": "Male"}])
        assert pipe.predict(entree).shape == (1,)
        proba = pipe.predict_proba(entree)[0]
        assert abs(float(proba.sum()) - 1.0) < 1e-6

    def test_modalite_inconnue_ne_leve_pas(self, jeu_ads):
        """handle_unknown='ignore' : une modalité jamais vue doit dégrader la
        prédiction, pas faire planter la simulation."""
        import base64
        import tempfile

        import joblib
        import pandas as pd

        from app.services.sandbox_service import execute_code

        code = build_supervised_code("Purchased", ["Age", "EstimatedSalary", "Gender"], budget=120)
        r = execute_code(code, dataframe_bytes=jeu_ads.to_csv(index=False).encode(), filename="t.csv")
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fh:
            fh.write(base64.b64decode((r["models"] or [{}])[0]["model_b64"]))
            chemin = fh.name
        pipe = joblib.load(chemin)
        entree = pd.DataFrame([{"Age": 30, "EstimatedSalary": 50000, "Gender": "Non renseigné"}])
        assert pipe.predict(entree).shape == (1,)


@pytest.mark.sandbox
def test_courbes_roc_et_pr_produites(jeu_ads):
    """Une AUC sans sa courbe n'est pas affichable, et une PR-AUC sans la
    prévalence est ininterprétable."""
    m = _executer(jeu_ads, "Purchased", ["Age", "EstimatedSalary", "Gender"])
    ret = m["modele_retenu"]
    assert len(ret.get("roc_curve") or []) > 5
    assert len(ret.get("pr_curve") or []) > 5
    assert ret["performances"].get("prevalence_positive") is not None
    for p in ret["roc_curve"]:
        assert 0 <= p["fpr"] <= 1 and 0 <= p["tpr"] <= 1
