"""Modifier les données depuis le chat, sans que ce soit irréversible.

Une transformation demandée en langage naturel écrase le fichier de
l'utilisateur. Elle n'est acceptable qu'à trois conditions, vérifiées ici :
le tableau modifié ressort réellement du sandbox, l'état précédent est archivé
avant d'être remplacé, et « annuler » le restaure à l'identique.
"""

import contextlib
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.core.database as database
import app.services.session_service as session_service
from app.api.chat import _compte_rendu_modification, _est_demande_annulation, _nom_csv
from app.services.chart_spec import extract_dataset, prelude_snippet
from app.services.sandbox_charts import ChartError, emit_dataset

_ORIGINE = b"region,ventes\nDakar,10\nThies,20\n"
_MODIFIE = b"region,ventes\nDakar,10\n"


# ── Sortie du sandbox ────────────────────────────────────────────────────────

def _executer(code: str):
    env = {}
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        exec(prelude_snippet(), env)  # noqa: S102
        exec(code, env)  # noqa: S102
    return extract_dataset(capture.getvalue())


def test_le_tableau_modifie_ressort_du_sandbox():
    """Sans ce canal, un DataFrame transformé mourrait avec le container."""
    csv, sortie = _executer(
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2]})\n"
        "print('Lignes : 2')\n"
        "emit_dataset(df)"
    )
    assert list(pd.read_csv(io.BytesIO(csv))["a"]) == [1, 2]
    # Le base64 ne doit pas rester dans la sortie : elle part au prompt d'interprétation.
    assert sortie == "Lignes : 2"


def test_le_dernier_etat_emis_l_emporte():
    csv, _ = _executer(
        "import pandas as pd\n"
        "emit_dataset(pd.DataFrame({'a': [1]}))\n"
        "emit_dataset(pd.DataFrame({'a': [1, 2, 3]}))"
    )
    assert len(pd.read_csv(io.BytesIO(csv))) == 3


def test_une_sortie_sans_tableau_ne_renvoie_rien():
    assert extract_dataset("Rien à signaler") == (None, "Rien à signaler")


def test_une_ligne_tronquee_ne_remplace_pas_les_donnees():
    """Mieux vaut ne rien enregistrer qu'enregistrer un tableau corrompu."""
    csv, sortie = extract_dataset("<<<SALI_DATASET>>>pas-du-base64!!\nsuite")
    assert csv is None
    assert "suite" in sortie


def test_emit_dataset_refuse_ce_qui_n_est_pas_un_tableau():
    with pytest.raises(ChartError):
        emit_dataset([1, 2, 3])
    with pytest.raises(ChartError):
        emit_dataset(pd.DataFrame())


# ── Versions et annulation ───────────────────────────────────────────────────

