"""La lecture d'images doit passer par le fournisseur CHOISI par l'utilisateur.

Avant, `ask_gemini_vision` codait Gemini en dur : sélectionner Ollama en local
n'empêchait pas les pages d'un document scanné de partir chez Google. Un refus
explicite vaut mieux qu'un contournement silencieux de ce choix.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.vision_service as vision
from app.services.vision_service import VisionNonSupportee, ask_vision, supporte_vision

_IMG = [b"\x89PNG_fake"]


class TestCapaciteVision:
    @pytest.mark.parametrize("model", [
        "gemini-3.1-flash-lite-preview",
        "openai/gpt-4o", "openai/gpt-4.1",
        "anthropic/claude-sonnet-4-5", "anthropic/claude-3-5-haiku-latest",
        "llava:13b", "llama3.2-vision", "qwen2.5-vl:7b",
    ])
    def test_modeles_multimodaux(self, model):
        assert supporte_vision(model)

    @pytest.mark.parametrize("model", [
        "openai/o3-mini",
        "mistral/mistral-large-latest", "mistral/mistral-small-latest",
        "groq/llama-3.3-70b-versatile", "groq/mixtral-8x7b-32768",
        "gemma2:latest", "qwen3.5:0.8b", "mistral:7b",
        None, "",
    ])
    def test_modeles_sans_vision(self, model):
        assert not supporte_vision(model)

    def test_mistral_small_latest_nest_pas_la_3x_multimodale(self):
        """Piège de nommage : `mistral-small-3` a la vision, pas `-latest`."""
        assert not supporte_vision("mistral/mistral-small-latest")
        assert supporte_vision("mistral/mistral-small-3.2")


class TestRoutage:
    def test_refuse_un_modele_sans_vision(self):
        with pytest.raises(VisionNonSupportee) as exc:
            ask_vision("Résume", _IMG, model="gemma2:latest")
        # Le message doit être exploitable par l'utilisateur, pas un code d'erreur.
        assert "gemma2:latest" in str(exc.value)
        assert "multimodal" in str(exc.value)

    def test_ne_bascule_jamais_sur_gemini(self, monkeypatch):
        """Le cœur de la correction : aucun repli silencieux vers un autre
        fournisseur que celui choisi."""
        appels = []
        monkeypatch.setattr(vision, "_vision_ollama",
                            lambda *a, **k: appels.append("ollama") or "ok")
        import app.services.gemini_service as gs
        monkeypatch.setattr(gs, "ask_gemini_vision",
                            lambda *a, **k: appels.append("gemini") or "ok")

        # Modèle sans vision : on refuse, sans appeler personne.
        with pytest.raises(VisionNonSupportee):
            ask_vision("Résume", _IMG, model="groq/llama-3.3-70b-versatile")
        assert appels == []

        # Modèle Ollama multimodal : c'est Ollama qui répond, pas Gemini.
        assert ask_vision("Résume", _IMG, model="llava:13b") == "ok"
        assert appels == ["ollama"]

    def test_route_vers_anthropic(self, monkeypatch):
        vu = {}

        def faux(prompt, images, model, history):
            vu["model"] = model
            return "réponse claude"

        monkeypatch.setattr(vision, "_vision_anthropic", faux)
        assert ask_vision("Q", _IMG, model="anthropic/claude-sonnet-4-5") == "réponse claude"
        # Le préfixe fournisseur ne doit pas fuiter dans le nom envoyé à l'API.
        assert vu["model"] == "claude-sonnet-4-5"

    def test_route_vers_openai_avec_le_bon_fournisseur(self, monkeypatch):
        vu = {}

        def faux(prompt, images, model, history, provider):
            vu.update(model=model, provider=provider)
            return "réponse gpt"

        monkeypatch.setattr(vision, "_vision_openai_compatible", faux)
        assert ask_vision("Q", _IMG, model="openai/gpt-4o") == "réponse gpt"
        assert vu == {"model": "gpt-4o", "provider": "openai"}

    def test_refuse_sans_image(self):
        with pytest.raises(ValueError):
            ask_vision("Q", [], model="gemini-3.1-flash-lite-preview")


class TestBrancheChatDocumentVisual:
    """Exécute réellement la branche `document_visual` du chat.

    Un simple import ne l'aurait pas couverte : la première version de ce code
    référençait un `model` inexistant dans `_run_chat` (le reste de la fonction
    utilise `request.model`), soit un NameError à chaque question sur un scan.
    """

    @staticmethod
    def _preparer(monkeypatch, modele):
        import app.api.chat as chat
        import app.services.colsmolvlm_service as colsmol

        monkeypatch.setattr(chat, "get_session", lambda sid: {"id": sid})
        monkeypatch.setattr(chat, "get_session_type", lambda sid: "document_visual")
        monkeypatch.setattr(chat, "get_history", lambda sid: [])
        monkeypatch.setattr(chat, "add_to_history", lambda *a, **k: None)
        monkeypatch.setattr(chat, "save_message_to_report", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(colsmol, "retrieve_visual_pages",
                            lambda sid, q: [{"page": 1, "image_bytes": b"png"}])
        return chat.ChatRequest(session_id="s1", message="De quoi parle ce document ?",
                                model=modele)

    async def _collecter(self, chat, request):
        return [ev async for ev in chat._run_chat(request)]

    def test_modele_vision_lit_les_pages(self, monkeypatch):
        import asyncio

        import app.api.chat as chat
        req = self._preparer(monkeypatch, "llava:13b")
        monkeypatch.setattr(vision, "_vision_ollama", lambda *a, **k: "Le document traite de X.")

        events = asyncio.run(self._collecter(chat, req))
        final = [e for e in events if e.get("type") == "result"][-1]
        assert "Le document traite de X." in final["response"]

    def test_modele_sans_vision_explique_au_lieu_de_planter(self, monkeypatch):
        import asyncio

        import app.api.chat as chat
        req = self._preparer(monkeypatch, "gemma2:latest")

        events = asyncio.run(self._collecter(chat, req))
        final = [e for e in events if e.get("type") == "result"][-1]
        assert "gemma2:latest" in final["response"]
        assert "multimodal" in final["response"]
