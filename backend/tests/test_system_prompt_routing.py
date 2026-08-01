"""Le prompt système doit arriver dans l'emplacement DÉDIÉ de chaque fournisseur.

Avant, `ask_gemini` concaténait le prompt système en tête du tour utilisateur et
`complete_text` ne transmettait jamais le paramètre `system` — pourtant déjà
accepté par les adaptateurs Anthropic et OpenAI-compatible. Conséquences
mesurables : les consignes se présentaient au modèle comme un texte à commenter
au même titre que les données, et chez Ollama elles pouvaient tomber dans la
zone amputée par `_trim_prompt`, disparaissant sans trace.

Chaque test vérifie les DEUX moitiés de la correction : la consigne est bien dans
son champ, et elle n'est PLUS dans le tour utilisateur.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.gemini_service as gs
import app.services.ollama_service as ollama_service

_SYSTEME = "CONSIGNE-SYSTEME-SENTINELLE"


# ── Faux client Gemini ───────────────────────────────────────────────────────
# Reproduit la surface réellement utilisée du SDK google-genai : `chats.create`
# accepte `config` (où vit `system_instruction`) et le conserve pour les envois
# suivants — comportement vérifié dans la source du SDK.

class _FauxChat:
    def __init__(self, journal):
        self._journal = journal

    def send_message(self, message):
        self._journal["message"] = message
        return SimpleNamespace(text="réponse du modèle")


class _FauxClient:
    def __init__(self, journal):
        self._journal = journal
        self.chats = SimpleNamespace(create=self._create)

    def _create(self, *, model, history=None, config=None):
        self._journal.update(model=model, history=history, config=config)
        return _FauxChat(self._journal)


@pytest.fixture
def gemini(monkeypatch):
    journal = {}
    monkeypatch.setattr(gs, "get_gemini_client", lambda: _FauxClient(journal))
    return journal


def _faux_post(captures, charge_utile):
    """Remplace requests.post en enregistrant le corps JSON envoyé."""
    def poster(url, json=None, headers=None, timeout=None):
        captures.append(json)
        return SimpleNamespace(
            status_code=200,
            text="",
            raise_for_status=lambda: None,
            json=lambda: charge_utile,
        )
    return poster


class TestGemini:
    def test_le_systeme_va_dans_system_instruction(self, gemini):
        gs.complete_text("Combien de lignes ?", "gemini-3.1-flash-lite-preview",
                         system=_SYSTEME)

        assert gemini["config"].system_instruction == _SYSTEME
        assert gemini["message"] == "Combien de lignes ?"

    def test_sans_systeme_aucun_config_nest_impose(self, gemini):
        """Les prompts de tâche (intention, génération de code) n'ont pas de
        consigne conversationnelle : leur comportement ne doit pas changer."""
        gs.complete_text("Classifie : bonjour", "gemini-3.1-flash-lite-preview")

        assert gemini["config"] is None

    def test_ask_gemini_ne_concatene_plus_le_systeme(self, gemini):
        reponse = gs.ask_gemini("Combien de lignes ?",
                                data_context="CONTEXTE-DONNEES-SENTINELLE",
                                model="gemini-3.1-flash-lite-preview")

        assert reponse == "réponse du modèle"
        # Le prompt système de l'app est bien celui posé en system_instruction…
        assert "agent d'analyse de données" in gemini["config"].system_instruction
        # …et le tour utilisateur ne garde que ce qui vient de l'utilisateur.
        assert "agent d'analyse de données" not in gemini["message"]
        assert "CONTEXTE-DONNEES-SENTINELLE" in gemini["message"]
        assert "Question : Combien de lignes ?" in gemini["message"]


class TestOllama:
    def test_le_systeme_va_dans_son_champ(self, monkeypatch):
        captures = []
        monkeypatch.setattr(requests, "post",
                            _faux_post(captures, {"response": "ok"}))

        assert gs.complete_text("Combien de lignes ?", "qwen3.5:2b",
                                system=_SYSTEME) == "ok"

        envoye = captures[0]
        assert envoye["system"] == _SYSTEME
        assert _SYSTEME not in envoye["prompt"]

    def test_le_systeme_nest_jamais_ampute_par_le_raccourcissement(self, monkeypatch):
        """Le cas qui motive la correction côté local : concaténé, le prompt
        système d'un gros contexte tombait dans la zone coupée par `_trim_prompt`.
        Dans son champ dédié il arrive entier, et son coût reste décompté du budget
        du prompt — le total envoyé au modèle est donc EXACTEMENT celui d'avant, la
        correction ne se paie pas en fenêtre de contexte.
        """
        captures = []
        monkeypatch.setattr(requests, "post",
                            _faux_post(captures, {"response": "ok"}))

        systeme = "CONSIGNE. " * 120          # ~1 200 caractères
        brut = "x" * 100_000
        ollama_service.ask_ollama(brut, model="qwen3.5:2b", system=systeme)

        envoye = captures[0]
        assert envoye["system"] == systeme
        assert systeme not in envoye["prompt"]

        # Ce que l'ancien code aurait envoyé : tout concaténé, puis raccourci.
        # (`_trim_prompt` dépasse `limit` du marqueur de coupe qu'il insère — un
        # surcoût constant, présent avant comme après.)
        total_avant = len(ollama_service._trim_prompt(f"{systeme}\n\n{brut}"))
        assert len(envoye["prompt"]) + len(envoye["system"]) <= total_avant

    def test_le_systeme_survit_aux_replis(self, monkeypatch):
        """Un repli qui perdrait la consigne changerait la langue et le format de
        la réponse dégradée."""
        captures = []

        def post_qui_echoue_deux_fois(url, json=None, headers=None, timeout=None):
            captures.append(json)
            if len(captures) <= 2:
                raise requests.RequestException("VRAM insuffisante")
            return SimpleNamespace(status_code=200, text="",
                                   raise_for_status=lambda: None,
                                   json=lambda: {"response": "ok"})

        monkeypatch.setattr(requests, "post", post_qui_echoue_deux_fois)

        ollama_service.ask_ollama("Combien de lignes ?", model="qwen3.5:2b",
                                  system=_SYSTEME)

        assert len(captures) == 3          # nominal, repli CPU, contexte réduit
        assert all(envoi["system"] == _SYSTEME for envoi in captures)


class TestFournisseursApi:
    def test_openai_compatible_place_le_systeme_en_premier_message(self, monkeypatch):
        captures = []
        monkeypatch.setenv("OPENAI_API_KEY", "clef-de-test")
        monkeypatch.setattr(requests, "post", _faux_post(
            captures, {"choices": [{"message": {"content": "ok"}}]}))

        assert gs.complete_text("Combien de lignes ?", "openai/gpt-4o",
                                system=_SYSTEME) == "ok"

        messages = captures[0]["messages"]
        assert messages[0] == {"role": "system", "content": _SYSTEME}
        assert messages[-1]["role"] == "user"
        assert _SYSTEME not in messages[-1]["content"]

    def test_anthropic_place_le_systeme_hors_des_messages(self, monkeypatch):
        """L'API Messages refuse un rôle `system` dans `messages` : la consigne a
        son propre champ au niveau de la requête."""
        captures = []
        monkeypatch.setenv("ANTHROPIC_API_KEY", "clef-de-test")
        monkeypatch.setattr(requests, "post", _faux_post(
            captures, {"content": [{"text": "ok"}]}))

        assert gs.complete_text("Combien de lignes ?", "anthropic/claude-sonnet-4-5",
                                system=_SYSTEME) == "ok"

        envoye = captures[0]
        assert envoye["system"] == _SYSTEME
        assert all(msg["role"] != "system" for msg in envoye["messages"])
        assert _SYSTEME not in envoye["messages"][-1]["content"]


class TestVision:
    """Seul le bras Gemini posait le prompt système. Lire le même scan avec
    Claude, GPT-4o ou un modèle local donnait donc une réponse sans les règles de
    langue et de style de l'application."""

    _IMG = [b"\x89PNG-factice"]

    def test_ollama_vision_recoit_le_systeme(self, monkeypatch):
        from app.services.vision_service import ask_vision

        captures = []
        monkeypatch.setattr(requests, "post",
                            _faux_post(captures, {"response": "ok"}))

        assert ask_vision("De quoi parle ce document ?", self._IMG,
                          model="llava:13b") == "ok"
        assert "agent d'analyse de données" in captures[0]["system"]

    def test_anthropic_vision_recoit_le_systeme(self, monkeypatch):
        from app.services.vision_service import ask_vision

        captures = []
        monkeypatch.setenv("ANTHROPIC_API_KEY", "clef-de-test")
        monkeypatch.setattr(requests, "post", _faux_post(
            captures, {"content": [{"text": "ok"}]}))

        assert ask_vision("De quoi parle ce document ?", self._IMG,
                          model="anthropic/claude-sonnet-4-5") == "ok"
        assert "agent d'analyse de données" in captures[0]["system"]


class TestLangueDEvaluation:
    """Les campagnes d'évaluation basculent en anglais via un ContextVar. La
    consigne de langue doit suivre le prompt système dans son nouvel emplacement,
    sinon le banc InfiAgent-DABench reçoit des réponses en français."""

    def test_la_variante_anglaise_part_en_system_instruction(self, gemini):
        jeton = gs.response_language.set("en")
        try:
            gs.ask_gemini("How many rows?", model="gemini-3.1-flash-lite-preview")
        finally:
            gs.response_language.reset(jeton)

        assert "You always answer in English." in gemini["config"].system_instruction
