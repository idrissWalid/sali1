from typing import Optional, List, Dict, Any
import uuid
import os
import json
import sqlite3
from app.core.database import get_db_connection

# Configuration des répertoires persistants
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data"))
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

def create_session() -> str:
    session_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (id, title, type) VALUES (?, ?, ?)",
        (session_id, "Nouvelle session", "tabular")
    )
    conn.commit()
    conn.close()
    return session_id

def get_session(session_id: str) -> Optional[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    return {
        "id": row["id"],
        "title": row["title"],
        "type": row["type"],
        "filename": row["filename"],
        "data_profile": json.loads(row["data_profile"]) if row["data_profile"] else None,
        "data_stats": json.loads(row["data_stats"]) if row["data_stats"] else None,
        "data_preview": json.loads(row["data_preview"]) if row["data_preview"] else None,
        "profiling_html": row["profiling_html"],
        "initial_analysis": row["initial_analysis"],
        "file_path": row["file_path"],
        "embedded_table_filename": row["embedded_table_filename"],
        "history": get_history(session_id)
    }

def save_data_context(session_id: str, profile: dict, stats: dict, filename: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Si le titre est encore par défaut, on le met à jour avec le nom du fichier
    cursor.execute("SELECT title FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    title = filename
    if row and row["title"] != "Nouvelle session" and row["title"]:
        title = row["title"]
        
    cursor.execute(
        """
        UPDATE sessions 
        SET title = ?, filename = ?, data_profile = ?, data_stats = ?, data_preview = ? 
        WHERE id = ?
        """,
        (
            title,
            filename,
            json.dumps(profile),
            json.dumps(stats),
            json.dumps(profile.get("preview")) if profile else None,
            session_id
        )
    )
    conn.commit()
    conn.close()

def add_to_history(session_id: str, role: str, content: str):
    # Map role pour la cohérence interne ('model' -> 'assistant')
    db_role = "assistant" if role == "model" else role
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Éviter les doublons successifs
    cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,))
    last = cursor.fetchone()
    if not last or last["role"] != db_role or last["content"] != content:
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, images, sources) VALUES (?, ?, ?, ?, ?)",
            (session_id, db_role, content, json.dumps([]), json.dumps([]))
        )
        conn.commit()
    conn.close()

def get_history(session_id: str) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    # Convertir 'assistant' en 'model' pour l'API Gemini
    history = []
    for r in rows:
        history.append({
            "role": "model" if r["role"] == "assistant" else r["role"],
            "content": r["content"]
        })
    return history

