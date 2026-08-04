from typing import Optional, List, Dict, Any
import uuid
import os
import json
import sqlite3
from app.core.database import get_db_connection
from app.core.json_utils import dumps_safe

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
            dumps_safe(profile),
            dumps_safe(stats),
            dumps_safe(profile.get("preview")) if profile else None,
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

def delete_session_cascade(session_id: str) -> Optional[dict]:
    """Supprime une session et toutes ses données : messages, jeux de données
    secondaires et modèles suivent via ON DELETE CASCADE (PRAGMA foreign_keys
    activé dans core/database.py). Cette fonction s'occupe en plus de ce que
    SQL ne sait pas faire : les fichiers physiques (dataset principal, tableau
    intégré, datasets secondaires, .pkl des modèles).

    Renvoie {"type": ...} pour laisser l'appelant nettoyer le stockage
    spécifique au type de session (collection ChromaDB, embeddings visuels),
    ou None si la session n'existe pas.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT type, file_path, embedded_table_file_path FROM sessions WHERE id = ?",
        (session_id,)
    )
    session_row = cursor.fetchone()
    if not session_row:
        conn.close()
        return None

    file_paths = [session_row["file_path"], session_row["embedded_table_file_path"]]

    cursor.execute("SELECT file_path FROM datasets WHERE session_id = ?", (session_id,))
    file_paths.extend(row["file_path"] for row in cursor.fetchall())

    cursor.execute("SELECT file_path FROM models WHERE session_id = ?", (session_id,))
    file_paths.extend(row["file_path"] for row in cursor.fetchall())

    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                print(f"Erreur de suppression du fichier {path}: {e}")

    return {"type": session_row["type"]}


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
        (filename, file_path, dumps_safe(profile), dumps_safe(stats), session_id)
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
         dumps_safe(profile), dumps_safe(stats), source)
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
            # Les NOMS, pas seulement le compte : c'est ce qui permet de dire au
            # modèle ce que contiennent les autres fichiers de la session, et de
            # repérer deux fichiers de même structure (voir `jeux_fusionnables`).
            "column_names": profile.get("column_names") or [],
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
                "column_names": profile.get("column_names") or [],
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
            "column_names": profile.get("column_names") or [],
        })

    return datasets


def jeux_fusionnables(session_id: str, dataset_id: str) -> list[dict]:
    """Jeux de la session ayant EXACTEMENT les mêmes colonnes que `dataset_id`.

    Sert à proposer une fusion quand un fichier est manifestement la suite d'un
    autre. La comparaison est stricte — mêmes noms, même ordre : deux tableaux
    qui ne coïncident qu'à peu près ne se concatènent pas sans dégât, et mieux
    vaut ne rien proposer que produire un jeu bancal.
    """
    jeux = list_datasets(session_id)
    reference = next((d for d in jeux if d["id"] == dataset_id), None)
    if not reference or not reference.get("column_names"):
        return []
    signature = list(reference["column_names"])
    return [
        d for d in jeux
        if d["id"] != dataset_id and list(d.get("column_names") or []) == signature
    ]


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


def get_embedded_table_context(session_id: str, model: str | None = None) -> str:
    """Bloc de contexte texte pour le prompt du chat, quand une session document
    a un tableau de données attaché : permet de répondre avec des chiffres exacts
    plutôt que de deviner à partir du résumé narratif.

    Construit dans le budget de contexte du modèle choisi (voir `prompt_budget`) :
    ici le tableau PARTAGE la place avec les extraits du document retrouvés par le
    RAG, la marge est donc plus étroite qu'en session tabulaire."""
    from app.services.prompt_budget import bloc_apercu, bloc_roles, profil_modele, stats_essentielles

    _, filename, profile, stats = get_embedded_table(session_id)
    if not profile:
        return ""

    overview = stats.get("dataset_overview", {}) if stats else {}
    variables = stats_essentielles(stats.get("variables", {}) if stats else {})
    profil = profil_modele(model)

    return f"""
TABLEAU DE DONNÉES DÉTECTÉ DANS CE DOCUMENT ({filename}) :
Lignes : {profile['rows']} | Colonnes : {profile['columns']}
Colonnes disponibles : {', '.join(profile['column_names'])}
{bloc_roles(variables)}
STATISTIQUES PAR VARIABLE :
{dumps_safe(variables, indent=2)}

APERÇU (5 premières lignes) :
{bloc_apercu(profile.get('preview'), budget=profil.budget_contexte // 4)}

Si la question porte sur ces données chiffrées, réponds en te basant sur ce tableau (calculs, comparaisons, tendances), en plus des extraits textuels du document.
"""

