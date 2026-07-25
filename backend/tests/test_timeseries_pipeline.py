import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.timeseries_service as timeseries_service
import app.services.timeseries_pipeline as timeseries_pipeline


def _echec_moteur_auto(*args, **kwargs):
    return {
        "metrics": None,
        "images": [],
        "output": "",
        "error": {
            "technical": "ModuleNotFoundError: statsforecast",
            "simple": "Le moteur de prévision automatique n'a produit aucun résultat exploitable.",
        },
    }


def test_autoforecast_bascule_sur_le_moteur_rigoureux_en_cas_d_echec(monkeypatch):
    calls = []

    def fake_rigorous(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "ok": True,
            "response": "fallback ok",
            "images": [],
            "model_id": "model-123",
            "report": {"statut_final": "OK"},
            "error": None,
        }

    monkeypatch.setattr(timeseries_service, "run_autoforecast", _echec_moteur_auto)
    monkeypatch.setattr(timeseries_pipeline, "run_rigorous_timeseries", fake_rigorous)

    result = timeseries_pipeline.run_autoforecast_timeseries(
        question="Prévoir la série",
        file_bytes=b"a,b\n1,2\n",
        filename="data.csv",
        session_id="session-1",
        data_context="",
        history=[],
        model="gemma2:latest",
        date_col="a",
        value_col="b",
    )

    assert result["ok"] is True
    assert result["response"].startswith("fallback ok")
    assert len(calls) == 1
    # Le secours doit recevoir les colonnes, sinon il repart d'une série inconnue.
    assert calls[0][1]["date_col"] == "a"
    assert calls[0][1]["value_col"] == "b"


def test_autoforecast_exige_les_colonnes_de_la_serie():
    """Sans date_col/value_col le moteur ne peut rien faire : échouer explicitement
    plutôt que de lancer un calcul sur une série arbitraire."""
    result = timeseries_pipeline.run_autoforecast_timeseries(
        question="Prévoir",
        file_bytes=b"a,b\n1,2\n",
        filename="data.csv",
        session_id="session-1",
    )
    assert result["ok"] is False
    assert result["model_id"] is None


def test_nom_du_modele_sans_ordre_utilise_son_type():
    """Un modèle non-ARIMA (ETS, Theta) n'a pas d'ordre (p,d,q) : son type doit
    suffire à le nommer, sans retomber sur le libellé générique."""
    nom = timeseries_pipeline._model_name_from_report(
        {"modele_retenu": {"type": "AutoETS", "ordre": None}}, "générique"
    )
    assert nom == "AutoETS"


def test_nom_du_modele_sarima_conserve_ordres():
    nom = timeseries_pipeline._model_name_from_report(
        {"modele_retenu": {"type": "SARIMA", "ordre": [0, 1, 1],
                           "ordre_saisonnier": [0, 1, 1, 12]}},
        "générique",
    )
    assert nom == "SARIMA (0, 1, 1)x(0, 1, 1, 12)"