def rename_session(session_id: str, title: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def set_session_type(session_id: str, session_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET type = ? WHERE id = ?", (session_type, session_id))
    conn.commit()
    conn.close()

def get_session_type(session_id: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT type FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return row["type"] if row else "tabular"

def save_file_bytes(session_id: str, file_bytes: bytes, filename: str):
    file_path = os.path.join(UPLOADS_DIR, f"{session_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET filename = ?, file_path = ? WHERE id = ?",
        (filename, file_path, session_id)
    )
    conn.commit()
    conn.close()

def get_file_bytes(session_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT filename, file_path FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row["file_path"] or not os.path.exists(row["file_path"]):
        return None, None
        
    with open(row["file_path"], "rb") as f:
        file_bytes = f.read()
    return file_bytes, row["filename"]

def save_embedded_table(session_id: str, file_bytes: bytes, filename: str, profile: dict, stats: dict):
    """Attache un dataset tabulaire secondaire à une session document (ex : un
    tableau extrait d'un rapport PDF), sans toucher au fichier/résumé principal
    du document."""
    file_path = os.path.join(UPLOADS_DIR, f"{session_id}_table_{filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sessions
        SET embedded_table_filename = ?, embedded_table_file_path = ?,
            embedded_table_profile = ?, embedded_table_stats = ?
        WHERE id = ?
        """,
        (filename, file_path, json.dumps(profile), json.dumps(stats), session_id)
    )
    conn.commit()
    conn.close()

def get_embedded_table(session_id: str):
    """Retourne (file_bytes, filename, profile, stats) du dataset secondaire
    attaché à une session document, ou (None, None, None, None) s'il n'y en a pas."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT embedded_table_filename, embedded_table_file_path, embedded_table_profile, embedded_table_stats FROM sessions WHERE id = ?",
        (session_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not row["embedded_table_file_path"] or not os.path.exists(row["embedded_table_file_path"]):
        return None, None, None, None

    with open(row["embedded_table_file_path"], "rb") as f:
        file_bytes = f.read()

    profile = json.loads(row["embedded_table_profile"]) if row["embedded_table_profile"] else None
    stats = json.loads(row["embedded_table_stats"]) if row["embedded_table_stats"] else None
    return file_bytes, row["embedded_table_filename"], profile, stats

MAIN_DATASET_ID = "__main__"
EMBEDDED_DATASET_ID = "__embedded__"


def add_dataset(session_id: str, file_bytes: bytes, filename: str, profile: dict, stats: dict,
                name: str | None = None, source: str = "upload") -> str:
    """Rattache un jeu de données supplémentaire à une session existante."""
    dataset_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOADS_DIR, f"{session_id}_ds_{dataset_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO datasets (id, session_id, name, filename, file_path, data_profile, data_stats, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dataset_id, session_id, name or filename, filename, file_path,
         json.dumps(profile), json.dumps(stats), source)
    )
    conn.commit()
    conn.close()
    return dataset_id


def list_datasets(session_id: str) -> list[dict]:
    """Tous les jeux de données consultables dans une session.

    Le fichier principal et le tableau éventuellement extrait d'un PDF sont
    synthétisés depuis les colonnes de `sessions`, si bien que les sessions
    créées avant l'arrivée du multi-dataset apparaissent normalement.
    """
    session = get_session(session_id)
    if not session:
        return []

    datasets = []

    if session.get("file_path") and os.path.exists(session["file_path"]):
        profile = session.get("data_profile") or {}
        datasets.append({
            "id": MAIN_DATASET_ID,
            "name": session.get("filename") or "Jeu de données principal",
            "filename": session.get("filename"),
            "source": "upload",
            "rows": profile.get("rows"),
            "columns": profile.get("columns"),
        })

    if session.get("embedded_table_filename"):
        _, filename, profile, _ = get_embedded_table(session_id)
        if filename:
            profile = profile or {}
            datasets.append({
                "id": EMBEDDED_DATASET_ID,
                "name": f"Tableau extrait — {filename}",
                "filename": filename,
                "source": "extracted_table",
                "rows": profile.get("rows"),
                "columns": profile.get("columns"),
            })

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, filename, file_path, data_profile, source FROM datasets WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    for row in rows:
        if not row["file_path"] or not os.path.exists(row["file_path"]):
            continue
        profile = json.loads(row["data_profile"]) if row["data_profile"] else {}
        datasets.append({
            "id": row["id"],
            "name": row["name"] or row["filename"],
            "filename": row["filename"],
            "source": row["source"] or "upload",
            "rows": profile.get("rows"),
            "columns": profile.get("columns"),
        })

    return datasets


def get_dataset(session_id: str, dataset_id: str | None = None):
    """Charge un jeu de données de la session : (bytes, filename, profile, stats).

    Sans `dataset_id`, renvoie le premier disponible (fichier principal en
    général), ce qui préserve le comportement d'avant le multi-dataset.
    """
    if dataset_id is None:
        available = list_datasets(session_id)
        if not available:
            return None, None, None, None
        dataset_id = available[0]["id"]

    if dataset_id == MAIN_DATASET_ID:
        session = get_session(session_id)
        file_bytes, filename = get_file_bytes(session_id)
        stats = session.get("data_stats") if session else None
        profile = session.get("data_profile") if session else None
        return file_bytes, filename, profile, stats

    if dataset_id == EMBEDDED_DATASET_ID:
        return get_embedded_table(session_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT filename, file_path, data_profile, data_stats FROM datasets WHERE id = ? AND session_id = ?",
        (dataset_id, session_id)
    )
    row = cursor.fetchone()
    conn.close()

    if not row or not row["file_path"] or not os.path.exists(row["file_path"]):
        return None, None, None, None

    with open(row["file_path"], "rb") as f:
        file_bytes = f.read()
    profile = json.loads(row["data_profile"]) if row["data_profile"] else None
    stats = json.loads(row["data_stats"]) if row["data_stats"] else None
    return file_bytes, row["filename"], profile, stats


def get_embedded_table_context(session_id: str) -> str:
    """Bloc de contexte texte pour le prompt du chat, quand une session document
    a un tableau de données attaché : permet de répondre avec des chiffres exacts
    plutôt que de deviner à partir du résumé narratif."""
    _, filename, profile, stats = get_embedded_table(session_id)
    if not profile:
        return ""

    overview = stats.get("dataset_overview", {}) if stats else {}
    variables = stats.get("variables", {}) if stats else {}

    return f"""
TABLEAU DE DONNÉES DÉTECTÉ DANS CE DOCUMENT ({filename}) :
Lignes : {profile['rows']} | Colonnes : {profile['columns']}
Colonnes disponibles : {', '.join(profile['column_names'])}

STATISTIQUES PAR VARIABLE :
{json.dumps(variables, ensure_ascii=False, indent=2)}

APERÇU (5 premières lignes) :
{json.dumps(profile['preview'], ensure_ascii=False, indent=2)}

Si la question porte sur ces données chiffrées, réponds en te basant sur ce tableau (calculs, comparaisons, tendances), en plus des extraits textuels du document.
"""

def get_data_context(session_id: str) -> str:
    session = get_session(session_id)
    if not session or not session.get("data_profile"):
        return ""

    profile = session["data_profile"]
    stats = session["data_stats"]

    overview = stats.get("dataset_overview", {}) if stats else {}
    variables = stats.get("variables", {}) if stats else {}
    missing = stats.get("missing", {}) if stats else {}

    return f"""
CONTEXTE DES DONNÉES EN SESSION :
Fichier : {session['filename']}
Lignes : {profile['rows']} | Colonnes : {profile['columns']}
Colonnes disponibles : {', '.join(profile['column_names'])}
Doublons : {overview.get('n_doublons', profile.get('duplicates', 0))}
Variables numériques : {overview.get('n_variables_numeriques', 0)}
Variables catégorielles : {overview.get('n_variables_categorielles', 0)}
Valeurs manquantes totales : {overview.get('n_valeurs_manquantes_total', 0)}

STATISTIQUES PAR VARIABLE :
{json.dumps(variables, ensure_ascii=False, indent=2)}

VALEURS MANQUANTES :
{json.dumps(missing, ensure_ascii=False, indent=2) if missing else "Aucune."}

APERÇU (5 premières lignes) :
{json.dumps(profile['preview'], ensure_ascii=False, indent=2)}
"""

def save_message_to_report(session_id: str, role: str, text: str, images: list = [], sources: list = []):
    """Sauvegarde ou met à jour les échanges pour le rapport final et l'historique."""
    db_role = "assistant" if role == "model" else role
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Si c'est l'assistant, on tente de mettre à jour le dernier message 'assistant' existant
    # (qui a été créé juste avant par add_to_history)
    if db_role == "assistant":
        cursor.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (session_id,)
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE messages SET content = ?, images = ?, sources = ? WHERE id = ?",
                (text, json.dumps(images), json.dumps(sources), row["id"])
            )
            conn.commit()
            conn.close()
            return

    # Sinon (ou si aucun message trouvé), on insère
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, images, sources) VALUES (?, ?, ?, ?, ?)",
        (session_id, db_role, text, json.dumps(images), json.dumps(sources))
    )
    conn.commit()
    conn.close()

def get_report_data(session_id: str) -> dict:
    session = get_session(session_id)
    if not session:
        return {}
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content as text, images, sources FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    report_messages = []
    for r in rows:
        report_messages.append({
            "role": r["role"],
            "text": r["text"],
            "images": json.loads(r["images"]) if r["images"] else [],
            "sources": json.loads(r["sources"]) if r["sources"] else []
        })
        
    return {
        "messages": report_messages,
        "analysis": session.get("initial_analysis", ""),
        "filename": session.get("filename", ""),
        "images": [
            img
            for msg in report_messages
            for img in msg.get("images", [])
        ],
    }

def save_initial_analysis(session_id: str, text: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET initial_analysis = ? WHERE id = ?", (text, session_id))
    conn.commit()
    conn.close()

def save_profiling_html(session_id: str, html: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET profiling_html = ? WHERE id = ?", (html, session_id))
    conn.commit()
    conn.close()

def get_profiling_html(session_id: str) -> Optional[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT profiling_html FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return row["profiling_html"] if row else None

def save_model_to_db(session_id: str, model_data: dict):
    import base64
    conn = get_db_connection()
    cursor = conn.cursor()
    
    model_id = str(uuid.uuid4())
    name = model_data.get("name", f"modele_{model_id[:8]}")
    metadata = model_data.get("metadata", {})
    
    model_type = metadata.get("model_type", "Unknown")
    features = json.dumps(metadata.get("features", []))
    metrics = json.dumps(metadata.get("metrics", {}))
    
    # Save the base64 content to a physical file
    models_dir = os.path.join(DATA_DIR, "models")
    os.makedirs(models_dir, exist_ok=True)
    file_path = os.path.join(models_dir, f"{model_id}.pkl")
    
    try:
        b64_content = model_data.get("model_b64", "")
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(b64_content))
    except Exception as e:
        print(f"Error saving model file: {e}")
        return
        
    cursor.execute(
        """
        INSERT INTO models (id, session_id, name, type, features, metrics, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (model_id, session_id, name, model_type, features, metrics, file_path)
    )
    conn.commit()
    conn.close()

