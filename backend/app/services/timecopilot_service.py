"""timecopilot_service.py — Pont vers le vrai TimeCopilot, exécuté hors venv.

TimeCopilot est un *agent* de prévision : il calcule des caractéristiques de série
(tsfeatures), fait raisonner un LLM dessus pour choisir un modèle parmi un pool
(statistiques + modèles de fondation Chronos/TimesFM/Moirai/TimeGPT), le compare à
la baseline SeasonalNaive par cross-validation, puis explique ses décisions et
répond à la question posée en langage naturel.

Il vit dans son propre venv `.venv-timecopilot`, appelé en sous-processus : il
porte un jeu de dépendances épinglées (dont `openai>=1.99.7`) qui lui est propre.
Le conflit qui rendait la cohabitation strictement impossible venait de
`pandasai` (`openai<0.28`), retiré du projet depuis ; l'isolation est conservée,
la compatibilité des deux environnements n'ayant pas été revérifiée.

L'agent a besoin du réseau (API du LLM, poids HuggingFace) : il tourne sur l'hôte,
pas dans le sandbox Docker — ce qui est cohérent, le sandbox existant pour confiner
du code *généré*, pas une bibliothèque de confiance.

Sa configuration de fournisseur (clés d'API, URL d'Ollama) voyage dans le payload
JSON, pas dans l'environnement du sous-processus : voir `_environnement_fournisseur`.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.core import config

logger = logging.getLogger("app.timecopilot")

_BACKEND_DIR = Path(__file__).resolve().parents[2]
VENV_PYTHON = Path(os.getenv(
    "TIMECOPILOT_PYTHON",
    _BACKEND_DIR / ".venv-timecopilot" / "bin" / "python",
))
RUNNER = Path(__file__).resolve().parent / "timecopilot_runner.py"
# Un forecast agentique enchaîne plusieurs appels LLM et une cross-validation :
# quelques minutes sont normales, surtout au premier usage (poids à télécharger).
TIMEOUT = int(os.getenv("TIMECOPILOT_TIMEOUT", "900"))


class TimeCopilotIndisponible(Exception):
    """Le venv dédié est absent, ou le modèle choisi ne convient pas.

    Porte un message destiné à l'utilisateur, remonté tel quel dans le chat.
    """


# TimeCopilot délègue à pydantic-ai, qui nomme les modèles « fournisseur:modèle ».
# L'application, elle, utilise « fournisseur/modèle » (et un nom nu pour Ollama).
#
# Les noms ci-dessous sont ceux de `pydantic_ai.providers.infer_provider_class`.
# Attention : Gemini s'y appelle « google » — l'ancien « google-gla » a disparu et
# provoque « ValueError: Unknown provider: google-gla ».
_PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "mistral": "mistral",
    "groq": "groq",
    "gemini": "google",
}
PROVIDER_GEMINI = "google"


def traduire_modele(model: str | None) -> str:
    """Convertit un identifiant applicatif en identifiant pydantic-ai.

    « openai/gpt-4o » → « openai:gpt-4o » ; « gemini-3.1-… » → « google:… » ;
    un nom nu est un modèle Ollama, servi par pydantic-ai via son provider
    « ollama ».
    """
    nom = (model or config.get_default_model()).strip()
    if "/" in nom:
        fournisseur, reste = nom.split("/", 1)
        return f"{_PROVIDERS.get(fournisseur, fournisseur)}:{reste}"
    if nom.startswith("gemini"):
        return f"{PROVIDER_GEMINI}:{nom}"
    return f"ollama:{nom}"


# Le README de TimeCopilot est explicite : « models need support for tool use to
# function properly ». Un modèle sans tool-use produit une boucle d'agent qui
# échoue après plusieurs minutes — autant le dire tout de suite.
_SANS_TOOL_USE = (
    "gemma", "gemma2", "gemma3", "phi", "tinyllama", "orca-mini",
    "stablelm", "deepseek-r1", "qwen3.5:0.8b",
)


def supporte_tool_use(model: str | None) -> bool:
    nom = (model or "").split("/", 1)[-1].strip().lower()
    if not nom:
        return False
    if "/" in (model or "") or nom.startswith("gemini"):
        # Fournisseurs API : tous leurs modèles conversationnels gèrent le tool-use.
        return True
    return not any(nom.startswith(x) for x in _SANS_TOOL_USE)


def message_refus_tool_use(model: str) -> str:
    return (
        f"Le moteur **TimeCopilot** pilote sa prévision via des appels d'outils "
        f"(*tool use*), que le modèle sélectionné (**{model}**) ne prend pas en "
        f"charge.\n\n"
        f"Deux options :\n"
        f"- choisir un modèle qui gère le tool-use (Gemini, GPT-4o, Claude, "
        f"Mistral, ou un modèle Ollama récent comme `qwen2.5` / `llama3.1`) ;\n"
        f"- utiliser le moteur **ARIMA/SARIMA rigoureux**, qui n'a besoin "
        f"d'aucun appel d'outil."
    )


def disponible() -> bool:
    """Le venv dédié est-il installé ?"""
    return VENV_PYTHON.exists() and RUNNER.exists()


def message_venv_absent() -> str:
    return (
        "Le moteur **TimeCopilot** n'est pas installé sur ce serveur. Il vit dans "
        "un environnement Python dédié, car ses dépendances sont incompatibles "
        "avec celles du backend.\n\n"
        "Pour l'installer :\n"
        "```bash\n"
        "cd backend\n"
        "python3.11 -m venv .venv-timecopilot\n"
        "./.venv-timecopilot/bin/pip install -r requirements-timecopilot.txt\n"
        "```\n"
        "En attendant, le moteur **ARIMA/SARIMA rigoureux** reste disponible."
    )


def url_ollama_pydantic_ai() -> str:
    """URL d'Ollama au format attendu par pydantic-ai.

    Deux conventions coexistent et ne se croisent jamais :
      - le backend lit `OLLAMA_API_URL`, qui pointe l'API native
        (« …:11434/api/generate ») ;
      - pydantic-ai lit `OLLAMA_BASE_URL`, qui pointe l'endpoint
        OpenAI-compatible et doit se terminer par « /v1 ».

    Sans cette traduction, un Ollama servi ailleurs que sur localhost:11434 était
    suivi par tout le backend SAUF TimeCopilot, qui continuait d'interroger
    localhost et échouait sans que rien n'explique pourquoi.
    """
    from app.services.ollama_service import _base_url

    return f"{_base_url()}/v1"


def _environnement_fournisseur() -> dict:
    """Variables que pydantic-ai lira pour joindre le fournisseur choisi.

    Transmises DANS le payload plutôt que par l'environnement du sous-processus :
    c'est le seul canal qui survivra au passage en conteneur, où des clés posées
    en `-e` seraient lisibles dans `docker inspect` et dans la table des
    processus de l'hôte. Le runner les repose lui-même avant d'importer l'agent.
    """
    variables = {"OLLAMA_BASE_URL": url_ollama_pydantic_ai()}
    for fournisseur, var in (
        ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"), ("groq", "GROQ_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
    ):
        cle = config.get_api_key(fournisseur)
        if cle:
            variables[var] = cle
            if fournisseur == "gemini":
                # pydantic-ai attend GOOGLE_API_KEY pour le provider google.
                variables["GOOGLE_API_KEY"] = cle
    return variables


def lancer_forecast(
    csv_text: str,
    date_col: str,
    value_col: str,
    question: str = "",
    model: str | None = None,
    freq: str | None = None,
    horizon: int | None = None,
) -> dict:
    """Exécute TimeCopilot dans son venv et renvoie sa sortie structurée.

    Returns:
        { ok, result, fcst, error } — `result` porte le contrat TimeCopilot
        (tsfeatures_analysis, selected_model, cross_validation_results,
        is_better_than_seasonal_naive, reason_for_selection, forecast_analysis,
        user_query_response…).

    Raises:
        TimeCopilotIndisponible: venv manquant ou modèle sans tool-use. À présenter
            à l'utilisateur, sans basculer en douce sur un autre moteur.
    """
    modele_app = model or config.get_default_model()
    if not disponible():
        raise TimeCopilotIndisponible(message_venv_absent())
    if not supporte_tool_use(modele_app):
        raise TimeCopilotIndisponible(message_refus_tool_use(modele_app))

    payload = json.dumps({
        "csv": csv_text,
        "date_col": date_col,
        "value_col": value_col,
        "query": question,
        "llm": traduire_modele(modele_app),
        "freq": freq,
        "h": horizon,
        "env": _environnement_fournisseur(),
    }, ensure_ascii=False)

    logger.info("TimeCopilot : %s → %s", modele_app, traduire_modele(modele_app))
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), str(RUNNER)],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=TIMEOUT,
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": None, "fcst": [], "error": {
            "simple": f"TimeCopilot a dépassé {TIMEOUT} s — opération annulée.",
            "technical": "TimeoutExpired",
        }}
    except Exception as exc:
        return {"ok": False, "result": None, "fcst": [], "error": {
            "simple": "Impossible de lancer le moteur TimeCopilot.",
            "technical": f"{type(exc).__name__}: {exc}",
        }}

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    # Les bibliothèques du venv écrivent volontiers sur stdout (barres de
    # progression, avertissements) : on ne garde que la dernière ligne, seule à
    # porter le JSON du runner.
    ligne_json = next((l for l in reversed(stdout.splitlines()) if l.startswith("{")), "")
    if not ligne_json:
        return {"ok": False, "result": None, "fcst": [], "error": {
            "simple": "Réponse inattendue du moteur TimeCopilot.",
            "technical": f"stdout:\n{stdout[-2000:]}\nstderr:\n{stderr[-2000:]}",
        }}
    try:
        return json.loads(ligne_json)
    except json.JSONDecodeError as exc:
        return {"ok": False, "result": None, "fcst": [], "error": {
            "simple": "Réponse illisible du moteur TimeCopilot.",
            "technical": f"{exc}\n{ligne_json[:2000]}",
        }}
