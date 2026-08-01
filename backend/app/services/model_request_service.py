"""Extraction déterministe des contraintes ML écrites dans le chat.

Le LLM peut aider à comprendre l'intention, mais il ne doit jamais être la source
de vérité lorsqu'un utilisateur impose un estimateur ou des hyperparamètres.
"""

from dataclasses import dataclass, field
import re
import unicodedata


@dataclass
class ModelRequest:
    model: str | None = None
    hyperparameters: dict = field(default_factory=dict)
    unsupported_parameters: list[str] = field(default_factory=list)


MODEL_ALIASES = {
    "random_forest": (
        "random forest", "randomforest", "forêt aléatoire", "foret aleatoire",
        "random forest classifier", "random forest regressor",
        "randomforestclassifier", "randomforestregressor",
    ),
    "balanced_random_forest": ("balanced random forest", "forêt aléatoire équilibrée"),
    "gradient_boosting": (
        "gradient boosting", "hist gradient boosting", "histgradientboosting",
        "histgradientboostingclassifier", "histgradientboostingregressor",
    ),
    "elasticnet": ("elasticnet", "elastic net", "elasticnetcv"),
    "logistique": (
        "régression logistique", "regression logistique", "logistic regression",
        "logisticregression",
    ),
    "ols": (
        "régression linéaire", "regression lineaire", "linear regression",
        "linearregression", "ols",
    ),
}

UNSUPPORTED_MODEL_ALIASES = {
    "xgboost": ("xgboost", "xgbclassifier", "xgbregressor"),
    "lightgbm": ("lightgbm", "lgbmclassifier", "lgbmregressor"),
    "catboost": ("catboost",),
    "svm": ("support vector machine", "support vector classifier", "svm", "svc", "svr"),
    "knn": ("k-nearest neighbors", "k nearest neighbors", "knn"),
    "decision_tree": ("decision tree", "arbre de décision", "arbre de decision"),
}

PARAMETER_ALIASES = {
    "n_estimators": ("n_estimators", "nombre_arbre", "nombre_arbres"),
    "max_depth": ("max_depth", "profondeur_max", "profondeur_maximale"),
    "min_samples_split": ("min_samples_split",),
    "min_samples_leaf": ("min_samples_leaf",),
    "max_features": ("max_features",),
    "bootstrap": ("bootstrap",),
    "class_weight": ("class_weight",),
    "learning_rate": ("learning_rate", "taux_apprentissage"),
    "max_iter": ("max_iter", "iterations", "nombre_iterations"),
    "max_leaf_nodes": ("max_leaf_nodes",),
    "l2_regularization": ("l2_regularization",),
    "l1_ratio": ("l1_ratio",),
    "cv": ("cv",),
    "C": ("c",),
    "solver": ("solver",),
    "penalty": ("penalty",),
    "test_size": ("test_size", "taille_test"),
    "random_state": ("random_state", "seed", "graine"),
}

MODEL_ALLOWED_PARAMETERS = {
    "random_forest": {
        "n_estimators", "max_depth", "min_samples_split", "min_samples_leaf",
        "max_features", "bootstrap", "class_weight", "random_state",
    },
    "balanced_random_forest": {
        "n_estimators", "max_depth", "min_samples_split", "min_samples_leaf",
        "max_features", "bootstrap", "class_weight", "random_state",
    },
    "gradient_boosting": {
        "learning_rate", "max_iter", "max_leaf_nodes", "max_depth",
        "min_samples_leaf", "l2_regularization", "random_state",
    },
    "elasticnet": {"l1_ratio", "cv", "max_iter", "random_state"},
    "logistique": {"C", "max_iter", "solver", "penalty", "class_weight", "random_state"},
    "ols": set(),
}
PIPELINE_PARAMETERS = {"test_size", "random_state"}


def _normaliser(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_normaliser(alias))}(?!\w)", text) is not None


def _parse_value(raw: str):
    value = raw.strip().strip("'\"")
    lowered = value.lower()
    if lowered in {"true", "vrai", "oui"}:
        return True
    if lowered in {"false", "faux", "non"}:
        return False
    if lowered in {"none", "null", "aucun"}:
        return None
    try:
        return float(value.replace(",", ".")) if any(c in value for c in ".,") else int(value)
    except ValueError:
        return value


