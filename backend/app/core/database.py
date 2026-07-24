import os
import sqlite3

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data"))
DB_PATH = os.path.join(DB_DIR, "sessions.db")

def get_db_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        title TEXT,
        type TEXT DEFAULT 'tabular',
        filename TEXT,
        data_profile TEXT,
        data_stats TEXT,
        data_preview TEXT,
        profiling_html TEXT,
        initial_analysis TEXT,
        file_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Migration légère : dataset secondaire attaché à une session document
    # (tableau détecté dans un rapport PDF, conservé à côté du résumé/RAG).
    existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(sessions)").fetchall()}
    embedded_table_columns = {
        "embedded_table_filename": "TEXT",
        "embedded_table_file_path": "TEXT",
        "embedded_table_profile": "TEXT",
        "embedded_table_stats": "TEXT",
    }
    for column, column_type in embedded_table_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {column} {column_type}")

    # Create messages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        images TEXT,
        sources TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
    );
    """)

    # Datasets additionnels rattachés à une session. Le fichier principal et le
    # tableau extrait d'un PDF restent portés par les colonnes de `sessions`
    # (aucune migration de l'existant n'est donc nécessaire) : cette table
    # accueille les jeux de données ajoutés ensuite à une même session.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS datasets (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        name TEXT,
        filename TEXT,
        file_path TEXT,
        data_profile TEXT,
        data_stats TEXT,
        source TEXT DEFAULT 'upload',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
    );
    """)

    # Create models table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS models (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        name TEXT,
        type TEXT,
        features TEXT,
        metrics TEXT,
        file_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()
