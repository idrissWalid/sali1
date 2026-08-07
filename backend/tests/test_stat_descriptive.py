"""Les statistiques descriptives passent par le sandbox, plus par PandasAI.

L'ancien chemin exécutait le code du modèle dans le processus backend, et
retombait silencieusement sur une réponse conversationnelle quand ce code
échouait : sur une question chiffrée, l'utilisateur recevait alors une
estimation de mémoire présentée comme un calcul. Ces tests verrouillent les deux
moitiés de la correction — le calcul a bien lieu dans le sandbox, et un échec se
dit au lieu d'être maquillé.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.api.chat as chat
import app.services.gemini_service as gs

RACINE = Path(__file__).resolve().parents[1]


def _executer(intent="stat_descriptive", message="Quelle est la moyenne des ventes ?"):
    """Déroule le générateur d'intention et renvoie la liste des événements."""
    async def collecter():
        return [
            event async for event in chat._run_dataset_intent(
                intent, "session-1", message, "modele-test", [],
                b"a,b\n1,2\n", "data.csv", "contexte de données",
            )
        ]
    return asyncio.run(collecter())


@pytest.fixture(autouse=True)
def _pas_d_appel_reseau(monkeypatch):
    monkeypatch.setattr(chat, "generate_stats_code", lambda *a, **k: "print(df['a'].mean())")
    monkeypatch.setattr(chat, "ask_gemini", lambda *a, **k: "RÉPONSE-CONVERSATIONNELLE")


def test_le_calcul_passe_par_le_sandbox(monkeypatch):
    appels = {}

    def faux_pipeline(**kwargs):
        appels.update(kwargs)
        return {"output": "Moyenne : 12.5", "images": [], "charts": [], "error": None}

    monkeypatch.setattr(chat, "run_with_autocorrect", faux_pipeline)
    resultat = [e for e in _executer() if e["type"] == "result"][0]

    # Le code généré est bien celui qui part au pipeline sandbox…
    assert appels["initial_code"] == "print(df['a'].mean())"
    assert appels["file_bytes"] == b"a,b\n1,2\n"
    # …et la sortie calculée précède l'interprétation rédigée.
    assert resultat["response"].startswith("Moyenne : 12.5")


def test_un_echec_de_calcul_n_est_pas_remplace_par_une_reponse_de_memoire(monkeypatch):
    """Le cœur de la correction : sans calcul, pas de chiffre."""
    monkeypatch.setattr(chat, "run_with_autocorrect", lambda **k: {
        "output": "", "images": [], "charts": [],
        "error": {"technical": "KeyError: 'ventes'", "simple": "Colonne introuvable."},
    })

    resultat = [e for e in _executer() if e["type"] == "result"][0]

    assert "RÉPONSE-CONVERSATIONNELLE" not in resultat["response"]
    assert "KeyError: 'ventes'" in resultat["response"]
    assert "Colonne introuvable." in resultat["response"]


def test_les_graphiques_emis_remontent_jusqu_au_resultat(monkeypatch):
    graphique = {
        "v": 1, "kind": "column", "title": "Répartition",
        "x": {"key": "a", "label": "a", "type": "category"},
        "y": {"label": None, "format": "number"},
        "series": [{"key": "b", "label": "b"}],
        "data": [{"a": "x", "b": 1}], "stacked": False,
    }
    monkeypatch.setattr(chat, "run_with_autocorrect", lambda **k: {
        "output": "ok", "images": [], "charts": [graphique], "error": None,
    })

    resultat = [e for e in _executer() if e["type"] == "result"][0]
    assert resultat["charts"] == [graphique]


def test_sans_code_genere_aucun_chiffre_n_est_avance(monkeypatch):
    monkeypatch.setattr(chat, "generate_stats_code", lambda *a, **k: "")
    monkeypatch.setattr(chat, "run_with_autocorrect", lambda **k: pytest.fail(
        "Le pipeline ne doit pas être appelé sans code à exécuter."
    ))

    resultat = [e for e in _executer() if e["type"] == "result"][0]
    assert "RÉPONSE-CONVERSATIONNELLE" not in resultat["response"]
    assert resultat["charts"] == []


def test_le_prompt_de_calcul_interdit_les_valeurs_ecrites_en_dur(monkeypatch):
    captures = {}

    def faux_complete(prompt, model, history=None, system=None):
        captures["prompt"] = prompt
        return "print(1)"

    monkeypatch.setattr(gs, "complete_text", faux_complete)
    gs.generate_stats_code("Moyenne ?", "contexte", [], "openai/gpt-4o-mini")

    prompt = captures["prompt"]
    assert "aucune valeur affichée ne doit être écrite en dur" in prompt.lower()
    assert "emit_chart" in prompt          # graphiques interactifs, pas de PNG
    assert "valeurs manquantes" in prompt  # exclues du calcul et signalées


def test_plus_aucun_import_de_pandasai_dans_le_backend():
    """La dépendance est retirée : un import résiduel casserait le démarrage.

    Seuls les imports comptent — les commentaires qui racontent la migration
    citent légitimement le nom du paquet.
    """
    import re

    motif = re.compile(r"^\s*(from|import)\s+pandasai", re.MULTILINE)
    fautifs = [
        chemin.relative_to(RACINE).as_posix()
        for chemin in (RACINE / "app").rglob("*.py")
        if motif.search(chemin.read_text(encoding="utf-8"))
    ]
    assert fautifs == []


def test_pandasai_ne_figure_plus_dans_les_dependances():
    lignes = [
        ligne.strip()
        for ligne in (RACINE / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.strip().startswith("#")
    ]
    assert not [ligne for ligne in lignes if "pandasai" in ligne.lower()]
