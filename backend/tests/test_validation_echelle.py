"""Le code du pipeline rigoureux est écrit par le LLM : il lui arrive d'oublier la
transformation inverse et de livrer une prévision en log sous un historique en
échelle d'origine. Le schéma Pydantic ne voit rien (les types sont bons), mais le
dashboard affiche une prévision à ~1 sous un historique à ~432.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.model_specs import MODEL_SPECS, ModelFamily
from app.services.sandbox_service import _incoherence_echelle_prevision, validate_output

_SPEC = MODEL_SPECS[ModelFamily.TIME_SERIES]


def _rapport(hist_vals, prev_vals):
    return {
        "serie": {}, "transformation": {}, "stationnarite": {},
        "modele_retenu": {"type": "SARIMA", "ordre": [0, 1, 1]},
        "gate_1_diagnostics_residus": {"statut": "PASS"},
        "gate_2_validation_out_of_sample": {"statut": "PASS"},
        "statut_final": "MODELE_VALIDE",
        "avertissements": [],
        "historique": [{"date": f"1949-{i % 12 + 1:02d}-01", "valeur": v}
                       for i, v in enumerate(hist_vals)],
        "prevision": [{"date": f"1961-{i + 1:02d}-01", "valeur_prevue": v,
                       "ic_bas": v * 0.95, "ic_haut": v * 1.05}
                      for i, v in enumerate(prev_vals)],
    }


def test_detecte_une_prevision_restee_en_log():
    # Historique ~400 (échelle d'origine), prévision ~6 (log non ré-exponentié).
    motif = _incoherence_echelle_prevision(_rapport([400.0] * 24, [6.0] * 12))
    assert motif is not None
    assert "Échelle incohérente" in motif


def test_accepte_une_prevision_a_la_bonne_echelle():
    assert _incoherence_echelle_prevision(_rapport([400.0] * 24, [450.0] * 12)) is None


def test_tolere_une_croissance_forte_mais_plausible():
    """Une série peut légitimement croître : le seuil ne doit pas être si serré
    qu'il rejette une tendance réelle."""
    assert _incoherence_echelle_prevision(_rapport([100.0] * 24, [380.0] * 12)) is None


def test_ignore_les_series_trop_courtes_ou_vides():
    assert _incoherence_echelle_prevision(_rapport([400.0], [450.0])) is None
    assert _incoherence_echelle_prevision(_rapport([], [])) is None


def test_validate_output_relance_l_autocorrection_sur_echelle_incoherente():
    """L'incohérence doit remonter comme une erreur : c'est ce qui déclenche une
    nouvelle tentative auprès du LLM dans run_with_autocorrect."""
    result = {"error": None, "output": "x", "images": [],
              "metrics": _rapport([400.0] * 24, [6.0] * 12)}
    out = validate_output(result, _SPEC)
    assert out["error"] is not None
    assert "échelle" in out["error"]["simple"].lower()


def test_validate_output_laisse_passer_un_rapport_coherent():
    result = {"error": None, "output": "x", "images": [],
              "metrics": _rapport([400.0] * 24, [450.0] * 12)}
    assert validate_output(result, _SPEC)["error"] is None
