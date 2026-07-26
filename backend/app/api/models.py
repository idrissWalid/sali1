import asyncio
import os
import io
import json
import uuid
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional

from app.core.database import get_db_connection
from app.core import config
import joblib

router = APIRouter(
    prefix="/models",
    tags=["models"]
)

class PredictRequest(BaseModel):
    features: Dict[str, Any]


class TrainSupervisedRequest(BaseModel):
    """Le modèle n'est pas choisi par l'utilisateur : la famille est déduite de la
    cible et tous les modèles de cette famille sont mis en concurrence."""

    session_id: str
    target: str
    dataset_id: Optional[str] = None
    features: Optional[list[str]] = None
    model: Optional[str] = None  # modèle LLM, pour l'interprétation uniquement


class TrainTimeSeriesRequest(BaseModel):
    session_id: str
    date_col: str
    value_col: str
    dataset_id: Optional[str] = None
    horizon: Optional[int] = None
    # "auto" = pipeline ARIMA/SARIMA rigoureux (code généré + autocorrigé)
    # "autoforecast" = moteur multi-modèles déterministe (statsforecast) en sandbox
    engine: str = "auto"
    model: Optional[str] = None  # modèle LLM pour la génération de code / interprétation

@router.get("/{session_id}")
async def list_models(session_id: str):
    """Liste tous les modèles entraînés pour une session donnée."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, type, features, metrics, created_at FROM models WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    models_list = []
    for r in rows:
        models_list.append({
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "features": json.loads(r["features"]) if r["features"] else [],
            "metrics": json.loads(r["metrics"]) if r["metrics"] else {},
            "created_at": r["created_at"]
        })
    
    return {"models": models_list}

@router.get("/info/{model_id}")
async def get_model_info(model_id: str):
    """Récupère les informations d'un modèle spécifique."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, type, features, metrics, created_at FROM models WHERE id = ?",
        (model_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
        
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "features": json.loads(row["features"]) if row["features"] else [],
        "metrics": json.loads(row["metrics"]) if row["metrics"] else {},
        "created_at": row["created_at"]
    }

