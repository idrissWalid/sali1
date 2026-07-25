"""timecopilot_runner.py — Script exécuté DANS le venv dédié à TimeCopilot.

Ce fichier n'est jamais importé par le backend : il est lancé en sous-processus
par `.venv-timecopilot/bin/python`, parce que les dépendances de TimeCopilot sont
incompatibles avec celles du backend (transformers<5 vs colpali-engine>=5.3,
openai>=1.99 vs pandasai<0.28 — aucune version commune n'existe).

Protocole, calqué sur `sandbox/runner.py` pour rester familier :
  - entrée  : un JSON sur stdin
      {"csv": "...", "date_col": "...", "value_col": "...",
       "freq": "MS"|null, "h": 12|null, "query": "...", "llm": "openai:gpt-4o"}
  - sortie  : un JSON sur stdout
      {"ok": bool, "result": {...}, "fcst": [...], "error": {...}|null}

Aucune dépendance au code du backend : ce script doit tourner avec le seul
contenu du venv TimeCopilot.
"""

import io
import json
import sys
import traceback


def _erreur(simple: str, technique: str = "") -> dict:
    return {"ok": False, "result": None, "fcst": [], "error": {"simple": simple, "technical": technique}}


def _serialisable(valeur):
    """Rend une sortie pydantic/numpy convertible en JSON.

    `result.output` est un modèle pydantic dont les champs mêlent scalaires,
    listes de chaînes et types numpy ; on les ramène à des types standards.
    """
    import math

    if isinstance(valeur, float):
        return valeur if math.isfinite(valeur) else None
    if isinstance(valeur, (str, int, bool)) or valeur is None:
        return valeur
    if isinstance(valeur, dict):
        return {str(k): _serialisable(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_serialisable(v) for v in valeur]
    # numpy scalar, Timestamp, Enum…
    for attr in ("item", "isoformat"):
        if hasattr(valeur, attr):
            try:
                return _serialisable(getattr(valeur, attr)())
            except Exception:
                pass
    return str(valeur)


# Modèles statistiques de TimeCopilot réimplémentables via statsforecast, pour
# recalculer les intervalles de prévision (voir `_intervalles`). Les modèles hors
# de cette table (Prophet, modèles de fondation) sont ignorés : mieux vaut aucun
# intervalle qu'un intervalle emprunté à un autre modèle.
_MODELES_STATSFORECAST = {
    "AutoARIMA": "AutoARIMA",
    "AutoETS": "AutoETS",
    "AutoTheta": "AutoTheta",
    "Theta": "Theta",
    "AutoCES": "AutoCES",
    "SeasonalNaive": "SeasonalNaive",
    "HistoricAverage": "HistoricAverage",
    "ADIDA": "ADIDA",
}


def _intervalles(df, modele: str, h: int, freq: str, saison: int, prevu: list[float]):
    """Recalcule la prévision AVEC intervalle à 95 % en réajustant le modèle
    retenu par TimeCopilot (qui, lui, ne renvoie que le point).

    Les intervalles ne sont retournés que si le point recalculé coïncide avec
    celui de TimeCopilot : sinon ils décriraient une autre prévision que celle
    affichée, ce qui serait pire que pas d'intervalle du tout.
    """
    classe = _MODELES_STATSFORECAST.get(modele)
    if not classe:
        return None
    try:
        import numpy as np
        from statsforecast import StatsForecast
        import statsforecast.models as sfm

        ctor = getattr(sfm, classe)
        try:
            instance = ctor(season_length=saison)
        except TypeError:
            instance = ctor()  # modèles sans saisonnalité paramétrable

        sf = StatsForecast(models=[instance], freq=freq)
        out = sf.forecast(df=df[["unique_id", "ds", "y"]], h=h, level=[95])

        col_pt = next((c for c in out.columns if c == classe), None)
        col_bas = next((c for c in out.columns if c.endswith("-lo-95")), None)
        col_haut = next((c for c in out.columns if c.endswith("-hi-95")), None)
        if not (col_pt and col_bas and col_haut):
            return None

        recalcule = out[col_pt].to_numpy(dtype=float)
        if len(recalcule) != len(prevu):
            return None
        reference = np.asarray(prevu, dtype=float)
        echelle = max(float(np.nanmean(np.abs(reference))), 1e-9)
        # 1 % d'écart relatif : tolère le bruit numérique, rejette un modèle
        # réellement différent.
        if float(np.nanmax(np.abs(recalcule - reference))) / echelle > 0.01:
            return None

        return list(zip(out[col_bas].to_numpy(dtype=float),
                        out[col_haut].to_numpy(dtype=float)))
    except Exception:
        return None


def _liste_depuis_df(df, formatter) -> list:
    """Aplati un DataFrame d'une ligne en liste « clé: valeur » lisible."""
    try:
        if df is None or len(df) == 0:
            return []
        return formatter(df)
    except Exception:
        return []


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception as exc:
        print(json.dumps(_erreur("Entrée illisible par le moteur TimeCopilot.", str(exc))))
        return

    try:
        import pandas as pd
        from timecopilot import TimeCopilot
    except Exception:
        print(json.dumps(_erreur(
            "Le venv TimeCopilot est incomplet. Réinstallez-le : "
            "python3.11 -m venv backend/.venv-timecopilot && "
            "backend/.venv-timecopilot/bin/pip install -r backend/requirements-timecopilot.txt",
            traceback.format_exc(),
        )))
        return

    try:
        df = pd.read_csv(io.StringIO(payload["csv"]))

        # TimeCopilot impose le format long de Nixtla : unique_id / ds / y.
        date_col, value_col = payload["date_col"], payload["value_col"]
        df = df[[date_col, value_col]].rename(columns={date_col: "ds", value_col: "y"})
        df["ds"] = pd.to_datetime(df["ds"], errors="coerce")
        df["y"] = pd.to_numeric(df["y"], errors="coerce")
        df = df.dropna(subset=["ds", "y"]).sort_values("ds")
        if df.empty:
            print(json.dumps(_erreur(
                f"Aucune ligne exploitable après lecture de « {date_col} » et « {value_col} »."
            )))
            return
        df.insert(0, "unique_id", payload.get("serie_id") or "serie")

        agent = TimeCopilot(llm=payload["llm"], retries=payload.get("retries", 3))

        kwargs = {"df": df}
        for cle in ("freq", "h"):
            if payload.get(cle):
                kwargs[cle] = payload[cle]
        if payload.get("query"):
            kwargs["query"] = payload["query"]

        resultat = agent.forecast(**kwargs)

        sortie = resultat.output
        # `model_dump` existe sur les modèles pydantic ; sinon on retombe sur les
        # attributs publics, pour ne pas dépendre d'une version précise.
        if hasattr(sortie, "model_dump"):
            brut = sortie.model_dump()
        else:
            brut = {k: getattr(sortie, k) for k in dir(sortie)
                    if not k.startswith("_") and not callable(getattr(sortie, k))}

        # `features_df` et `eval_df` portent ce que le README appelle
        # `tsfeatures_results` et `cross_validation_results` : la 0.0.28 les
        # expose en DataFrame plutôt qu'en liste dans `output`.
        brut.setdefault("tsfeatures_results", _liste_depuis_df(
            getattr(resultat, "features_df", None),
            lambda d: [f"{c}: {d.iloc[0][c]:.4g}" if isinstance(d.iloc[0][c], (int, float))
                       else f"{c}: {d.iloc[0][c]}" for c in d.columns],
        ))
        brut.setdefault("cross_validation_results", _liste_depuis_df(
            getattr(resultat, "eval_df", None),
            lambda d: [f"{c}: {d.iloc[0][c]:.4g}" for c in d.columns if c != "metric"],
        ))
        try:
            metrique = str(resultat.eval_df.iloc[0]["metric"])
            brut.setdefault("cross_validation_metric", metrique)
        except Exception:
            pass

        fcst = []
        try:
            fdf = resultat.fcst_df.copy()
            # La colonne de valeurs porte le nom du modèle retenu (« Theta »,
            # « AutoARIMA »…) : on la retrouve en écartant les colonnes connues.
            col_val = next((c for c in fdf.columns
                            if c not in ("unique_id", "ds", "cutoff")), None)
            valeurs = [float(v) for v in fdf[col_val]] if col_val else []

            # TimeCopilot ne renvoie que la prévision ponctuelle : on réajuste le
            # modèle qu'il a retenu pour obtenir l'intervalle à 95 % réclamé par
            # le tableau du dashboard.
            saison = 1
            try:
                saison = int(resultat.features_df.iloc[0]["seasonal_period"])
            except Exception:
                pass
            bornes = _intervalles(
                df, str(brut.get("selected_model") or col_val or ""),
                len(fdf), kwargs.get("freq") or (pd.infer_freq(df["ds"]) or "MS"),
                max(saison, 1), valeurs,
            )

            for i, (_, ligne) in enumerate(fdf.iterrows()):
                point = {
                    "date": str(pd.Timestamp(ligne["ds"]).date()),
                    "valeur_prevue": valeurs[i] if i < len(valeurs) else None,
                }
                if bornes is not None:
                    point["ic_bas"], point["ic_haut"] = bornes[i]
                fcst.append(point)
            brut.setdefault("intervalles_disponibles", bornes is not None)
        except Exception:
            pass  # Le rapport textuel reste exploitable même sans tableau.

        print(json.dumps({
            "ok": True,
            "result": _serialisable(brut),
            "fcst": _serialisable(fcst),
            "error": None,
        }, ensure_ascii=False))

    except Exception:
        tb = traceback.format_exc()
        lignes = [l for l in tb.strip().splitlines() if l.strip()]
        print(json.dumps(_erreur(lignes[-1] if lignes else "Échec TimeCopilot.", tb),
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
