"""TimeCopilot vit dans un venv dédié, appelé en sous-processus.

Il porte ses propres dépendances épinglées (dont `openai>=1.99`), historiquement
inconciliables avec `pandasai` (`openai<0.28`, depuis retiré du projet). Ces
tests verrouillent la frontière entre les deux environnements.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.timecopilot_service as tc
from app.services.timecopilot_service import (
    TimeCopilotIndisponible, lancer_forecast, supporte_tool_use, traduire_modele,
    url_ollama_pydantic_ai,
)


class TestTraductionModele:
    """TimeCopilot passe par pydantic-ai, qui nomme « fournisseur:modèle » là où
    l'application utilise « fournisseur/modèle »."""

    @pytest.mark.parametrize("app_id,attendu", [
        ("openai/gpt-4o", "openai:gpt-4o"),
        ("anthropic/claude-sonnet-4-5", "anthropic:claude-sonnet-4-5"),
        ("mistral/mistral-large-latest", "mistral:mistral-large-latest"),
        ("groq/llama-3.3-70b-versatile", "groq:llama-3.3-70b-versatile"),
        # Gemini s'appelle « google » chez pydantic-ai : « google-gla » a disparu
        # et lève « Unknown provider ».
        ("gemini-3.1-flash-lite-preview", "google:gemini-3.1-flash-lite-preview"),
        # Nom nu = modèle Ollama local.
        ("qwen2.5:7b", "ollama:qwen2.5:7b"),
    ])
    def test_conversion(self, app_id, attendu):
        assert traduire_modele(app_id) == attendu


class TestUrlOllama:
    """Deux conventions coexistent et ne se croisent pas : le backend lit
    `OLLAMA_API_URL` (API native), pydantic-ai lit `OLLAMA_BASE_URL` (endpoint
    OpenAI-compatible, terminé par « /v1 »). Sans traduction, un Ollama servi
    ailleurs que sur localhost était suivi partout SAUF par TimeCopilot."""

    @pytest.mark.parametrize("api_url,attendu", [
        (None, "http://localhost:11434/v1"),
        ("http://localhost:11434/api/generate", "http://localhost:11434/v1"),
        ("http://192.168.1.42:11434/api/generate", "http://192.168.1.42:11434/v1"),
        ("http://ollama.interne:8080/api/chat", "http://ollama.interne:8080/v1"),
    ])
    def test_traduit_vers_l_endpoint_openai(self, monkeypatch, api_url, attendu):
        import importlib
        import app.services.ollama_service as ollama

        if api_url is None:
            monkeypatch.delenv("OLLAMA_API_URL", raising=False)
        else:
            monkeypatch.setenv("OLLAMA_API_URL", api_url)
        importlib.reload(ollama)
        try:
            assert url_ollama_pydantic_ai() == attendu
        finally:
            monkeypatch.delenv("OLLAMA_API_URL", raising=False)
            importlib.reload(ollama)

    def test_l_url_ollama_accompagne_toujours_le_payload(self, monkeypatch):
        """Même sans clé d'API configurée : c'est la seule façon pour l'agent de
        joindre un Ollama qui n'est pas sur localhost."""
        monkeypatch.setattr(tc.config, "get_api_key", lambda _f: None)
        assert "OLLAMA_BASE_URL" in tc._environnement_fournisseur()

    def test_gemini_est_double_en_google_api_key(self, monkeypatch):
        monkeypatch.setattr(
            tc.config, "get_api_key",
            lambda f: "cle-gemini" if f == "gemini" else None,
        )
        env = tc._environnement_fournisseur()
        assert env["GEMINI_API_KEY"] == "cle-gemini"
        assert env["GOOGLE_API_KEY"] == "cle-gemini"


class TestToolUse:
    """Le README de TimeCopilot est explicite : sans tool-use, la boucle d'agent
    échoue — autant refuser tout de suite plutôt qu'après plusieurs minutes."""

    @pytest.mark.parametrize("model", [
        "openai/gpt-4o", "anthropic/claude-sonnet-4-5",
        "gemini-3.1-flash-lite-preview", "qwen2.5:7b", "llama3.1:8b",
    ])
    def test_modeles_compatibles(self, model):
        assert supporte_tool_use(model)

    @pytest.mark.parametrize("model", [
        "gemma2:latest", "gemma3:4b", "phi3:mini", "tinyllama:latest", None, "",
    ])
    def test_modeles_incompatibles(self, model):
        assert not supporte_tool_use(model)


