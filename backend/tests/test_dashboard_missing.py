import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_service import _build_missing_insight


def test_missing_insight_distingue_cellules_et_lignes_affectees():
    df = pd.DataFrame({
        "a": [1, None, 3],
        "b": [None, None, 9],
    })

    insight = _build_missing_insight(df)

    assert insight == {
        "n_valeurs_manquantes": 3,
        "pct_cellules_manquantes": 50.0,
        "n_lignes_affectees": 2,
        "pct_lignes_affectees": 66.67,
        "n_colonnes_affectees": 2,
    }
