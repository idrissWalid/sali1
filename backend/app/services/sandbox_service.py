"""
sandbox_service.py — Exécution sécurisée de code Python via Docker.

Le code est exécuté dans un container Docker éphémère et isolé :
  - --network=none    → pas d'accès réseau
  - --memory=256m     → limite RAM
  - --cpus=0.5        → limite CPU
  - --rm              → container supprimé après exécution
  - --read-only       → système de fichiers en lecture seule (sauf /tmp)
  - timeout 30s       → tue le container si trop long
"""

import base64
import json
import subprocess
import sys
from pydantic import ValidationError
from app.services.model_specs import ModelSpec

# Nom de l'image Docker sandbox (construite avec sandbox/Dockerfile)
SANDBOX_IMAGE = "no-code-sandbox:latest"
SANDBOX_TIMEOUT = 120  # secondes pour laisser AutoML s'exécuter


def execute_code(code: str, dataframe_bytes: bytes = None, filename: str = None) -> dict:
    """
    Exécute `code` dans un container Docker isolé.

    Args:
        code:             Code Python à exécuter (df est disponible si dataframe_bytes fourni)
        dataframe_bytes:  Contenu brut du fichier CSV/Excel
        filename:         Nom du fichier (pour déterminer l'extension)

    Returns:
        dict avec clés : output (str), images (list[str base64]), metrics (dict|None), error (dict|None)
    """
    # Préparer le payload JSON pour le runner.py
    data_b64 = None
    if dataframe_bytes and filename:
        data_b64 = base64.b64encode(dataframe_bytes).decode("utf-8")

    # Injection pour fixer le problème de Read-Only File System sans avoir à rebuild l'image Docker.
    # Change le dossier de travail du processus vers /tmp avant d'exécuter le code.
    safe_code = "import os, tempfile\ntry:\n    os.chdir(tempfile.gettempdir())\nexcept:\n    pass\n" + code

    payload = json.dumps({
        "code": safe_code,
        "data_b64": data_b64,
        "filename": filename,
    }, ensure_ascii=False)

    # Lancer le container Docker
    cmd = [
        "docker", "run",
        "--rm",                   # supprimer après exécution
        "-i",                     # mode interactif (stdin)
        "--network=none",         # pas d'accès réseau
        "--memory=256m",          # limite RAM
        "--memory-swap=256m",     # pas de swap
        "--cpus=0.5",             # limite CPU
        "--read-only",            # FS en lecture seule
        "--tmpfs", "/tmp:rw,size=64m,noexec",  # /tmp en RAM pour les graphiques
        SANDBOX_IMAGE,
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=SANDBOX_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {
            "output": "",
            "images": [],
            "metrics": None,
            "error": {
                "technical": f"TimeoutExpired: exécution dépassé {SANDBOX_TIMEOUT}s",
                "simple": f"Le code a mis plus de {SANDBOX_TIMEOUT} secondes — opération annulée.",
            },
        }
    except FileNotFoundError:
        # Docker n'est pas installé ou pas dans le PATH
        return _fallback_local_exec(code, dataframe_bytes, filename)
    except Exception as exc:
        return {
            "output": "",
            "images": [],
            "metrics": None,
            "error": {
                "technical": str(exc),
                "simple": "Erreur lors du lancement du container Docker.",
            },
        }

    # Analyser la sortie du container
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0 and not stdout:
        return {
            "output": "",
            "images": [],
            "metrics": None,
            "error": {
                "technical": stderr or f"Exit code {proc.returncode}",
                "simple": "Le container a échoué à démarrer.",
            },
        }

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "output": stdout,
            "images": [],
            "metrics": None,
            "error": {
                "technical": f"Sortie non-JSON du container:\n{stdout}\nstderr:\n{stderr}",
                "simple": "Réponse inattendue du sandbox.",
            },
        }

    # Normaliser le champ error pour correspondre au format attendu par code_pipeline.py
    if result.get("error"):
        raw_error = result["error"]
        if isinstance(raw_error, str):
            # Extraire le dernier message de la traceback comme message simple
            lines = [l for l in raw_error.strip().splitlines() if l.strip()]
            simple = lines[-1] if lines else raw_error
            result["error"] = {"technical": raw_error, "simple": simple}
    else:
        result["error"] = None

    if "metrics" not in result:
        result["metrics"] = None
        
    if "models" not in result:
        result["models"] = []

    return result