class TestRefusExplicite:
    """Aucun repli silencieux : l'utilisateur a choisi TimeCopilot, on lui dit
    pourquoi ça ne marche pas plutôt que de basculer sur un autre moteur."""

    def test_refuse_un_modele_sans_tool_use(self, monkeypatch):
        monkeypatch.setattr(tc, "disponible", lambda: True)
        with pytest.raises(TimeCopilotIndisponible) as exc:
            lancer_forecast("ds,y\n2020-01-01,1\n", "ds", "y", model="gemma2:latest")
        assert "gemma2:latest" in str(exc.value)
        assert "tool use" in str(exc.value).lower()

    def test_explique_comment_installer_si_venv_absent(self, monkeypatch):
        monkeypatch.setattr(tc, "disponible", lambda: False)
        with pytest.raises(TimeCopilotIndisponible) as exc:
            lancer_forecast("ds,y\n2020-01-01,1\n", "ds", "y", model="openai/gpt-4o")
        message = str(exc.value)
        # Le message doit être actionnable, pas un simple code d'erreur.
        assert "requirements-timecopilot.txt" in message
        assert "ARIMA/SARIMA" in message  # l'alternative disponible

    def test_venv_absent_verifie_avant_tool_use(self, monkeypatch):
        """L'ordre compte : inutile de reprocher son modèle à quelqu'un dont le
        moteur n'est même pas installé."""
        monkeypatch.setattr(tc, "disponible", lambda: False)
        with pytest.raises(TimeCopilotIndisponible) as exc:
            lancer_forecast("ds,y\n2020-01-01,1\n", "ds", "y", model="gemma2:latest")
        assert "requirements-timecopilot.txt" in str(exc.value)


class TestSortieSousProcessus:
    def test_ignore_le_bruit_avant_le_json(self, monkeypatch):
        """Les bibliothèques du venv polluent stdout (barres de progression,
        avertissements) : seule la dernière ligne JSON compte."""
        import subprocess

        class FauxProc:
            stdout = (b"Downloading weights: 100%|####| 200M/200M\n"
                      b"FutureWarning: deprecated\n"
                      b'{"ok": true, "result": {"selected_model": "AutoARIMA"}, '
                      b'"fcst": [], "error": null}\n')
            stderr = b""

        monkeypatch.setattr(tc, "disponible", lambda: True)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FauxProc())
        out = lancer_forecast("ds,y\n2020-01-01,1\n", "ds", "y", model="openai/gpt-4o")
        assert out["ok"] is True
        assert out["result"]["selected_model"] == "AutoARIMA"

    def test_sortie_sans_json_remonte_une_erreur_lisible(self, monkeypatch):
        import subprocess

        class FauxProc:
            stdout = b"Traceback (most recent call last):\nImportError: no module\n"
            stderr = b"boom"

        monkeypatch.setattr(tc, "disponible", lambda: True)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FauxProc())
        out = lancer_forecast("ds,y\n2020-01-01,1\n", "ds", "y", model="openai/gpt-4o")
        assert out["ok"] is False
        assert "inattendue" in out["error"]["simple"]


