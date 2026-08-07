"""Les graphiques du chat ne sont plus des PNG mais des specs JSON.

Deux choses doivent tenir : le transport (stdout de la sandbox → spec, sans
polluer la sortie texte envoyée au modèle) et les plafonds de lisibilité, qui
sont la vraie raison d'être de `emit_chart` — un graphique à 300 barres ne doit
pas pouvoir atteindre le navigateur.
"""

import contextlib
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chart_spec import (
    chart_from_timeseries_report,
    extract_charts,
    prelude_snippet,
)
from app.services.sandbox_charts import (
    MAX_CATEGORIES,
    MAX_POINTS_LINE,
    MAX_TABLE_ROWS,
    ChartError,
    build_chart_spec,
    emit_chart,
    markdown_table,
)


def _executer(code: str) -> tuple[list, str]:
    """Exécute du code comme le ferait la sandbox, helper injecté compris."""
    env = {}
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        exec(prelude_snippet(), env)  # noqa: S102
        exec(code, env)  # noqa: S102
    return extract_charts(capture.getvalue())


def test_le_helper_injecte_est_disponible_sans_import():
    """La sandbox tourne sur une image Docker figée : le helper voyage avec le
    code, sinon il faudrait reconstruire l'image à chaque déploiement."""
    charts, _ = _executer(
        "emit_chart('column', [{'a': 'x', 'b': 1}, {'a': 'y', 'b': 2}], title='T')"
    )
    assert len(charts) == 1
    assert charts[0]["kind"] == "column"
    assert charts[0]["title"] == "T"


def test_la_sortie_texte_ne_contient_plus_le_json_du_graphique():
    """Le JSON repartirait sinon dans le prompt d'interprétation, où il coûte du
    contexte et finit recopié dans la réponse."""
    charts, sortie = _executer(
        "print('Moyenne : 12.5')\n"
        "emit_chart('column', [{'a': 'x', 'b': 1}])\n"
        "print('Fin')"
    )
    assert len(charts) == 1
    assert sortie == "Moyenne : 12.5\nFin"
    assert "SALI_CHART" not in sortie


def test_les_valeurs_non_finies_deviennent_nulles():
    """NaN n'existe pas en JSON : laissé tel quel il casse la lecture côté client."""
    df = pd.DataFrame({"region": ["A", "B"], "ventes": [1.5, float("nan")]})
    spec = build_chart_spec("column", df, x="region", y="ventes")
    assert spec["data"] == [
        {"region": "A", "ventes": 1.5},
        {"region": "B", "ventes": None},
    ]


def test_trop_de_categories_sont_repliees_dans_autres():
    df = pd.DataFrame({
        "cle": [f"c{i}" for i in range(120)],
        "valeur": list(range(120)),
    })
    spec = build_chart_spec("column", df, x="cle", y="valeur")

    assert len(spec["data"]) == MAX_CATEGORIES + 1
    assert spec["data"][-1]["cle"] == "Autres"
    # Le repli conserve la masse : ce qui disparaît des libellés reste dans le total.
    assert spec["data"][-1]["valeur"] == sum(range(120 - MAX_CATEGORIES))
    assert spec["reductions"]


def test_une_serie_longue_est_echantillonnee_en_gardant_le_dernier_point():
    """Le dernier point est la valeur que le lecteur cherche en premier."""
    df = pd.DataFrame({"t": list(range(5000)), "v": list(range(5000))})
    spec = build_chart_spec("line", df, x="t", y="v")

    assert len(spec["data"]) == MAX_POINTS_LINE
    assert spec["data"][-1]["t"] == 4999


def test_une_valeur_unique_devient_une_tuile_et_non_une_barre_solitaire():
    spec = build_chart_spec("column", [{"a": "Total", "b": 42}], x="a", y="b")
    assert spec["kind"] == "stat"


def test_un_nuage_de_points_plafonne_a_trois_series():
    """Au-delà de trois, deux couleurs quelconques peuvent se toucher et la
    palette ne garantit plus de les distinguer."""
    df = pd.DataFrame({"x": [1, 2], "a": [1, 2], "b": [2, 3], "c": [3, 4], "d": [4, 5]})
    spec = build_chart_spec("scatter", df, x="x")
    assert [s["key"] for s in spec["series"]] == ["a", "b", "c"]
    assert any("d" in r for r in spec["reductions"])


def test_une_colonne_absente_produit_une_erreur_explicite():
    """Le message repart à l'autocorrection : il doit nommer le problème."""
    with pytest.raises(ChartError) as exc:
        build_chart_spec("column", [{"a": 1}], x="inexistante")
    assert "inexistante" in str(exc.value)


