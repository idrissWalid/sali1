"""Régression : un NaN dans un rapport de modèle faisait échouer la sérialisation
de la réponse HTTP (`ValueError: Out of range float values are not JSON compliant`),
bien après coup, à la lecture du modèle — pas à son écriture.
"""

import json
import math
import sys
from pathlib import Path

import pytest
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.json_utils import SafeJSONResponse, dumps_safe, json_safe


def test_json_safe_remplace_les_flottants_non_finis():
    src = {
        "ok": 1.5,
        "historique": [{"valeur": float("nan")}, {"valeur": 2.0}],
        "bornes": [float("inf"), float("-inf")],
        "texte": "NaN",
    }
    out = json_safe(src)
    assert out["ok"] == 1.5
    assert out["historique"] == [{"valeur": None}, {"valeur": 2.0}]
    assert out["bornes"] == [None, None]
    # Une chaîne qui contient "NaN" n'est pas un flottant : ne pas y toucher.
    assert out["texte"] == "NaN"


def test_reponse_standard_echoue_la_ou_la_notre_passe():
    payload = {"metrics": {"historique": [{"date": "1949-01-01", "valeur": float("nan")}]}}

    with pytest.raises(ValueError):
        JSONResponse(payload)

    body = SafeJSONResponse(payload).body
    assert json.loads(body)["metrics"]["historique"][0]["valeur"] is None


def test_reponse_sans_nan_reste_identique_a_la_serialisation_standard():
    payload = {"a": 1, "b": [1.5, "x"], "c": {"d": None}}
    assert SafeJSONResponse(payload).body == JSONResponse(payload).body


def test_dumps_safe_n_ecrit_jamais_de_json_invalide():
    """`json.dumps` écrit `NaN` sans broncher et `json.loads` le relit : le JSON
    invalide se propage donc silencieusement jusqu'en base."""
    payload = {"valeur": float("nan")}

    naif = json.dumps(payload)
    assert "NaN" in naif
    assert math.isnan(json.loads(naif)["valeur"])  # relu sans erreur, d'où le piège

    sur = dumps_safe(payload)
    assert "NaN" not in sur
    assert json.loads(sur)["valeur"] is None