def fusionner_jeux(session_id: str, base_id: str, ajout_id: str) -> dict:
    """Concatène deux jeux de même structure en un troisième.

    Les deux sources sont CONSERVÉES : une fusion mal avisée doit pouvoir être
    abandonnée en supprimant simplement le jeu produit. La comparaison des
    colonnes est refaite ici et non tenue pour acquise depuis l'interface — un
    appel direct à l'API ne doit pas pouvoir coller n'importe quoi.
    """
    import io

    import pandas as pd

    from app.services.ingestion_service import load_tabular
    from app.services.profiling_service import generate_profiling_stats

    jeux = {d["id"]: d for d in list_datasets(session_id)}
    if base_id not in jeux or ajout_id not in jeux:
        return {"status": "error", "message": "Jeu de données introuvable dans cette session."}
    if base_id == ajout_id:
        return {"status": "error", "message": "Les deux jeux à fusionner sont identiques."}

    colonnes_base = list(jeux[base_id].get("column_names") or [])
    if not colonnes_base or colonnes_base != list(jeux[ajout_id].get("column_names") or []):
        return {"status": "error",
                "message": "Les deux fichiers n'ont pas exactement les mêmes colonnes."}

    def charger(dataset_id: str):
        octets, nom, _, _ = get_dataset(session_id, dataset_id)
        if not octets:
            return None
        if (nom or "").lower().endswith(".csv"):
            return pd.read_csv(io.BytesIO(octets))
        return pd.read_excel(io.BytesIO(octets))

    try:
        gauche, droite = charger(base_id), charger(ajout_id)
    except Exception as exc:
        return {"status": "error", "message": f"Lecture impossible : {exc}"}
    if gauche is None or droite is None:
        return {"status": "error", "message": "Fichier introuvable sur le disque."}

    fusion = pd.concat([gauche, droite], ignore_index=True)
    csv_bytes = fusion.to_csv(index=False).encode("utf-8")

    base_nom = os.path.splitext(jeux[base_id].get("filename") or "donnees")[0]
    filename = f"{base_nom}_fusionne.csv"

    controle = load_tabular(csv_bytes, filename)
    if controle.get("status") != "ok":
        return {"status": "error",
                "message": controle.get("message", "Le fichier fusionné est illisible.")}

    dataset_id = add_dataset(
        session_id, csv_bytes, filename,
        controle["profile"], generate_profiling_stats(fusion),
        name=f"{jeux[base_id].get('name')} + {jeux[ajout_id].get('name')}",
        source="merge",
    )
    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "filename": filename,
        "rows": int(len(fusion)),
        "columns": int(len(fusion.columns)),
    }


def get_data_context(session_id: str, model: str | None = None,
                     dataset_id: str | None = None) -> str:
    """Contexte de données injecté dans le prompt du chat.

    Reconstruit à CHAQUE message : tout caractère superflu ici est rejoué à chaque
    tour, sur tous les backends. D'où la construction dans le budget du modèle
    choisi (voir `prompt_budget`) plutôt qu'un dump intégral raccourci en aval par
    une coupe aveugle au milieu du JSON.

    Une session peut porter plusieurs fichiers (un jeu de données et ses
    métadonnées, une suite…). Seul le jeu ACTIF est décrit en entier ; les autres
    sont annoncés en une ligne — assez pour que le modèle sache qu'ils existent
    sans que le prompt triple de volume à chaque message.
    """
    from app.services.prompt_budget import bloc_apercu, bloc_roles, profil_modele, stats_essentielles

    session = get_session(session_id)
    if not session:
        return ""

    jeux = list_datasets(session_id)
    if not jeux:
        return ""

    # Jeu « actif » : celui que l'utilisateur consulte, sinon le premier (le
    # fichier principal). Lui seul est décrit en entier.
    connus = {d["id"] for d in jeux}
    if dataset_id not in connus:
        dataset_id = jeux[0]["id"]

    _, filename, profile, stats = get_dataset(session_id, dataset_id)
    if not profile:
        return ""

    overview = stats.get("dataset_overview", {}) if stats else {}
    variables = stats_essentielles(stats.get("variables", {}) if stats else {})
    missing = stats.get("missing", {}) if stats else {}
    profil = profil_modele(model)

    return f"""
CONTEXTE DES DONNÉES EN SESSION :
Fichier : {filename}
Lignes : {profile.get('rows')} | Colonnes : {profile.get('columns')}
Colonnes disponibles : {', '.join(profile.get('column_names') or [])}
Doublons : {overview.get('n_doublons', profile.get('duplicates', 0))}
Variables numériques : {overview.get('n_variables_numeriques', 0)}
Variables catégorielles : {overview.get('n_variables_categorielles', 0)}
Valeurs manquantes totales : {overview.get('n_valeurs_manquantes_total', 0)}
{bloc_roles(variables)}
STATISTIQUES PAR VARIABLE :
{dumps_safe(variables, indent=2)}

VALEURS MANQUANTES :
{dumps_safe(missing, indent=2) if missing else "Aucune."}

APERÇU (5 premières lignes) :
{bloc_apercu(profile.get('preview'), budget=profil.budget_contexte // 3)}
{bloc_autres_jeux(jeux, dataset_id)}"""


