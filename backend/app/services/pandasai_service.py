"""
pandasai_service.py — Statistiques descriptives via PandasAI.

Le paquet `pandasai` réellement installé dans ce projet est la version 0.4.0
(API historique `PandasAI(llm=...).run(df, prompt)`) : la "v3" (`SmartDataframe`,
`pandasai.config.Config`) visée par une version précédente de ce fichier n'existe
pas dans cette installation, ce qui faisait échouer systématiquement l'import.

RoutedLLM adapte l'interface `pandasai.llm.base.LLM` (v0.4.0) en délégant à
`complete_text()` de gemini_service, qui route déjà vers Gemini / Ollama / Mistral /
OpenAI / Groq / Anthropic selon le modèle choisi par l'utilisateur — pour que
PandasAI respecte lui aussi ce choix au lieu d'être figé sur Gemini.
"""

import base64
import io
import traceback
from pathlib import Path

import pandas as pd
from pandasai.llm.base import LLM

from app.services.gemini_service import complete_text


# ── Adaptateur LLM compatible avec pandasai 0.4.0 ─────────────────────────────

class RoutedLLM(LLM):
    """Délègue les appels PandasAI au routeur multi-fournisseur du projet."""

    def __init__(self, model: str):
        self.model = model

    def call(self, instruction, value: str, suffix: str = "") -> str:
        prompt = f"{instruction}{value}{suffix}"
        return complete_text(prompt, self.model)

    @property
    def type(self) -> str:
        return f"routed/{self.model}"


# ── Chargement du DataFrame ───────────────────────────────────────────────────

def _load_df(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Charge un DataFrame depuis les bytes bruts du fichier uploadé."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        return pd.read_csv(io.BytesIO(file_bytes))
    return pd.read_excel(io.BytesIO(file_bytes))


# ── Service principal PandasAI ────────────────────────────────────────────────

def ask_pandasai(file_bytes: bytes, filename: str, question: str, model: str = "gemini-3.1-flash-lite-preview") -> dict:
    """
    Répond à une question de statistiques descriptives via PandasAI.

    Args:
        file_bytes: Contenu du fichier CSV/Excel
        filename:   Nom du fichier
        question:   Question en langage naturel
        model:      Modèle sélectionné par l'utilisateur (routé via complete_text)

    Returns:
        dict:
            output (str)       — Réponse textuelle
            images (list[str]) — Graphiques base64 si générés
            error  (dict|None) — Erreur éventuelle
    """
    try:
        df = _load_df(file_bytes, filename)
    except Exception as exc:
        return {
            "output": "",
            "images": [],
            "error": {
                "technical": traceback.format_exc(),
                "simple": f"Impossible de charger le fichier : {exc}",
            },
        }

    try:
        from pandasai import PandasAI

        agent = PandasAI(llm=RoutedLLM(model), verbose=False, enable_cache=False, save_charts=True)
        full_question = f"Réponds en français. {question}"
        result = agent.run(df, full_question)

        if agent.last_error:
            return {
                "output": "",
                "images": [],
                "error": {
                    "technical": agent.last_error,
                    "simple": agent.last_error,
                },
            }

        images = _collect_charts()
        output = _format_result(result)

        return {"output": output, "images": images, "error": None}

    except Exception:
        tb = traceback.format_exc()
        lines = [l for l in tb.strip().splitlines() if l.strip()]
        return {
            "output": "",
            "images": [],
            "error": {
                "technical": tb,
                "simple": lines[-1] if lines else "Erreur PandasAI inconnue.",
            },
        }


def _format_result(result) -> str:
    """Convertit le résultat PandasAI en string propre."""
    if result is None:
        return "Aucun résultat retourné."
    if isinstance(result, pd.DataFrame):
        if hasattr(result, "to_markdown"):
            return result.to_markdown(index=False)
        return result.to_string(index=False)
    if isinstance(result, (int, float)):
        return str(result)
    return str(result)


def _collect_charts() -> list:
    """Récupère les graphiques PNG générés par pandasai (sauvegardés sous
    <site-packages>/exports/charts/<date>/ par le mécanisme save_charts) et les
    encode en base64."""
    import pandasai as _pandasai_pkg

    images = []
    try:
        charts_root = Path(_pandasai_pkg.__file__).resolve().parent.parent / "exports" / "charts"
        for chart_path in sorted(charts_root.glob("*/*.png")):
            with open(chart_path, "rb") as f:
                images.append(base64.b64encode(f.read()).decode("utf-8"))
            chart_path.unlink()
    except Exception:
        pass
    return images


# ── Stats descriptives rapides (sans LLM) ────────────────────────────────────

def get_descriptive_stats(file_bytes: bytes, filename: str) -> dict:
    """
    Génère les statistiques descriptives complètes sans LLM.
    Utilisé pour enrichir le contexte initial de la session.
    """
    try:
        df = _load_df(file_bytes, filename)

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        cat_cols = df.select_dtypes(exclude="number").columns.tolist()

        stats = {}

        if numeric_cols:
            desc = df[numeric_cols].describe().round(4)
            stats["numeriques"] = desc.to_dict()

        cat_stats = {}
        for col in cat_cols:
            vc = df[col].value_counts()
            cat_stats[col] = {
                "n_valeurs_distinctes": int(df[col].nunique()),
                "valeur_dominante": str(vc.index[0]) if len(vc) > 0 else None,
                "frequence_dominante": int(vc.iloc[0]) if len(vc) > 0 else 0,
                "n_manquantes": int(df[col].isna().sum()),
            }
        if cat_stats:
            stats["categorielles"] = cat_stats

        if len(numeric_cols) >= 2:
            corr = df[numeric_cols].corr().round(4)
            stats["correlations"] = corr.to_dict()

        missing = df.isna().sum()
        stats["valeurs_manquantes"] = {
            col: int(missing[col])
            for col in df.columns
            if missing[col] > 0
        }

        return {"status": "ok", "stats": stats, "shape": list(df.shape)}

    except Exception:
        return {
            "status": "error",
            "error": traceback.format_exc(),
        }
