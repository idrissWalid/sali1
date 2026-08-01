"""Ne pas demander à un petit modèle local d'écrire la méthodologie SARIMA A–H.

Le pipeline rigoureux fait ÉCRIRE au modèle ~80 lignes de consignes normatives
(étapes A à H, deux gates bloquants, hygiène mémoire, schéma JSON exact). Un modèle
servi en local n'y arrive pas : il produit du code cassé, épuise les tours
d'autocorrection, et l'on se replie de toute façon sur le moteur déterministe —
plusieurs minutes et plusieurs appels LLM plus tard, pour le même résultat.

Rien n'est retiré en capacité : `run_autoforecast_timeseries` garde lui-même le
pipeline rigoureux en secours interne. Seul l'ORDRE change, et seulement là où
l'utilisateur n'a choisi aucun moteur.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.api.chat as chat
import app.services.timeseries_pipeline as pipeline
import app.services.timeseries_service as ts_service


def _succes(moteur):
    return {
        "ok": True, "response": f"resultat {moteur}", "images": [],
        "model_id": f"id-{moteur}", "report": {}, "error": None,
    }


def _echec(moteur):
    return {
        "ok": False, "error": f"{moteur} a echoue", "technical": "",
        "response": "", "images": [], "model_id": None, "report": None,
    }


def _preparer(monkeypatch, *, rigoureux, automatique, colonnes=("date", "ventes")):
    """Instrumente les deux moteurs et renvoie la liste des appels observés.

    Les imports du moteur sont faits À L'INTÉRIEUR de `_run_dataset_intent` : c'est
    donc l'attribut du module qu'il faut remplacer, pas un nom déjà lié.
    """
    appels = []

    def faux_rigoureux(**kwargs):
        appels.append("rigoureux")
        return rigoureux

    def faux_automatique(**kwargs):
        appels.append("automatique")
        return automatique

    monkeypatch.setattr(pipeline, "run_rigorous_timeseries", faux_rigoureux)
    monkeypatch.setattr(pipeline, "run_autoforecast_timeseries", faux_automatique)
    monkeypatch.setattr(ts_service, "infer_series_columns", lambda *a, **k: colonnes)
    # Le repli conversationnel, quand les deux moteurs échouent.
    monkeypatch.setattr(chat, "ask_gemini", lambda **k: "repli conversationnel")
    return appels


def _jouer(model, **prepare):
    """Déroule la branche « séries temporelles » et renvoie (appels, résultat)."""
    async def collecter():
        return [
            ev async for ev in chat._run_dataset_intent(
                "series_temporelles", "s1", "Prevois les ventes", model, [],
                b"date,ventes\n2020-01,10\n", "ventes.csv", "CONTEXTE",
            )
        ]

    evenements = asyncio.run(collecter())
    return [e for e in evenements if e["type"] == "result"][-1]


class TestModeleLocal:
    def test_le_moteur_deterministe_est_essaye_en_premier(self, monkeypatch):
        appels = _preparer(monkeypatch,
                           rigoureux=_succes("rigoureux"),
                           automatique=_succes("automatique"))

        final = _jouer("qwen3.5:4b")

        assert appels == ["automatique"]
        assert final["response"] == "resultat automatique"
        assert final["model_type"] == "timeseries"

    def test_le_pipeline_rigoureux_nest_jamais_redemande_apres_un_echec(self, monkeypatch):
        """`run_autoforecast_timeseries` a déjà tenté le rigoureux en secours
        interne : le relancer ferait écrire deux fois la méthodologie A–H à un modèle
        qui vient d'échouer."""
        appels = _preparer(monkeypatch,
                           rigoureux=_succes("rigoureux"),
                           automatique=_echec("automatique"))

        final = _jouer("qwen3.5:4b")

        assert appels == ["automatique"]
        assert "rigoureux" not in appels
        assert final["response"] == "repli conversationnel"

    def test_sans_colonnes_deductibles_le_rigoureux_reste_la_seule_option(self, monkeypatch):
        """Le moteur automatique EXIGE un couple (date, valeur). S'il est
        indéterminable, la dégradation ne doit pas coûter la fonctionnalité."""
        appels = _preparer(monkeypatch,
                           rigoureux=_succes("rigoureux"),
                           automatique=_succes("automatique"),
                           colonnes=(None, None))

        final = _jouer("qwen3.5:4b")

        assert appels == ["rigoureux"]
        assert final["response"] == "resultat rigoureux"


class TestModeleDistant:
    def test_lordre_nominal_est_inchange(self, monkeypatch):
        """Une API — même petite — sait suivre la méthodologie. Dégrader son chemin
        casserait le parcours produit par défaut et la campagne d'évaluation."""
        appels = _preparer(monkeypatch,
                           rigoureux=_succes("rigoureux"),
                           automatique=_succes("automatique"))

        final = _jouer("gemini-3.1-flash-lite-preview")

        assert appels == ["rigoureux"]
        assert final["response"] == "resultat rigoureux"

    def test_le_repli_historique_sur_le_moteur_automatique_survit(self, monkeypatch):
        appels = _preparer(monkeypatch,
                           rigoureux=_echec("rigoureux"),
                           automatique=_succes("automatique"))

        final = _jouer("openai/gpt-4o")

        assert appels == ["rigoureux", "automatique"]
        assert final["response"] == "resultat automatique"
