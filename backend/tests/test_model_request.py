import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.model_request_service import parse_model_request, validate_model_request
from app.services.supervised_code import build_supervised_code


def test_random_forest_et_parametres_sont_extraits():
    request = parse_model_request(
        "Entraîne un Random Forest avec n_estimators=500, max_depth=8 et test_size=20%"
    )
    validate_model_request(request)

    assert request.model == "random_forest"
    assert request.hyperparameters == {
        "n_estimators": 500,
        "max_depth": 8,
        "test_size": 0.2,
    }


def test_un_parametre_caracteristique_deduit_le_modele():
    request = parse_model_request("Entraîne un modèle avec n_estimators=250")
    validate_model_request(request)

    assert request.model == "random_forest"
    assert request.hyperparameters["n_estimators"] == 250


def test_les_parametres_de_split_sappliquent_sans_modele_impose():
    request = parse_model_request("Entraîne le meilleur modèle avec test_size=30% et random_state=9")
    validate_model_request(request)

    assert request.model is None
    assert request.hyperparameters == {"test_size": 0.3, "random_state": 9}


def test_un_parametre_ambigu_nest_pas_ignore():
    request = parse_model_request("Entraîne un modèle avec max_depth=6")

    with pytest.raises(ValueError, match="Indiquez explicitement le modèle"):
        validate_model_request(request)


def test_un_modele_indisponible_nest_pas_remplace_silencieusement():
    request = parse_model_request("Entraîne un modèle XGBoost avec max_depth=6")

    with pytest.raises(ValueError, match="n'est pas disponible"):
        validate_model_request(request)


def test_un_parametre_inconnu_nest_pas_ignore_silencieusement():
    request = parse_model_request("Entraîne un Random Forest avec foo_bar=12")

    with pytest.raises(ValueError, match="foo_bar"):
        validate_model_request(request)


def test_le_code_genere_ne_contient_quun_modele_et_les_valeurs_imposees():
    code = build_supervised_code(
        "cible",
        ["x1", "x2"],
        requested_model="random_forest",
        hyperparameters={"n_estimators": 17, "max_depth": 3},
        test_size=0.2,
        random_state=7,
    )

    compile(code, "<entrainement-strict>", "exec")
    assert "REQUESTED_MODEL = 'random_forest'" in code
    assert "HYPERPARAMS = {'n_estimators': 17, 'max_depth': 3}" in code
    assert "TEST_SIZE = 0.2" in code
    assert "RANDOM_STATE = 7" in code
