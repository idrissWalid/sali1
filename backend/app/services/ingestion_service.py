import io
import pandas as pd
import json
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}

def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in [".csv", ".xlsx", ".xls"]:
        return "tabular"
    elif ext == ".pdf":
        return "document"
    else:
        return "unsupported"

def load_tabular(file_bytes: bytes, filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(pd.io.common.BytesIO(file_bytes))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(file_bytes))

        # Détection colonnes ambiguës
        ambiguous = [
            col for col in df.columns
            if str(col).lower().startswith("col") or 
               str(col).strip().isdigit() or
               len(str(col).strip()) <= 2
        ]

        # Profil de base
        profile = {
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
            "ambiguous_columns": ambiguous,
            "missing_values": df.isnull().sum().to_dict(),
            "duplicates": int(df.duplicated().sum()),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "preview": df.head(5).where(pd.notnull(df), None).to_dict(orient="records")
        }

        return {
            "status": "ok",
            "file_type": "tabular",
            "ambiguous": len(ambiguous) > 0,
            "profile": profile
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def extract_table_from_pdf(file_bytes: bytes):
    """Détecte et extrait un dataset tabulaire au sein d'un PDF (via pdfplumber).

    Retourne un DataFrame si un tableau exploitable est trouvé, sinon None
    (le PDF est alors traité comme un document classique, en repli).
    """
    try:
        import pdfplumber
    except ImportError:
        return None

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            raw_tables = [
                table
                for page in pdf.pages
                for table in page.extract_tables()
                if table and len(table) >= 2 and len(table[0]) >= 2
            ]
    except Exception:
        return None

    if not raw_tables:
        return None

    # On ne garde que les tableaux ayant le même nombre de colonnes que le
    # plus grand d'entre eux : les tableaux d'une autre largeur sont en
    # général des encadrés ou légendes, pas la suite du dataset sur une
    # page suivante.
    largest = max(raw_tables, key=lambda t: len(t) * len(t[0]))
    n_cols = len(largest[0])
    matching_tables = [t for t in raw_tables if len(t[0]) == n_cols]

    header = [str(c).strip() if c is not None else "" for c in matching_tables[0][0]]
    rows = []
    for table in matching_tables:
        table_header = [str(c).strip() if c is not None else "" for c in table[0]]
        body = table[1:] if table_header == header else table
        rows.extend(body)

    if len(rows) < 3:
        return None

    # Noms de colonnes vides ou dupliqués -> noms génériques uniques
    seen = {}
    clean_header = []
    for i, col in enumerate(header):
        name = col or f"col_{i + 1}"
        count = seen.get(name, 0)
        clean_header.append(name if count == 0 else f"{name}_{count}")
        seen[name] = count + 1

    df = pd.DataFrame(rows, columns=clean_header)
    df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)
    df = df.replace("", None)

    # pdfplumber ne renvoie que du texte : on retente une conversion
    # numérique par colonne (nombres à virgule décimale compris).
    for col in df.columns:
        if df[col].isna().all():
            continue
        as_str = df[col].astype(str).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
        converted = pd.to_numeric(as_str, errors="coerce")
        non_null = df[col].notna().sum()
        if non_null > 0 and converted.notna().sum() / non_null >= 0.9:
            df[col] = converted

    return df