def parse_model_request(question: str) -> ModelRequest:
    normalized = _normaliser(question)
    selected = None
    matches = [
        (len(_normaliser(alias)), key)
        for key, aliases in MODEL_ALIASES.items()
        for alias in aliases
        if _contains_alias(normalized, alias)
    ]
    if matches:
        selected = max(matches)[1]
    else:
        unsupported_matches = [
            (len(_normaliser(alias)), key)
            for key, aliases in UNSUPPORTED_MODEL_ALIASES.items()
            for alias in aliases
            if _contains_alias(normalized, alias)
        ]
        if unsupported_matches:
            selected = max(unsupported_matches)[1]

    parameters = {}
    for canonical, aliases in PARAMETER_ALIASES.items():
        for alias in aliases:
            pattern = rf"(?<!\w){re.escape(_normaliser(alias))}(?!\w)\s*(?:=|:|de)?\s*([\w.,À-ÿ%+-]+)"
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                raw = match.group(1).rstrip(".,;")
                value = _parse_value(raw.rstrip("%"))
                if raw.endswith("%") and isinstance(value, (int, float)):
                    value /= 100
                parameters[canonical] = value
                break

    natural_patterns = (
        ("n_estimators", r"(\d+)\s*(?:arbres?|trees?)"),
        ("max_depth", r"profondeur(?:\s+maximale|\s+max)?\s*(?:de|=|:)?\s*(\d+)"),
        ("test_size", r"(?:jeu|taille|part)\s+(?:de\s+)?test\s*(?:de|=|:)?\s*(\d+(?:[.,]\d+)?)\s*%"),
    )
    for name, pattern in natural_patterns:
        if name not in parameters and (match := re.search(pattern, normalized)):
            value = _parse_value(match.group(1))
            parameters[name] = value / 100 if name == "test_size" else value

    if selected is None:
        inference = {
            "random_forest": {"n_estimators", "max_features", "bootstrap", "min_samples_split"},
            "logistique": {"C", "solver", "penalty"},
            "elasticnet": {"l1_ratio"},
            "gradient_boosting": {"learning_rate", "max_leaf_nodes", "l2_regularization"},
        }
        candidates = [model for model, distinctive in inference.items() if distinctive & parameters.keys()]
        if len(candidates) == 1:
            selected = candidates[0]

    known_aliases = {
        _normaliser(alias)
        for aliases in PARAMETER_ALIASES.values()
        for alias in aliases
    }
    explicit_keys = {
        _normaliser(match.group(1))
        for match in re.finditer(r"(?<!\w)([A-Za-z_][A-Za-z0-9_]*)\s*=", normalized)
    }
    unsupported = sorted(explicit_keys - known_aliases)

    return ModelRequest(
        model=selected,
        hyperparameters=parameters,
        unsupported_parameters=unsupported,
    )


def validate_model_request(request: ModelRequest) -> None:
    if request.unsupported_parameters:
        raise ValueError(
            "Paramètre(s) inconnu(s) ou non pris en charge : "
            + ", ".join(request.unsupported_parameters)
            + ". Aucun de ces paramètres ne sera ignoré silencieusement."
        )
    if request.model is None and set(request.hyperparameters) <= PIPELINE_PARAMETERS:
        test_size = request.hyperparameters.get("test_size", 0.25)
        if not isinstance(test_size, (int, float)) or not 0.05 <= test_size <= 0.5:
            raise ValueError("test_size doit être compris entre 0,05 et 0,50.")
        return
    if request.model is None and request.hyperparameters:
        raise ValueError(
            "Des hyperparamètres ont été précisés sans modèle. Indiquez explicitement "
            "le modèle à entraîner pour qu'ils puissent être appliqués strictement."
        )
    if request.model is None:
        return
    if request.model not in MODEL_ALLOWED_PARAMETERS:
        raise ValueError(
            f"Le modèle demandé « {request.model} » n'est pas disponible dans le moteur "
            "supervisé strict. Aucun autre modèle ne sera entraîné à sa place."
        )
    allowed = MODEL_ALLOWED_PARAMETERS[request.model] | PIPELINE_PARAMETERS
    unsupported = sorted(set(request.hyperparameters) - allowed)
    if unsupported:
        raise ValueError(
            f"Paramètre(s) non compatible(s) avec {request.model} : {', '.join(unsupported)}."
        )
    test_size = request.hyperparameters.get("test_size", 0.25)
    if not isinstance(test_size, (int, float)) or not 0.05 <= test_size <= 0.5:
        raise ValueError("test_size doit être compris entre 0,05 et 0,50.")
    for name in ("n_estimators", "max_iter", "min_samples_split", "min_samples_leaf", "cv"):
        value = request.hyperparameters.get(name)
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ValueError(f"{name} doit être un entier strictement positif.")
    depth = request.hyperparameters.get("max_depth")
    if depth is not None and (not isinstance(depth, int) or depth <= 0):
        raise ValueError("max_depth doit être un entier positif ou null.")
