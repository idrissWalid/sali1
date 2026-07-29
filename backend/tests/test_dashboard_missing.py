"""Régression : les valeurs manquantes étaient traitées comme une modalité.

`get_dashboard_data` neutralisait les manquants sur le DataFrame d'analyse
(`df.replace({np.nan: None})`) avant d'en déduire le type de graphique. Or ce
remplacement bascule en dtype `object` TOUTE colonne contenant un manquant :
`is_numeric_dtype` répondait alors faux, et une variable numérique partait dans
la branche catégorielle où chacune de ses valeurs devenait une modalité — la
traîne finissant regroupée dans « Autres ».
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_service import (
    _category_counts,
    _discrete_label,
    _drop_missing,
    _preview_records,
)


def test_le_remplacement_global_detruisait_le_type_des_colonnes():
    """Le mécanisme même de la régression, isolé."""
    df = pd.DataFrame({"prix": [10.0, 20.5, np.nan, 33.2]})

    assert pd.api.types.is_numeric_dtype(df["prix"])
    # L'ancien prétraitement : la colonne cesse d'être numérique…
    assert not pd.api.types.is_numeric_dtype(df.replace({np.nan: None})["prix"])
    # …ce qui l'envoyait vers le comptage de modalités.
    assert not pd.api.types.is_datetime64_any_dtype(
        pd.DataFrame({"d": pd.to_datetime(["2024-01-01", None])}).replace({np.nan: None})["d"]
    )


def test_apercu_json_neutralise_les_manquants_sans_toucher_aux_dtypes():
    df = pd.DataFrame({
        "d": pd.to_datetime(["2024-01-01", None]),
        "v": [1.5, np.nan],
        "c": ["a", None],
        "i": np.array([1, 2], dtype="int64"),
    })

    rows = _preview_records(df)

    assert rows[1] == {"d": None, "v": None, "c": None, "i": 2}
    # Les entiers numpy ne sont pas sérialisables tels quels par FastAPI.
    assert type(rows[0]["i"]) is int
    # Le DataFrame source garde ses types : c'est là-dessus que porte le correctif.
    assert pd.api.types.is_numeric_dtype(df["v"])
    assert pd.api.types.is_datetime64_any_dtype(df["d"])


def test_un_manquant_ne_devient_jamais_une_modalite():
    series = pd.Series(["x", "y", np.nan, "x", None, pd.NaT])

    assert [item["name"] for item in _category_counts(series)] == ["x", "y"]


def test_les_manquants_ecrits_en_texte_sont_ecartes():
    """Excel, OCR et tableaux de PDF livrent « N/A » ou « NULL » comme du texte :
    `dropna` seul les laisserait passer pour des catégories."""
    series = pd.Series(["Paris", "N/A", "Lyon", "NULL", "   ", "Paris", "<NA>", "none"])

    assert [item["name"] for item in _category_counts(series)] == ["Paris", "Lyon"]


def test_les_placeholders_ambigus_restent_des_modalites():
    """« - » ou « ? » peuvent être de vraies valeurs : les écarter d'office ferait
    disparaître une catégorie sans que rien ne le signale."""
    assert _drop_missing(pd.Series(["a", "-", "?", "b"])).tolist() == ["a", "-", "?", "b"]


def test_une_numerique_a_manquants_garde_des_libelles_entiers():
    """Un indicateur 0/1 comportant des manquants est typé `float64` par pandas."""
    assert _discrete_label(1.0) == "1"
    assert _discrete_label(0.0) == "0"
    assert _discrete_label(2.5) == "2.5"