class TestRapportDashboard:
    """Le rapport doit porter le vocabulaire de TimeCopilot, pas le diluer."""

    def test_mappe_le_contrat_complet(self):
        from app.services.timeseries_pipeline import _rapport_timecopilot

        sortie = {
            "selected_model": "AutoARIMA",
            "tsfeatures_results": ["trend: 1.00", "seasonal_strength: 0.98"],
            "tsfeatures_analysis": "Forte saisonnalité annuelle.",
            "cross_validation_results": ["AutoARIMA: 1.82", "SeasonalNaive: 4.03"],
            "model_comparison": "AutoARIMA domine.",
            "is_better_than_seasonal_naive": True,
            "reason_for_selection": "Meilleur score de cross-validation.",
            "forecast_analysis": "Tendance haussière.",
            "user_query_response": "Environ 5 919 passagers.",
        }
        fcst = [{"date": "1961-01-01", "valeur_prevue": 445.0, "ic_bas": 420.0, "ic_haut": 470.0}]
        rapport = _rapport_timecopilot(sortie, fcst, [{"date": "1960-12-01", "valeur": 432.0}])

        assert rapport["modele_retenu"]["type"] == "AutoARIMA"
        assert rapport["user_query_response"] == "Environ 5 919 passagers."
        assert rapport["cross_validation_results"] == ["AutoARIMA: 1.82", "SeasonalNaive: 4.03"]
        # Le tableau téléchargeable du dashboard lit `prevision`.
        assert rapport["prevision"] == fcst
        assert rapport["avertissements"] == []
        # Ne pas prétendre avoir calculé les GATE de la méthodologie SARIMA.
        assert rapport["gate_1_diagnostics_residus"]["statut"] == "NON_CALCULE"

    def test_avertit_si_le_modele_ne_bat_pas_la_baseline(self):
        """Signal décisionnel : une prévision qui ne bat pas SeasonalNaive
        n'apporte rien, l'utilisateur doit le voir."""
        from app.services.timeseries_pipeline import _rapport_timecopilot

        rapport = _rapport_timecopilot({"is_better_than_seasonal_naive": False}, [], [])
        assert len(rapport["avertissements"]) == 1
        assert "SeasonalNaive" in rapport["avertissements"][0]

class TestContratReel_0_0_28:
    """La 0.0.28 installée ne renvoie pas le même contrat que le README.

    Vérifié en exécutant réellement l'agent : `output` ne contient ni
    `tsfeatures_results` ni `cross_validation_results` (le README décrit une
    version antérieure) — ils vivent dans `features_df` / `eval_df` —, il ajoute
    `anomaly_analysis`, et `fcst_df` ne porte aucun intervalle.
    """

    def test_anomaly_analysis_est_conserve(self):
        from app.services.timeseries_pipeline import _rapport_timecopilot

        r = _rapport_timecopilot({"anomaly_analysis": "13 anomalies détectées."}, [], [])
        assert r["anomaly_analysis"] == "13 anomalies détectées."

    def test_metrique_de_comparaison_conservee(self):
        """Sans elle, les scores du dashboard sont des nombres sans unité."""
        from app.services.timeseries_pipeline import _rapport_timecopilot

        r = _rapport_timecopilot(
            {"cross_validation_results": ["AutoARIMA: 0.6081"], "cross_validation_metric": "mase"},
            [], [],
        )
        assert r["cross_validation_metric"] == "mase"

    def test_champs_absents_ne_cassent_rien(self):
        """Un rapport minimal doit rester exploitable par le dashboard."""
        from app.services.timeseries_pipeline import _rapport_timecopilot

        r = _rapport_timecopilot({}, [], [])
        assert r["tsfeatures_results"] == []
        assert r["cross_validation_results"] == []
        assert r["statut_final"] == "INFO_TIMECOPILOT"


class TestIntervallesRecalcules:
    """TimeCopilot ne renvoie que la prévision ponctuelle ; le tableau du
    dashboard exige un intervalle à 95 %. On réajuste donc le modèle retenu, mais
    seulement si le point recalculé coïncide — sinon l'intervalle décrirait une
    autre prévision."""

    @staticmethod
    def _runner():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tc_runner",
            Path(__file__).resolve().parents[1] / "app/services/timecopilot_runner.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_modele_non_reimplementable_ne_produit_aucun_intervalle(self):
        runner = self._runner()
        # Prophet et les modèles de fondation ne sont pas dans la table.
        assert runner._intervalles(None, "Prophet", 12, "MS", 12, [1.0]) is None
        assert runner._intervalles(None, "Chronos", 12, "MS", 12, [1.0]) is None
        assert runner._intervalles(None, "", 12, "MS", 12, [1.0]) is None