def _fallback_local_exec(code: str, dataframe_bytes: bytes, filename: str) -> dict:
    """
    Fallback : exécution locale si Docker n'est pas disponible.
    Affiche un avertissement mais reste fonctionnel en développement.
    """
    import io
    import traceback
    import contextlib
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import base64 as b64

    print(
        "[WARN] Docker non disponible — exécution locale (non sécurisée).",
        file=sys.stderr,
    )

    local_env = {}
    if dataframe_bytes and filename:
        import pandas as pd
        ext = filename.split(".")[-1].lower()
        try:
            if ext == "csv":
                df = pd.read_csv(io.BytesIO(dataframe_bytes))
            else:
                df = pd.read_excel(io.BytesIO(dataframe_bytes))
            local_env["df"] = df
        except Exception:
            pass

    import pandas as pd
    import numpy as np
    import seaborn as sns
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    local_env.update({"pd": pd, "np": np, "plt": plt, "sns": sns, "sm": sm, "smf": smf})

    stdout_cap = io.StringIO()
    images = []
    metrics = None
    error = None

    try:
        with contextlib.redirect_stdout(stdout_cap):
            exec(code, local_env)  # noqa: S102
        for fig_num in plt.get_fignums():
            fig = plt.figure(fig_num)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                        facecolor="#1a1a1a", edgecolor="none")
            buf.seek(0)
            images.append(b64.b64encode(buf.read()).decode("utf-8"))
            plt.close(fig)
        if os.path.exists("metrics.json"):
            try:
                import json
                with open("metrics.json", "r", encoding="utf-8") as f:
                    metrics = json.load(f)
            except Exception as e:
                pass
                
        for f in os.listdir("."):
            if f.endswith(".pkl"):
                try:
                    model_name = f[:-4]
                    with open(f, "rb") as mf:
                        model_b64 = b64.b64encode(mf.read()).decode("utf-8")
                    
                    metadata = {}
                    meta_file = f"{model_name}_metadata.json"
                    if os.path.exists(meta_file):
                        import json
                        with open(meta_file, "r", encoding="utf-8") as meta_f:
                            metadata = json.load(meta_f)
                            
                    if "models" not in locals():
                        models = []
                    models.append({
                        "name": model_name,
                        "model_b64": model_b64,
                        "metadata": metadata
                    })
                except Exception:
                    pass
    except Exception:
        tb = traceback.format_exc()
        lines = [l for l in tb.strip().splitlines() if l.strip()]
        error = {"technical": tb, "simple": lines[-1] if lines else str(tb)}

    return {"output": stdout_cap.getvalue(), "images": images, "metrics": metrics, "models": locals().get("models", []), "error": error}

def validate_output(result: dict, spec: ModelSpec) -> dict:
    """
    Valide les metrics.json générés par rapport au ModelSpec.
    Si succès, le résultat est intact (result["error"]=None).
    Si échec de validation, remplit l'erreur avec les champs manquants.
    """
    if result["error"]:
        return result

    metrics = result.get("metrics")
    if not metrics:
        result["error"] = {
            "technical": "Missing metrics.json",
            "simple": "Le code n'a pas produit de fichier metrics.json."
        }
        return result

    try:
        spec.output_schema.model_validate(metrics)
    except ValidationError as e:
        # Formater les erreurs Pydantic pour être renvoyées au LLM
        missing_fields = []
        for err in e.errors():
            field_path = ".".join(str(loc) for loc in err["loc"])
            msg = err["msg"]
            missing_fields.append(f"Champ '{field_path}': {msg}")
        
        err_msg = "\\n".join(missing_fields)
        result["error"] = {
            "technical": f"Validation Error:\\n{err_msg}",
            "simple": "Le modèle a omis certaines statistiques obligatoires."
        }

    return result