@router.get("/{model_id}/download")
async def download_model(model_id: str):
    """Télécharge le fichier .pkl du modèle."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, file_path FROM models WHERE id = ?", (model_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row["file_path"] or not os.path.exists(row["file_path"]):
        raise HTTPException(status_code=404, detail="Modèle introuvable")
        
    return FileResponse(
        path=row["file_path"],
        filename=f"{row['name']}.pkl",
        media_type="application/octet-stream"
    )

@router.post("/{model_id}/predict")
async def predict(model_id: str, request: PredictRequest):
    """Fait une prédiction à partir des features fournies."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, features, type, metrics FROM models WHERE id = ?", (model_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row["file_path"] or not os.path.exists(row["file_path"]):
        raise HTTPException(status_code=404, detail="Modèle introuvable")
        
    try:
        expected_features = json.loads(row["features"]) if row["features"] else []
        model = await asyncio.to_thread(joblib.load, row["file_path"])

        # Prepare DataFrame for prediction (models usually expect 2D arrays/DataFrames)
        input_data = {}
        if expected_features:
            for feat in expected_features:
                val = request.features.get(feat)
                if val is None:
                    raise HTTPException(status_code=400, detail=f"Caractéristique manquante : {feat}")
                input_data[feat] = [val]
            df = pd.DataFrame(input_data)
        else:
            # S'il n'y a pas de features explicites, on utilise tout ce qu'on reçoit
            input_data = {k: [v] for k, v in request.features.items()}
            df = pd.DataFrame(input_data)

        # Predict
        prediction = await asyncio.to_thread(model.predict, df)

        reponse = {"prediction": prediction.tolist()}

        # Un pipeline de classification expose les probabilités : sans elles, la
        # simulation afficherait une classe sans dire à quel point elle est sûre.
        try:
            if hasattr(model, "predict_proba"):
                proba = (await asyncio.to_thread(model.predict_proba, df))[0]
                classes_modele = list(getattr(model, "classes_", range(len(proba))))
                metriques = json.loads(row["metrics"]) if "metrics" in row.keys() and row["metrics"] else {}
                libelles = ((metriques.get("artefact") or {}).get("classes")
                            or metriques.get("classes") or None)
                reponse["probabilites"] = {
                    str(libelles[int(c)]) if libelles and int(c) < len(libelles) else str(c): float(p)
                    for c, p in zip(classes_modele, proba)
                }
                if libelles:
                    idx = int(prediction[0])
                    if 0 <= idx < len(libelles):
                        reponse["classe_predite"] = str(libelles[idx])
        except Exception:
            pass  # La prédiction reste exploitable même sans probabilités.

        return reponse

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de prédiction : {str(e)}")


def _load_dataset_df(session_id: str, dataset_id: Optional[str]):
    from app.services.session_service import get_dataset
    file_bytes, filename, _profile, _stats = get_dataset(session_id, dataset_id)
    if not file_bytes:
        return None, None
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext == "csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))
    return df, filename


@router.get("/timeseries-candidates/{session_id}")
async def timeseries_candidates(session_id: str, dataset_id: Optional[str] = None):
    """Colonnes candidates pour une série temporelle : dates possibles (axe) et
    numériques (valeur à prévoir). Alimente la modale d'entraînement."""
    from app.services.timeseries_service import detect_timeseries_columns

    df, _ = await asyncio.to_thread(_load_dataset_df, session_id, dataset_id)
    if df is None:
        raise HTTPException(status_code=404, detail="Jeu de données introuvable.")

    date_columns, value_columns = detect_timeseries_columns(df)

    return {
        "date_columns": date_columns,
        "value_columns": value_columns,
        "n_rows": len(df),
        # Une série temporelle exige au moins un axe date et une valeur numérique.
        "feasible": bool(date_columns and value_columns),
    }


@router.get("/supervised-candidates/{session_id}")
async def supervised_candidates(session_id: str, dataset_id: Optional[str] = None):
    """Colonnes utilisables comme cible, avec la famille qui en découlerait.

    Permet à l'interface d'annoncer « régression » ou « classification » AVANT
    de lancer un tournoi de plusieurs minutes.
    """
    from app.services.supervised_specs import SEUIL_DESEQUILIBRE

    df, _ = await asyncio.to_thread(_load_dataset_df, session_id, dataset_id)
    if df is None:
        raise HTTPException(status_code=404, detail="Jeu de données introuvable.")

    cibles = []
    for col in df.columns:
        serie = df[col].dropna()
        if serie.empty or serie.nunique() < 2:
            continue
        if pd.api.types.is_numeric_dtype(df[col]) and serie.nunique() > 20:
            famille, ratio = "regression", None
        else:
            ratio = float(serie.value_counts(normalize=True).min())
            famille = ("classification_desequilibree"
                       if ratio < SEUIL_DESEQUILIBRE else "classification")
        cibles.append({
            "colonne": str(col),
            "famille": famille,
            "n_modalites": int(serie.nunique()),
            "ratio_minoritaire": ratio,
        })

    return {"cibles": cibles, "n_rows": len(df), "feasible": bool(cibles)}


@router.post("/train-supervised")
async def train_supervised(request: TrainSupervisedRequest):
    """Met en concurrence les modèles de la famille déduite de la cible et
    persiste le meilleur. Un modèle n'est validé que si ses hypothèses
    statistiques ET ses performances tiennent."""
    from app.services.session_service import get_dataset
    from app.services.supervised_pipeline import run_supervised_tournament

    file_bytes, filename, profile, _stats = get_dataset(request.session_id, request.dataset_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Jeu de données introuvable.")

    colonnes = (profile or {}).get("column_names", [])
    data_context = (
        f"Jeu de données : {filename}. Colonnes : "
        f"{', '.join(map(str, colonnes)) if colonnes else 'inconnues'}.\n"
        f"Variable à prédire : '{request.target}'."
    )
    result = await asyncio.to_thread(
        run_supervised_tournament,
        question=f"Construis le meilleur modèle pour prédire « {request.target} ».",
        file_bytes=file_bytes,
        filename=filename,
        session_id=request.session_id,
        data_context=data_context,
        model=request.model or config.get_default_model(),
        target=request.target,
        features=request.features,
    )

    if not result.get("ok"):
        detail = result.get("error") or "Échec de l'entraînement."
        if result.get("technical"):
            detail = f"{detail} ({str(result['technical'])[:300]})"
        raise HTTPException(status_code=422, detail=detail)

    rapport = result.get("report") or {}
    return {
        "model_id": result["model_id"],
        "statut_final": rapport.get("statut_final"),
        "famille": rapport.get("famille"),
        "response": result.get("response", ""),
    }


@router.post("/train-timeseries")
async def train_timeseries(request: TrainTimeSeriesRequest):
    """Entraîne un modèle de série temporelle (pipeline rigoureux ARIMA/SARIMA ou
    moteur de prévision automatique) sur les colonnes choisies, le persiste, et
    renvoie son id."""
    from app.services.session_service import get_dataset
    from app.services.timeseries_pipeline import (
        run_autoforecast_timeseries, run_rigorous_timeseries, run_timecopilot_timeseries,
    )

    file_bytes, filename, profile, _stats = get_dataset(request.session_id, request.dataset_id)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Jeu de données introuvable.")

    columns = (profile or {}).get("column_names", [])
    data_context = (
        f"Jeu de données : {filename}. Colonnes : {', '.join(map(str, columns)) if columns else 'inconnues'}.\n"
        f"Série temporelle à modéliser : axe temporel = '{request.date_col}', "
        f"valeur = '{request.value_col}'."
    )
    question = (
        f"Construis le meilleur modèle de série temporelle (ARIMA ou SARIMA selon la "
        f"saisonnalité) pour prévoir « {request.value_col} » en fonction de « {request.date_col} »."
    )
    llm_model = request.model or config.get_default_model()

    if request.engine == "timecopilot":
        # Le vrai TimeCopilot : agent LLM + modèles de fondation, dans son venv
        # dédié. Pas de repli silencieux — l'utilisateur a choisi ce moteur.
        result = await asyncio.to_thread(
            run_timecopilot_timeseries,
            question=question, file_bytes=file_bytes, filename=filename,
            session_id=request.session_id, data_context=data_context, model=llm_model,
            date_col=request.date_col, value_col=request.value_col, horizon=request.horizon,
        )
    elif request.engine == "autoforecast":
        result = await asyncio.to_thread(
            run_autoforecast_timeseries,
            question=question, file_bytes=file_bytes, filename=filename,
            session_id=request.session_id, data_context=data_context, model=llm_model,
            date_col=request.date_col, value_col=request.value_col, horizon=request.horizon,
        )
    else:
        result = await asyncio.to_thread(
            run_rigorous_timeseries,
            question=question, data_context=data_context, file_bytes=file_bytes,
            filename=filename, session_id=request.session_id, model=llm_model,
            date_col=request.date_col, value_col=request.value_col, horizon=request.horizon,
        )

    if not result.get("ok"):
        detail = result.get("error") or "Échec de l'entraînement."
        technical = result.get("technical")
        if technical:
            # Détail court pour faciliter le diagnostic côté client/logs.
            detail = f"{detail} ({str(technical)[:300]})"
        raise HTTPException(status_code=422, detail=detail)

    report = result.get("report") or {}
    return {
        "model_id": result["model_id"],
        "statut_final": report.get("statut_final"),
        "response": result.get("response", ""),
    }
