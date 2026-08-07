import io
import pandas as pd
import json
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".docx", ".md", ".tex"}

def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in [".csv", ".xlsx", ".xls"]:
        return "tabular"
    elif ext in [".pdf", ".docx", ".md", ".tex"]:
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


# Un classeur à plusieurs feuilles n'est pas un tableau : c'est un dossier de
# tableaux. `pd.read_excel` sans `sheet_name` n'en lit que le premier, en
# silence — et la première feuille d'un classeur institutionnel est souvent une
# page de garde. Chaque feuille exploitable devient donc un jeu de données à
# part entière, converti en CSV pour que toute la chaîne (profilage, sandbox,
# modèles) la lise comme n'importe quel autre fichier.
MAX_FEUILLES = 12


def _feuille_exploitable(df) -> bool:
    """Une feuille porte-t-elle un tableau, ou seulement du décor ?

    Deux colonnes suffisent à faire un tableau. Une colonne unique n'en est un
    que si elle est longue — sinon c'est une couverture, un titre ou une note.
    Heuristique assumée : le détail des feuilles écartées est renvoyé à
    l'utilisateur, qui garde le dernier mot.
    """
    lignes, colonnes = len(df), len(df.columns)
    if lignes == 0 or colonnes == 0:
        return False
    return colonnes >= 2 or lignes >= 10


def _nom_de_fichier_sur(base: str, feuille: str) -> str:
    """Nom de fichier lisible et sans caractère interdit, en .csv.

    L'extension n'est pas cosmétique : toute la chaîne choisit son lecteur
    (`read_csv` / `read_excel`) d'après elle.
    """
    brut = f"{base} — {feuille}"
    propre = "".join(c if (c.isalnum() or c in " -_—().") else "_" for c in brut)
    return propre.strip()[:120] + ".csv"


def decouper_classeur(file_bytes: bytes, filename: str) -> dict | None:
    """Découpe un classeur multi-feuilles en jeux de données indépendants.

    Renvoie None si le fichier n'est pas un classeur ou n'a qu'une feuille —
    le comportement reste alors strictement celui d'avant.

    Sinon : {"feuilles": [{nom, nom_affichage, filename, bytes, rows, columns}],
             "ignorees": [noms], "total": n}
    """
    if Path(filename).suffix.lower() not in (".xlsx", ".xls"):
        return None

    try:
        classeur = pd.ExcelFile(io.BytesIO(file_bytes))
    except Exception:
        return None  # illisible ici : l'erreur sera rapportée par load_tabular

    noms = list(classeur.sheet_names)
    if len(noms) <= 1:
        return None

    base = Path(filename).stem
    retenues, ignorees, premiere_non_vide = [], [], None

    for nom in noms:
        try:
            df = classeur.parse(nom)
        except Exception:
            ignorees.append(nom)
            continue

        # Lignes et colonnes entièrement vides : fréquentes dans les classeurs
        # mis en forme à la main, elles fausseraient le test d'exploitabilité.
        df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
        if len(df) and len(df.columns) and premiere_non_vide is None:
            premiere_non_vide = (nom, df)

        if not _feuille_exploitable(df):
            ignorees.append(nom)
            continue

        retenues.append({
            "nom": nom,
            "nom_affichage": f"{base} — {nom}",
            "filename": _nom_de_fichier_sur(base, nom),
            "bytes": df.to_csv(index=False).encode("utf-8"),
            "rows": len(df),
            "columns": len(df.columns),
        })

    # Filet de sécurité : si l'heuristique a tout écarté, on garde la première
    # feuille non vide. Mieux vaut un tableau discutable que rien du tout.
    if not retenues and premiere_non_vide:
        nom, df = premiere_non_vide
        ignorees = [n for n in ignorees if n != nom]
        retenues.append({
            "nom": nom,
            "nom_affichage": f"{base} — {nom}",
            "filename": _nom_de_fichier_sur(base, nom),
            "bytes": df.to_csv(index=False).encode("utf-8"),
            "rows": len(df),
            "columns": len(df.columns),
        })

    if not retenues:
        return None

    if len(retenues) > MAX_FEUILLES:
        ignorees.extend(f["nom"] for f in retenues[MAX_FEUILLES:])
        retenues = retenues[:MAX_FEUILLES]

    return {"feuilles": retenues, "ignorees": ignorees, "total": len(noms)}


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
