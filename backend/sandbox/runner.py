"""
runner.py — Exécuté à l'intérieur du container Docker sandbox.

Protocole :
  - Lit un JSON depuis stdin : { "code": str, "data_b64": str|null, "filename": str|null }
  - Exécute le code Python dans un env isolé avec df disponible
  - Retourne un JSON sur stdout : { "output": str, "images": [base64...], "error": str|null }
"""

import sys
import io
import json
import base64
import traceback
import contextlib
import os
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    # Lire l'entrée complète depuis stdin
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        _exit_error(f"Erreur de décodage JSON stdin: {e}")
        return

    code: str = payload.get("code", "")
    data_b64: str | None = payload.get("data_b64")
    filename: str | None = payload.get("filename")

    # Préparer l'environnement d'exécution
    local_env = _build_env(data_b64, filename)

    # Captures
    stdout_capture = io.StringIO()
    images: list[str] = []
    error_info = None

    try:
        # Changer le dossier de travail vers un dossier temporaire en écriture
        # pour éviter les erreurs "Read-only file system" sur Docker avec --read-only
        os.chdir(tempfile.gettempdir())
        
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, local_env)  # noqa: S102

        output = stdout_capture.getvalue()

        # Récupérer tous les graphiques matplotlib générés
        for fig_num in plt.get_fignums():
            fig = plt.figure(fig_num)
            buf = io.BytesIO()
            fig.savefig(
                buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#1a1a1a", edgecolor="none"
            )
            buf.seek(0)
            images.append(base64.b64encode(buf.read()).decode("utf-8"))
            plt.close(fig)

    except Exception:
        error_info = traceback.format_exc()
        output = stdout_capture.getvalue()

    metrics_data = None
    if os.path.exists("metrics.json"):
        try:
            with open("metrics.json", "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
        except Exception as e:
            error_info = f"Failed to parse metrics.json: {e}\n{error_info or ''}"

    # Extract any trained models (.pkl) and their metadata
    extracted_models = []
    for f in os.listdir("."):
        if f.endswith(".pkl"):
            try:
                model_name = f[:-4]
                with open(f, "rb") as mf:
                    model_b64 = base64.b64encode(mf.read()).decode("utf-8")
                
                metadata = {}
                meta_file = f"{model_name}_metadata.json"
                if os.path.exists(meta_file):
                    with open(meta_file, "r", encoding="utf-8") as meta_f:
                        metadata = json.load(meta_f)
                        
                extracted_models.append({
                    "name": model_name,
                    "model_b64": model_b64,
                    "metadata": metadata
                })
            except Exception as e:
                error_info = f"Failed to extract model {f}: {e}\n{error_info or ''}"

    result = {
        "output": output,
        "images": images,
        "charts": _json_safe(local_env.get("charts", [])),
        "metrics": metrics_data,
        "models": extracted_models,
        "error": error_info,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


def _json_safe(value):
    """Convertit les sorties pandas/numpy en valeurs JSON strictes."""
    import math
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _build_env(data_b64: str | None, filename: str | None) -> dict:
    """Construit l'environnement Python avec toutes les bibliothèques disponibles."""
    import pandas as pd
    import numpy as np
    import seaborn as sns
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from sklearn.ensemble import (
        RandomForestClassifier, RandomForestRegressor,
        GradientBoostingClassifier, GradientBoostingRegressor,
        IsolationForest,
    )
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.cluster import KMeans, DBSCAN
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import (
        classification_report, confusion_matrix,
        roc_curve, auc, silhouette_score,
        mean_absolute_error, mean_squared_error, r2_score,
    )
    from sklearn.decomposition import PCA
    import joblib

    env = {
        "pd": pd, "np": np, "plt": plt, "sns": sns,
        "sm": sm, "smf": smf, "joblib": joblib,
        "RandomForestClassifier": RandomForestClassifier,
        "RandomForestRegressor": RandomForestRegressor,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "GradientBoostingRegressor": GradientBoostingRegressor,
        "IsolationForest": IsolationForest,
        "LogisticRegression": LogisticRegression,
        "LinearRegression": LinearRegression,
        "KMeans": KMeans, "DBSCAN": DBSCAN,
        "LocalOutlierFactor": LocalOutlierFactor,
        "StandardScaler": StandardScaler,
        "LabelEncoder": LabelEncoder,
        "train_test_split": train_test_split,
        "cross_val_score": cross_val_score,
        "classification_report": classification_report,
        "confusion_matrix": confusion_matrix,
        "roc_curve": roc_curve, "auc": auc,
        "silhouette_score": silhouette_score,
        "mean_absolute_error": mean_absolute_error,
        "mean_squared_error": mean_squared_error,
        "r2_score": r2_score, "PCA": PCA,
    }

    # Charger le DataFrame si des données sont fournies
    if data_b64 and filename:
        try:
            raw_bytes = base64.b64decode(data_b64)
            ext = filename.rsplit(".", 1)[-1].lower()
            if ext == "csv":
                df = pd.read_csv(io.BytesIO(raw_bytes))
            else:
                df = pd.read_excel(io.BytesIO(raw_bytes))
            env["df"] = df
        except Exception as exc:
            # Pas de df disponible mais on continue
            env["_load_error"] = str(exc)

    return env


def _exit_error(msg: str):
    result = {"output": "", "images": [], "charts": [], "error": msg}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