def bloc_autres_jeux(jeux: list[dict], actif_id: str) -> str:
    """Les AUTRES fichiers de la session, en une ligne chacun.

    Volontairement réduit au nom, à la taille et aux colonnes : le contexte est
    rejoué à chaque message, et décrire trois fichiers en entier saturerait un
    modèle local avant même la question. C'est assez pour que le modèle sache
    qu'ils existent et propose un croisement — l'utilisateur bascule ensuite sur
    celui qu'il veut interroger.
    """
    autres = [d for d in jeux if d["id"] != actif_id]
    if not autres:
        return ""

    lignes = []
    for jeu in autres:
        colonnes = jeu.get("column_names") or []
        apercu = ", ".join(colonnes[:8])
        if len(colonnes) > 8:
            apercu += f", … (+{len(colonnes) - 8})"
        taille = f"{jeu.get('rows')} lignes, {jeu.get('columns')} colonnes"
        lignes.append(f"- « {jeu.get('name')} » : {taille}"
                      + (f"\n  Colonnes : {apercu}" if apercu else ""))

    return f"""
AUTRES FICHIERS DE CETTE SESSION :
{chr(10).join(lignes)}

Tu sais qu'ils existent et tu peux suggérer de les croiser avec le fichier
ci-dessus, mais tu n'as PAS leur contenu : ne cite aucun chiffre à leur sujet.
Pour les analyser, l'utilisateur doit les sélectionner dans le tableau de bord.
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
    features = dumps_safe(metadata.get("features", []))
    metrics = dumps_safe(metadata.get("metrics", {}))
    
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
        return None

    cursor.execute(
        """
        INSERT INTO models (id, session_id, name, type, features, metrics, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (model_id, session_id, name, model_type, features, metrics, file_path)
    )
    conn.commit()
    conn.close()
    return model_id


def save_timeseries_model_to_db(
    session_id: str,
    name: str,
    report: dict,
    forecast_image_b64: Optional[str] = None,
    engine: str = "sarima",
) -> str:
    """Persiste un modèle de série temporelle (ARIMA/SARIMA ou prévision automatique).

    Le rapport complet (metrics.json de la méthodologie) est stocké tel quel dans
    la colonne `metrics`. Le graphique de
    prévision est intégré en base64 sous la clé `forecast_chart` pour que le
    dashboard l'affiche sans endpoint supplémentaire. `type` vaut "timeseries"
    afin que le frontend bascule sur la vue dédiée.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    model_id = str(uuid.uuid4())
    stored_report = dict(report or {})
    stored_report["_engine"] = engine
    if forecast_image_b64:
        stored_report["forecast_chart"] = forecast_image_b64

    cursor.execute(
        """
        INSERT INTO models (id, session_id, name, type, features, metrics, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            model_id,
            session_id,
            name,
            "timeseries",
            json.dumps([]),
            dumps_safe(stored_report),
            None,
        ),
    )
    conn.commit()
    conn.close()
    return model_id



def save_supervised_model_to_db(session_id: str, name: str, report: dict,
                                model_b64: Optional[str] = None) -> str:
    """Persiste un modèle issu du tournoi supervisé (régression / classification).

    `type` vaut "supervised" pour que le frontend bascule sur la vue dédiée,
    distincte de celle des séries temporelles. Le rapport complet (hypothèses
    testées, candidats comparés, verdict) est stocké tel quel dans `metrics`.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    model_id = str(uuid.uuid4())
    # Le pipeline sérialisé rend le modèle réutilisable : simulation et export.
    file_path = None
    if model_b64:
        import base64

        models_dir = os.path.join(DATA_DIR, "models")
        os.makedirs(models_dir, exist_ok=True)
        file_path = os.path.join(models_dir, f"{model_id}.pkl")
        try:
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(model_b64))
        except Exception:
            file_path = None

    # Colonnes BRUTES attendues par le pipeline (et non les colonnes encodées) :
    # c'est ce que le formulaire de simulation doit demander à l'utilisateur.
    artefact = (report or {}).get("artefact") or {}
    variables = artefact.get("colonnes_attendues") or (report or {}).get("variables") or []
    cursor.execute(
        """
        INSERT INTO models (id, session_id, name, type, features, metrics, file_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            model_id,
            session_id,
            name,
            "supervised",
            dumps_safe(variables),
            dumps_safe(report or {}),
            file_path,
        ),
    )
    conn.commit()
    conn.close()
    return model_id