@pytest.fixture
def base_isolee(tmp_path, monkeypatch):
    """Base et dossier d'upload jetables : ces tests écrivent vraiment."""
    monkeypatch.setattr(database, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(session_service, "UPLOADS_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    database.init_db()

    session_id = session_service.create_session()
    session_service.save_file_bytes(session_id, _ORIGINE, "ventes.csv")
    session_service.save_data_context(
        session_id, {"rows": 2, "columns": 2, "preview": []}, {}, "ventes.csv",
    )
    return session_id


def test_un_jeu_jamais_modifie_est_en_version_1(base_isolee):
    assert session_service.version_dataset(base_isolee, "__main__") == 1


def test_la_modification_remplace_les_donnees_et_incremente_la_version(base_isolee):
    retour = session_service.remplacer_dataset(
        base_isolee, "__main__", _MODIFIE,
        {"rows": 1, "columns": 2, "preview": []}, {}, "supprime Thiès",
    )

    assert retour["status"] == "ok"
    assert retour["version"] == 2
    octets, _, profile, _ = session_service.get_dataset(base_isolee, "__main__")
    assert octets == _MODIFIE
    assert profile["rows"] == 1


def test_annuler_restaure_l_etat_precedent_a_l_identique(base_isolee):
    """La garantie qui rend la fonctionnalité acceptable."""
    session_service.remplacer_dataset(
        base_isolee, "__main__", _MODIFIE,
        {"rows": 1, "columns": 2, "preview": []}, {}, "supprime Thiès",
    )
    retour = session_service.annuler_derniere_modification(base_isolee, "__main__")

    assert retour["status"] == "ok"
    assert retour["motif"] == "supprime Thiès"
    octets, _, profile, _ = session_service.get_dataset(base_isolee, "__main__")
    assert octets == _ORIGINE
    assert profile["rows"] == 2
    assert session_service.version_dataset(base_isolee, "__main__") == 1


def test_les_annulations_se_depilent_une_a_une(base_isolee):
    for i in range(3):
        session_service.remplacer_dataset(
            base_isolee, "__main__", f"a\n{i}\n".encode(),
            {"rows": 1, "columns": 1, "preview": []}, {}, f"modif {i}",
        )
    assert session_service.version_dataset(base_isolee, "__main__") == 4

    for i in reversed(range(3)):
        retour = session_service.annuler_derniere_modification(base_isolee, "__main__")
        assert retour["motif"] == f"modif {i}"

    octets, _, _, _ = session_service.get_dataset(base_isolee, "__main__")
    assert octets == _ORIGINE


def test_annuler_sans_modification_le_dit(base_isolee):
    retour = session_service.annuler_derniere_modification(base_isolee, "__main__")
    assert retour["status"] == "error"
    assert "Aucune modification" in retour["message"]


def test_un_jeu_attache_se_modifie_et_s_annule_aussi(base_isolee):
    dataset_id = session_service.add_dataset(
        base_isolee, _ORIGINE, "annexe.csv", {"rows": 2, "columns": 2}, {},
    )
    session_service.remplacer_dataset(
        base_isolee, dataset_id, _MODIFIE, {"rows": 1, "columns": 2}, {}, "filtre",
    )
    octets, _, _, _ = session_service.get_dataset(base_isolee, dataset_id)
    assert octets == _MODIFIE

    session_service.annuler_derniere_modification(base_isolee, dataset_id)
    octets, _, _, _ = session_service.get_dataset(base_isolee, dataset_id)
    assert octets == _ORIGINE


def test_le_changement_de_format_suit_le_contenu(base_isolee):
    """Le tableau modifié ressort en CSV : l'extension doit suivre, sinon toute
    la chaîne tenterait de le relire avec `read_excel`."""
    session_service.save_file_bytes(base_isolee, _ORIGINE, "classeur.xlsx")
    retour = session_service.remplacer_dataset(
        base_isolee, "__main__", _MODIFIE, {"rows": 1, "columns": 2, "preview": []}, {},
        "nettoyage", nouveau_filename="classeur.csv",
    )

    assert retour["format_change"] is True
    _, filename, _, _ = session_service.get_dataset(base_isolee, "__main__")
    assert filename == "classeur.csv"


def test_modifier_un_jeu_inexistant_ne_casse_rien(base_isolee):
    retour = session_service.remplacer_dataset(
        base_isolee, "inconnu", _MODIFIE, {}, {}, "peu importe",
    )
    assert retour["status"] == "error"


def test_supprimer_la_session_emporte_les_instantanes(base_isolee):
    """La ligne part en cascade SQL ; le fichier, lui, resterait orphelin."""
    import os

    session_service.remplacer_dataset(
        base_isolee, "__main__", _MODIFIE,
        {"rows": 1, "columns": 2, "preview": []}, {}, "modif",
    )
    conn = database.get_db_connection()
    chemins = [r["file_path"] for r in conn.execute(
        "SELECT file_path FROM dataset_versions WHERE session_id = ?", (base_isolee,)
    ).fetchall()]
    conn.close()
    assert chemins and all(os.path.exists(c) for c in chemins)

    session_service.delete_session_cascade(base_isolee)
    assert not any(os.path.exists(c) for c in chemins)


def test_la_version_est_exposee_dans_la_liste_des_jeux(base_isolee):
    session_service.remplacer_dataset(
        base_isolee, "__main__", _MODIFIE,
        {"rows": 1, "columns": 2, "preview": []}, {}, "modif",
    )
    principal = [d for d in session_service.list_datasets(base_isolee) if d["id"] == "__main__"][0]
    assert principal["version"] == 2


# ── Reconnaissance de la demande d'annulation ────────────────────────────────

@pytest.mark.parametrize("message", [
    "annule la dernière modification",
    "Annuler",
    "annule le dernier changement",
    "reviens à l'état précédent",
    "défais la dernière modif",
])
def test_les_formulations_d_annulation_sont_reconnues(message):
    assert _est_demande_annulation(message)


@pytest.mark.parametrize("message", [
    "quelle est la moyenne des ventes ?",
    "annule mon abonnement",          # « annule » sans complément de modification
    "supprime les lignes vides",      # une vraie modification, pas une annulation
])
def test_une_demande_ordinaire_n_est_pas_prise_pour_une_annulation(message):
    assert not _est_demande_annulation(message)


# ── Branche de chat ──────────────────────────────────────────────────────────

def _run_transformation(monkeypatch, resultat_sandbox):
    """Déroule la branche `transformation` avec un sandbox simulé."""
    import asyncio

    import app.api.chat as chat
    import app.services.analysis_service as analysis_service

    monkeypatch.setattr(chat, "generate_transformation_code", lambda *a, **k: "emit_dataset(df)")
    monkeypatch.setattr(chat, "run_with_autocorrect", lambda **k: resultat_sandbox)

    async def fausse_analyse(*a, **k):
        return {"status": "ok",
                "profile": {"rows": 1, "columns": 2, "column_names": ["region", "ventes"]},
                "stats": {}}

    monkeypatch.setattr(analysis_service, "analyze_tabular", fausse_analyse)

    async def collecter():
        return [
            e async for e in chat._run_dataset_intent(
                "transformation", "s1", "supprime les lignes vides", "m", [],
                _ORIGINE, "ventes.csv", "contexte", dataset_id="__main__",
            )
        ]
    return [e for e in asyncio.run(collecter()) if e["type"] == "result"][0]


def test_un_code_qui_n_enregistre_rien_ne_fait_pas_croire_le_contraire(monkeypatch):
    """Piège principal : le code tourne sans erreur mais oublie `emit_dataset`.
    Annoncer une modification appliquée serait alors un mensonge."""
    import app.services.session_service as ss

    appels = []
    monkeypatch.setattr(ss, "remplacer_dataset", lambda *a, **k: appels.append(a))

    resultat = _run_transformation(monkeypatch, {
        "output": "Rien à supprimer.", "images": [], "charts": [], "dataset": None, "error": None,
    })

    assert appels == []
    assert "Aucune modification n'a été enregistrée" in resultat["response"]
    assert not resultat.get("dataset_changed")


def test_une_erreur_d_execution_laisse_les_donnees_intactes(monkeypatch):
    import app.services.session_service as ss

    appels = []
    monkeypatch.setattr(ss, "remplacer_dataset", lambda *a, **k: appels.append(a))

    resultat = _run_transformation(monkeypatch, {
        "output": "", "images": [], "charts": [], "dataset": None,
        "error": {"technical": "KeyError: 'region'", "simple": "Colonne introuvable."},
    })

    assert appels == []
    assert "n'a pas été appliquée" in resultat["response"]
    assert "KeyError: 'region'" in resultat["response"]


def test_une_modification_reussie_signale_le_changement_au_client(monkeypatch):
    import app.services.session_service as ss

    monkeypatch.setattr(ss, "remplacer_dataset", lambda *a, **k: {
        "status": "ok", "version": 2, "filename": "ventes.csv", "format_change": False,
    })

    resultat = _run_transformation(monkeypatch, {
        "output": "Lignes supprimées : 1", "images": [], "charts": [],
        "dataset": _MODIFIE, "error": None,
    })

    # `dataset_changed` déclenche le rechargement du panneau des sources :
    # sans lui, l'interface afficherait encore l'ancienne version.
    assert resultat["dataset_changed"] is True
    assert "version 2" in resultat["response"]


# ── Compte rendu ─────────────────────────────────────────────────────────────

def test_le_compte_rendu_chiffre_ce_qui_a_change():
    """Les chiffres avant/après sont ce qui permet de repérer une transformation
    qui a fait plus que demandé."""
    rendu = _compte_rendu_modification(
        {"filename": "ventes.csv", "version": 2},
        {"lignes": 1240, "colonnes": 8, "noms": ["a", "vent", "c"]},
        {"lignes": 1187, "colonnes": 8, "noms": ["a", "ventes", "c"]},
        "Lignes supprimées : 53",
    )

    assert "1240 → 1187 (-53)" in rendu
    assert "Colonnes disparues : vent" in rendu
    assert "Colonnes apparues : ventes" in rendu
    assert "Lignes supprimées : 53" in rendu
    assert "annule la dernière modification" in rendu


def test_le_nom_du_fichier_modifie_passe_en_csv():
    assert _nom_csv("rapport.xlsx") == "rapport.csv"
    assert _nom_csv("deja.csv") == "deja.csv"
    assert _nom_csv(None) == "donnees.csv"