def test_une_ligne_json_tronquee_ne_casse_pas_la_reponse():
    charts, sortie = extract_charts("<<<SALI_CHART>>>{\"kind\": \"col\nreste du texte")
    assert charts == []
    assert "reste du texte" in sortie


def test_une_spec_de_type_inconnu_est_rejetee():
    charts, _ = extract_charts('<<<SALI_CHART>>>{"kind": "pyramide", "data": [{}], "series": []}')
    assert charts == []


def test_la_traceback_du_repli_local_ne_traine_pas_la_panne_docker():
    """Le repli local est appelé depuis le `except FileNotFoundError` de Docker :
    sans rupture de chaînage, la traceback renvoyée à l'autocorrection s'ouvrait
    sur « docker introuvable », et le modèle réparait le mauvais problème."""
    from app.services.sandbox_service import _fallback_local_exec

    try:
        raise FileNotFoundError("docker introuvable — SENTINELLE-DOCKER")
    except FileNotFoundError:
        resultat = _fallback_local_exec("raise ValueError('le vrai problème')", None, None)

    technique = resultat["error"]["technical"]
    assert "SENTINELLE-DOCKER" not in technique
    assert "le vrai problème" in technique


def test_le_rapport_de_serie_temporelle_donne_une_spec_avec_bande_de_confiance():
    spec = chart_from_timeseries_report({
        "variable": "Ventes",
        "historique": [{"date": "2024-01-01", "valeur": 10.0}],
        "prevision": [{"date": "2024-02-01", "valeur_prevue": 12.0, "ic_bas": 9.0, "ic_haut": 15.0}],
    })

    assert [s["key"] for s in spec["series"]] == ["historique", "prevue"]
    assert spec["band"]["key"] == "ic"
    # Raccord des deux courbes : sans ça un trou d'une période les sépare.
    assert spec["data"][0]["prevue"] == 10.0
    assert spec["data"][1]["ic"] == [9.0, 15.0]


def test_un_rapport_sans_serie_ne_produit_aucun_graphique():
    assert chart_from_timeseries_report({}) is None
    assert chart_from_timeseries_report(None) is None


def test_markdown_table_rend_un_tableau_sans_dependance_externe():
    """`to_markdown()` exigerait `tabulate`, absent de l'image sandbox : le code
    généré échouerait à l'exécution pour une simple question de mise en forme."""
    table = markdown_table(pd.DataFrame({"region": ["Dakar"], "ventes": [12.5]}))
    lignes = table.splitlines()

    assert lignes[0] == "| region | ventes |"
    # Colonne numérique alignée à droite — c'est ce que le chat sait rendre.
    assert lignes[1] == "| --- | ---: |"
    assert lignes[2] == "| Dakar | 12.5 |"


def test_markdown_table_tronque_et_annonce_le_total():
    table = markdown_table(pd.DataFrame({"i": range(100), "v": range(100)}))
    lignes = [l for l in table.splitlines() if l.startswith("|")]

    assert len(lignes) == MAX_TABLE_ROWS + 2  # en-tête + séparateur + lignes
    assert f"sur 100" in table


def test_markdown_table_echappe_les_pipes_et_vide_les_nan():
    table = markdown_table([{"nom": "a|b", "valeur": float("nan")}])
    assert "a\\|b" in table
    assert table.splitlines()[-1] == "| a\\|b |  |"


def test_les_arguments_de_style_de_matplotlib_sont_absorbes():
    """`emit_chart(..., color=...)` est le réflexe naturel d'un modèle habitué à
    matplotlib. Échouer dessus coûtait trois tentatives d'autocorrection et un
    message d'erreur à l'utilisateur, pour un argument sans effet ici."""
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        spec = emit_chart(
            "column", [{"a": "x", "b": 1}, {"a": "y", "b": 2}], title="T",
            color="#ff0000", figsize=(10, 5), alpha=0.8, palette="viridis",
        )
    assert spec["kind"] == "column"
    assert spec["title"] == "T"


def test_un_parametre_inconnu_reste_signale_avec_la_liste_des_valides():
    """La tolérance s'arrête au style : une faute de frappe sur `title` doit
    échouer bruyamment, sinon le titre disparaîtrait sans que personne ne le
    remarque."""
    with pytest.raises(ChartError) as exc:
        emit_chart("column", [{"a": "x", "b": 1}], titre="T")

    message = str(exc.value)
    assert "titre" in message
    assert "title" in message and "y_format" in message  # la liste des acceptés


def test_emit_chart_renvoie_la_spec_emise():
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        spec = emit_chart("column", [{"a": "x", "b": 1}, {"a": "y", "b": 2}])
    assert spec["kind"] == "column"
    assert capture.getvalue().startswith("<<<SALI_CHART>>>")
