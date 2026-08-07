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
import math
import os
import subprocess
import sys
from pydantic import ValidationError
from app.core.json_utils import json_safe
from app.services.chart_spec import (
    extract_charts, extract_dataset, injectable_source, prelude_snippet,
)
from app.services.model_specs import ModelFamily, ModelSpec

# Nom de l'image Docker sandbox (construite avec sandbox/Dockerfile)
SANDBOX_IMAGE = "no-code-sandbox:latest"
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "180"))  # s — laisse le grid search SARIMA s'exécuter
# Limites ressources (surchargeables par variables d'env). 256m était trop juste
# pour statsmodels/SARIMA (OOM-kill, exit 137) ; 1g laisse tourner un grid search.
SANDBOX_MEMORY = os.getenv("SANDBOX_MEMORY", "1g")
SANDBOX_CPUS = os.getenv("SANDBOX_CPUS", "1.0")
SANDBOX_TMPFS_SIZE = os.getenv("SANDBOX_TMPFS_SIZE", "128m")


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
    # Même raison pour le helper `emit_chart` : injecté à chaque exécution, il est
    # disponible sans reconstruire l'image sandbox déjà en place.
    safe_code = (
        "import os, tempfile\ntry:\n    os.chdir(tempfile.gettempdir())\nexcept:\n    pass\n"
        + prelude_snippet()
        + code
    )

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
        "--network=none",                       # pas d'accès réseau
        f"--memory={SANDBOX_MEMORY}",           # limite RAM
        f"--memory-swap={SANDBOX_MEMORY}",      # pas de swap au-delà de la RAM
        f"--cpus={SANDBOX_CPUS}",               # limite CPU
        "--read-only",                          # FS en lecture seule
        "--tmpfs", f"/tmp:rw,size={SANDBOX_TMPFS_SIZE},noexec",  # /tmp en RAM
        # Sous cgroup --cpus, numpy/scipy/statsmodels (OpenBLAS/OMP) peuvent quand
        # même tenter de paralléliser sur tous les cœurs de l'hôte et sur-allouer
        # des buffers par thread → dépassement mémoire (OOM, exit 137) même avec
        # une limite RAM confortable. On borne explicitement à 1 thread.
        "-e", "OMP_NUM_THREADS=1",
        "-e", "OPENBLAS_NUM_THREADS=1",
        "-e", "MKL_NUM_THREADS=1",
        "-e", "NUMEXPR_NUM_THREADS=1",
        "-e", "VECLIB_MAXIMUM_THREADS=1",
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
            "charts": [],
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
            "charts": [],
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
            "charts": [],
            "metrics": None,
            "error": {
                "technical": stderr or f"Exit code {proc.returncode}",
                "simple": "Le container a échoué à démarrer.",
            },
        }

    try:
        # `json.loads` relit sans erreur les NaN/Infinity que le runner a pu
        # émettre (metrics.json issu de pandas). On les neutralise ici, sinon ils
        # se propagent jusqu'en base et cassent la lecture du modèle plus tard.
        result = json_safe(json.loads(stdout))
    except json.JSONDecodeError:
        return {
            "output": stdout,
            "images": [],
            "charts": [],
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

    # Les specs de graphiques et le jeu de données modifié transitent par stdout :
    # on les en retire ici, sinon leur contenu repartirait tel quel dans le prompt
    # d'interprétation.
    result["charts"], sortie = extract_charts(result.get("output", ""))
    result["dataset"], result["output"] = extract_dataset(sortie)

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
            exec(injectable_source(), local_env)  # noqa: S102 — définit emit_chart
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
    except Exception as exc:
        # `chain=False` : ce repli est appelé depuis le `except FileNotFoundError`
        # de Docker, si bien que la traceback complète embarquerait en tête une
        # panne (« docker introuvable ») étrangère au code exécuté. Elle repart
        # telle quelle à l'autocorrection, qui dépense alors ses tentatives à
        # réparer le mauvais problème.
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, chain=False))
        lines = [l for l in tb.strip().splitlines() if l.strip()]
        error = {"technical": tb, "simple": lines[-1] if lines else str(tb)}

    charts, sortie = extract_charts(stdout_cap.getvalue())
    dataset, sortie = extract_dataset(sortie)
    return {"output": sortie, "images": images, "charts": charts, "dataset": dataset,
            "metrics": metrics, "models": locals().get("models", []), "error": error}

def _incoherence_echelle_prevision(metrics: dict) -> str | None:
    """Détecte une prévision restée sur une échelle transformée.

    Le prompt impose l'échelle d'origine pour `historique` ET `prevision`, mais
    l'oubli de la transformation inverse (log jamais ré-exponentié) franchit la
    validation de schéma : les types sont corrects, seuls les ordres de grandeur
    sont incohérents. Le dashboard affiche alors une prévision à ~1 sous un
    historique à ~432.

    Renvoie le motif du rejet, ou None si les échelles sont plausibles.
    """
    import statistics

    hist = [h.get("valeur") for h in (metrics.get("historique") or [])]
    hist = [abs(v) for v in hist if isinstance(v, (int, float)) and math.isfinite(v)]
    prev = [p.get("valeur_prevue") for p in (metrics.get("prevision") or [])]
    prev = [abs(v) for v in prev if isinstance(v, (int, float)) and math.isfinite(v)]
    if len(hist) < 3 or not prev:
        return None

    # Médianes : insensibles aux quelques points extrêmes d'une série réelle.
    ref = statistics.median(hist[-min(len(hist), 24):])
    cible = statistics.median(prev)
    if ref <= 0 or cible <= 0:
        return None

    ratio = cible / ref
    # Seuil large (facteur 10) : une série peut légitimement croître fort, mais
    # pas d'un ordre de grandeur sur un horizon de prévision court.
    if 0.1 <= ratio <= 10:
        return None
    return (
        f"Échelle incohérente : la prévision médiane ({cible:.4g}) et la fin de "
        f"l'historique ({ref:.4g}) diffèrent d'un facteur {ratio:.3g}. La "
        f"transformation inverse a probablement été oubliée — si log(y) a été "
        f"appliqué, 'prevision' (valeur_prevue, ic_bas, ic_haut) doit être "
        f"ré-exponentiée pour revenir à l'échelle d'origine, comme 'historique'."
    )


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

    # Le schéma est respecté, mais des valeurs valides peuvent rester absurdes :
    # on relance l'autocorrection plutôt que de livrer une prévision inexploitable.
    if spec.family == ModelFamily.TIME_SERIES:
        motif = _incoherence_echelle_prevision(metrics)
        if motif:
            result["error"] = {
                "technical": motif,
                "simple": "La prévision produite n'est pas à la même échelle que l'historique.",
            }

    return result