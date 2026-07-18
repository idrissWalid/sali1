import pandas as pd
import json
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".docx", ".md", ".txt"}

def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in [".csv", ".xlsx", ".xls"]:
        return "tabular"
    elif ext in [".pdf", ".docx", ".md", ".txt"]:
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