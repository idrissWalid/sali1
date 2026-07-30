"""download_dabench.py — Récupère le jeu d'évaluation InfiAgent-DABench.

Les trois éléments attendus par `eval_analysis.py` / `eval_analysis_server.py` :

    data/da-dev-questions.jsonl    (~212 Ko)
    data/da-dev-labels.jsonl       (~23 Ko)
    data/da-dev-tables/*.csv       (68 fichiers, ~60 Mo)

Source : le dépôt GitHub InfiAgent, dossier examples/DA-Agent/data. Un seul
appel à l'API GitHub sert à lister les CSV ; tout le reste passe par
raw.githubusercontent.com, qui n'est pas soumis au quota de 60 requêtes/heure.

Le script est ré-exécutable : les fichiers déjà présents et de taille correcte
sont ignorés, ce qui permet de reprendre un téléchargement interrompu.

    python download_dabench.py
    python download_dabench.py --dest data --force
"""

import argparse
import os
import sys
from pathlib import Path

import certifi

# La machine Windows de dev ne parvient pas toujours à lire son magasin de
# certificats système (échec ASN.1) : on force certifi, comme le fait déjà
# run_server.py. Sans ça, chaque requête HTTPS échoue en SSLCertVerificationError.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import requests

API_DIR = "https://api.github.com/repos/InfiAgent/InfiAgent/contents/examples/DA-Agent/data"
RAW_BASE = "https://raw.githubusercontent.com/InfiAgent/InfiAgent/main/examples/DA-Agent/data"
JSONL_FILES = ["da-dev-questions.jsonl", "da-dev-labels.jsonl"]
TIMEOUT = 120


def human(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Go"


def fetch(url: str, dest: Path, expected_size: int | None, force: bool) -> tuple[bool, int]:
    """Télécharge `url` vers `dest`. Renvoie (téléchargé, octets écrits).

    Un fichier déjà présent à la bonne taille est laissé tel quel : c'est ce qui
    rend le script relançable après une coupure.
    """
    if dest.exists() and not force:
        actual = dest.stat().st_size
        if expected_size is None or actual == expected_size:
            return False, actual

    response = requests.get(url, timeout=TIMEOUT, stream=True)
    response.raise_for_status()

    # Écriture dans un fichier temporaire puis renommage : une coupure en plein
    # téléchargement ne laisse pas un CSV tronqué que la relance croirait complet.
    tmp = dest.with_suffix(dest.suffix + ".part")
    written = 0
    with tmp.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            handle.write(chunk)
            written += len(chunk)
    tmp.replace(dest)
    return True, written


def main() -> int:
    parser = argparse.ArgumentParser(description="Télécharge le jeu InfiAgent-DABench.")
    parser.add_argument("--dest", type=Path, default=Path("data"),
                        help="dossier de destination (défaut : data)")
    parser.add_argument("--force", action="store_true",
                        help="re-télécharger même si le fichier existe déjà")
    args = parser.parse_args()

    tables_dir = args.dest / "da-dev-tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    print(f"-> Destination : {args.dest.resolve()}")

    # ── Questions et labels ────────────────────────────────────────────────
    for name in JSONL_FILES:
        try:
            downloaded, size = fetch(f"{RAW_BASE}/{name}", args.dest / name, None, args.force)
        except Exception as exc:
            print(f"  [ERREUR] {name} : {exc}", file=sys.stderr)
            return 1
        print(f"  {'[dl]' if downloaded else '[ok]'} {name}  ({human(size)})")

    # ── Liste des CSV ──────────────────────────────────────────────────────
    print("-> Liste des tables...")
    try:
        response = requests.get(f"{API_DIR}/da-dev-tables", timeout=TIMEOUT)
        response.raise_for_status()
        entries = response.json()
    except Exception as exc:
        print(f"  [ERREUR] Impossible de lister les tables : {exc}", file=sys.stderr)
        return 1

    if isinstance(entries, dict):
        # L'API renvoie un objet (et non une liste) quand elle refuse la requête,
        # typiquement au dépassement du quota anonyme.
        print(f"  [ERREUR] Reponse inattendue de l'API GitHub : {entries.get('message')}", file=sys.stderr)
        return 1

    csvs = [e for e in entries if e.get("type") == "file"]
    total = sum(e.get("size", 0) for e in csvs)
    print(f"  {len(csvs)} fichiers, {human(total)} au total")

    n_new = n_skip = 0
    for i, entry in enumerate(csvs, 1):
        name = entry["name"]
        try:
            downloaded, _ = fetch(f"{RAW_BASE}/da-dev-tables/{name}",
                                  tables_dir / name, entry.get("size"), args.force)
        except Exception as exc:
            print(f"  [ERREUR] [{i}/{len(csvs)}] {name} : {exc}", file=sys.stderr)
            return 1
        if downloaded:
            n_new += 1
            print(f"  [dl] [{i}/{len(csvs)}] {name}  ({human(entry.get('size', 0))})")
        else:
            n_skip += 1

    print(f"\n[OK] Termine - {n_new} telecharges, {n_skip} deja presents.")
    print(f"  Lancer l'evaluation :  python eval_analysis_server.py   (dossier : {args.dest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
