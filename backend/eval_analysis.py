"""eval_analysis.py — Évaluation de l'agent d'analyse de données sur InfiAgent-DABench.

Pendant de `eval_server.py` (qui, lui, évalue le RÉSUMÉ de documents sur
MultiEURLEX). Ici on mesure la capacité à répondre à des questions d'analyse en
forme fermée : chaque question porte sur un CSV, impose un gabarit de réponse
`@nom[valeur]`, et la réponse attendue est connue. Le score est un exact match.

Protocole amont (InfiAgent/examples/DA-Agent) — trois fichiers à récupérer :
    data/da-dev-questions.jsonl   id, question, concepts, constraints, format,
                                  file_name, level
    data/da-dev-labels.jsonl      id, common_answers = [[nom, valeur], ...]
    data/da-dev-tables/           les CSV référencés par file_name

Ce script pilote l'API Sali AI de bout en bout, comme le ferait un utilisateur :
    POST /api/upload   une fois par CSV      → session_id
    POST /api/chat     une fois par question → réponse en langage naturel

Les questions sont groupées par fichier : un même CSV porte souvent plusieurs
questions, et le ré-uploader à chaque fois relancerait tout le profilage.

Sortie : un JSON de résultats détaillés, et un `responses.jsonl` au format
attendu par le scorer amont `eval_closed_form.py`, pour qui veut le chiffre
officiel plutôt que celui recalculé ici (cf. --help).

Exemple :
    python eval_analysis.py --data-dir data --limit 20
"""

import argparse
import io
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

DEFAULT_API_BASE = "http://127.0.0.1:8000"
UPLOAD_TIMEOUT = 900      # le profilage ydata d'un gros CSV peut être long
CHAT_TIMEOUT = 900        # une question peut déclencher du code en sandbox
REQUEST_DELAY = 0.2


# ═══════════════════════════════════════════════════════════════════════════
#  CHARGEMENT DU JEU D'ÉVALUATION
# ═══════════════════════════════════════════════════════════════════════════
def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no} — JSON invalide : {exc}")
    return rows


def build_prompt(question: dict, language: str = "en") -> str:
    """Question + contraintes + gabarit de sortie.

    Les champs `constraints` et `format` ne sont pas décoratifs : c'est le seul
    moyen d'obtenir une réponse parsable. Sans eux, le scorer amont ne trouve
    aucun `@nom[valeur]` à comparer et tout le jeu tombe à zéro.

    L'enrobage suit la langue demandée : le jeu DABench est en anglais, et
    mélanger une question anglaise à des consignes françaises brouille le
    respect du gabarit — ce qui pénaliserait l'agent sur la forme plutôt que
    sur le fond.
    """
    parts = [str(question.get("question", "")).strip()]
    constraints = str(question.get("constraints", "")).strip()
    fmt = str(question.get("format", "")).strip()

    if language == "fr":
        label, instruction = "Contraintes", (
            "Réponds en respectant EXACTEMENT ce format, sans rien y ajouter :")
    else:
        label, instruction = "Constraints", (
            "Answer using EXACTLY this format, adding nothing to it:")

    if constraints:
        parts.append(f"\n{label} : {constraints}")
    if fmt:
        parts.append(f"\n{instruction}\n{fmt}")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
#  APPELS API
# ═══════════════════════════════════════════════════════════════════════════
def upload_csv(api_base: str, csv_path: Path, model: str | None,
               with_interpretation: bool) -> str:
    """Crée une session à partir d'un CSV et renvoie son `session_id`.

    `/api/upload` répond en NDJSON : une ligne de progression par étape, puis
    une ligne `completed` qui porte la charge utile.
    """
    data = {
        "index_doc": "false",
        "skip_interpretation": "false" if with_interpretation else "true",
    }
    if model:
        data["model"] = model

    with csv_path.open("rb") as handle:
        payload = handle.read()

    response = requests.post(
        f"{api_base}/api/upload",
        data=data,
        files={"file": (csv_path.name, io.BytesIO(payload), "text/csv")},
        timeout=UPLOAD_TIMEOUT,
    )
    response.raise_for_status()

    for line in response.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("status") == "error":
            raise RuntimeError(event.get("technical") or event.get("message", "upload échoué"))
        if event.get("status") == "completed":
            session_id = event.get("data", {}).get("session_id")
            if not session_id:
                raise RuntimeError("réponse d'upload sans session_id")
            return session_id

    raise RuntimeError("flux d'upload terminé sans statut 'completed'")


def ask_question(api_base: str, session_id: str, message: str, model: str | None,
                 language: str = "en") -> str:
    body = {"session_id": session_id, "message": message, "language": language}
    if model:
        body["model"] = model
    response = requests.post(f"{api_base}/api/chat", json=body, timeout=CHAT_TIMEOUT)
    response.raise_for_status()
    return response.json().get("response", "")


# ═══════════════════════════════════════════════════════════════════════════
#  EXTRACTION ET COMPARAISON DES RÉPONSES
# ═══════════════════════════════════════════════════════════════════════════
ANSWER_PATTERN = re.compile(r"@([A-Za-z0-9_\- ]+?)\s*\[([^\]]*)\]")


def parse_answers(text: str) -> dict[str, str]:
    """Extrait les `@nom[valeur]` d'une réponse.

    En cas de doublon on garde la DERNIÈRE occurrence : quand le modèle
    raisonne à voix haute avant de conclure, la valeur finale est la bonne.
    """
    found = {}
    for name, value in ANSWER_PATTERN.findall(text or ""):
        found[name.strip().lower()] = value.strip()
    return found


_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _as_float(value: str):
    """Convertit en flottant si la valeur est numérique, sinon None.

    Tolère le séparateur décimal français, les %, les espaces d'unités et le
    texte autour du nombre (« environ 12,50 € »).
    """
    if value is None:
        return None
    cleaned = str(value).strip().replace(" ", "").replace(" ", "")
    cleaned = cleaned.rstrip("%").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        pass
    match = _NUMBER.search(str(value).replace(" ", ""))
    if match:
        try:
            return float(match.group().replace(",", "."))
        except ValueError:
            return None
    return None


def answers_match(expected: str, got: str, tolerance: float) -> bool:
    if got is None:
        return False
    exp_f, got_f = _as_float(expected), _as_float(got)
    if exp_f is not None and got_f is not None:
        return abs(exp_f - got_f) <= tolerance
    return str(expected).strip().lower() == str(got).strip().lower()


def grade(question: dict, label: dict, response_text: str, tolerance: float) -> dict:
    """Une question est juste si TOUS ses sous-champs attendus le sont."""
    produced = parse_answers(response_text)
    expected_pairs = label.get("common_answers") or []

    subs = []
    for pair in expected_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        name, expected = str(pair[0]).strip().lower(), pair[1]
        got = produced.get(name)
        subs.append({
            "answer_name": name,
            "expected": expected,
            "got": got,
            "correct": answers_match(expected, got, tolerance),
        })

    return {
        "id": question.get("id"),
        "file_name": question.get("file_name"),
        "level": question.get("level"),
        "concepts": question.get("concepts"),
        "correct": bool(subs) and all(s["correct"] for s in subs),
        "parsed_any": bool(produced),
        "sub_answers": subs,
        "response": response_text,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  AGRÉGATION
# ═══════════════════════════════════════════════════════════════════════════
def score(items: list[dict], field: str = "correct") -> dict:
    """Taux ET effectifs.

    Un pourcentage seul est intrompable : « 100 % » sur deux questions ne dit
    pas la même chose que sur quatre-vingts. Chaque score porte donc son
    numérateur et son dénominateur, jusque dans le JSON exporté.
    """
    total = len(items)
    correct = sum(bool(i.get(field)) for i in items)
    return {
        "rate": round(correct / total, 4) if total else None,
        "correct": correct,
        "total": total,
    }


def summarize(graded: list[dict], errors: list[dict]) -> dict:
    by_level, by_concept = defaultdict(list), defaultdict(list)
    for item in graded:
        by_level[str(item.get("level"))].append(item)
        concepts = item.get("concepts")
        if isinstance(concepts, str):
            concepts = [concepts]
        for concept in concepts or ["(sans concept)"]:
            by_concept[str(concept)].append(item)

    accuracy = score(graded)
    fmt = score(graded, "parsed_any")

    return {
        "n_questions": len(graded) + len(errors),
        "n_graded": len(graded),
        "n_errors": len(errors),
        # Le dénominateur est le nombre de questions RÉELLEMENT notées : une
        # question en erreur réseau n'est pas une mauvaise réponse du modèle.
        "accuracy": accuracy["rate"],
        "n_correct": accuracy["correct"],
        "format_compliance": fmt["rate"],
        "n_format_ok": fmt["correct"],
        "accuracy_by_level": {k: score(v) for k, v in sorted(by_level.items())},
        "accuracy_by_concept": {k: score(v) for k, v in sorted(by_concept.items())},
    }


# ═══════════════════════════════════════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Évalue l'agent d'analyse de données sur InfiAgent-DABench.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Pour le score officiel amont, passer le responses.jsonl produit ici à :\n"
            "  python eval_closed_form.py --questions_file_path da-dev-questions.jsonl \\\n"
            "      --labels_file_path da-dev-labels.jsonl --responses_file_path responses.jsonl"
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="dossier contenant da-dev-questions.jsonl, da-dev-labels.jsonl et da-dev-tables/")
    parser.add_argument("--questions", type=Path, help="chemin explicite du fichier de questions")
    parser.add_argument("--labels", type=Path, help="chemin explicite du fichier de labels")
    parser.add_argument("--tables", type=Path, help="chemin explicite du dossier de CSV")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="racine de l'API Sali AI")
    parser.add_argument("--model", default=None, help="modèle LLM à évaluer (défaut : celui du backend)")
    parser.add_argument("--limit", type=int, default=0, help="n'évaluer que les N premières questions (0 = toutes)")
    parser.add_argument("--tolerance", type=float, default=1e-6,
                        help="écart absolu toléré entre deux valeurs numériques")
    parser.add_argument("--with-interpretation", action="store_true",
                        help="laisser l'upload produire son texte d'accueil (2 appels LLM de plus par CSV)")
    parser.add_argument("--language", choices=["en", "fr"], default="en",
                        help="langue des réponses de l'agent (défaut : en, comme le jeu DABench)")
    parser.add_argument("--out", type=Path, default=Path("eval_analysis_results.json"))
    parser.add_argument("--responses-out", type=Path, default=Path("responses.jsonl"))
    args = parser.parse_args()

    questions_path = args.questions or args.data_dir / "da-dev-questions.jsonl"
    labels_path = args.labels or args.data_dir / "da-dev-labels.jsonl"
    tables_dir = args.tables or args.data_dir / "da-dev-tables"

    for path in (questions_path, labels_path):
        if not path.is_file():
            print(f"✗ Fichier introuvable : {path}", file=sys.stderr)
            print("  Récupérer le jeu DABench : https://huggingface.co/datasets/infiagent/DAEval",
                  file=sys.stderr)
            return 1
    if not tables_dir.is_dir():
        print(f"✗ Dossier de CSV introuvable : {tables_dir}", file=sys.stderr)
        return 1

    try:
        requests.get(f"{args.api_base}/health", timeout=10).raise_for_status()
    except Exception as exc:
        print(f"✗ Backend injoignable sur {args.api_base} : {exc}", file=sys.stderr)
        print("  Lancer d'abord : python run_server.py", file=sys.stderr)
        return 1

    questions = load_jsonl(questions_path)
    labels = {str(row.get("id")): row for row in load_jsonl(labels_path)}
    if args.limit:
        questions = questions[: args.limit]

    # Groupement par CSV : un upload par fichier, pas un par question.
    by_file = defaultdict(list)
    for question in questions:
        by_file[str(question.get("file_name"))].append(question)

    print(f"▶ {len(questions)} questions sur {len(by_file)} fichiers — modèle : {args.model or 'défaut backend'}"
          f" — langue : {args.language}")
    if not args.with_interpretation:
        print("  (upload sans texte d'accueil : --with-interpretation pour le réactiver)")

    graded, errors = [], []
    started = time.time()
    done = 0

    for file_name, file_questions in sorted(by_file.items()):
        csv_path = tables_dir / file_name
        if not csv_path.is_file():
            for question in file_questions:
                errors.append({"id": question.get("id"), "file_name": file_name,
                               "error": "CSV introuvable"})
            done += len(file_questions)
            print(f"  ✗ {file_name} — CSV introuvable ({len(file_questions)} questions ignorées)")
            continue

        try:
            session_id = upload_csv(args.api_base, csv_path, args.model,
                                    args.with_interpretation)
        except Exception as exc:
            for question in file_questions:
                errors.append({"id": question.get("id"), "file_name": file_name,
                               "error": f"upload : {exc}"})
            done += len(file_questions)
            print(f"  ✗ {file_name} — upload échoué : {exc}")
            continue

        for question in file_questions:
            done += 1
            qid = str(question.get("id"))
            label = labels.get(qid)
            if label is None:
                errors.append({"id": qid, "file_name": file_name, "error": "label absent"})
                continue

            try:
                answer = ask_question(args.api_base, session_id,
                                      build_prompt(question, args.language),
                                      args.model, args.language)
            except Exception as exc:
                errors.append({"id": qid, "file_name": file_name, "error": f"chat : {exc}"})
                print(f"  ✗ [{done}/{len(questions)}] q{qid} — {exc}")
                continue

            result = grade(question, label, answer, args.tolerance)
            graded.append(result)

            elapsed = time.time() - started
            eta = elapsed / done * (len(questions) - done)
            flag = "✓" if result["correct"] else ("~" if result["parsed_any"] else "✗")
            print(f"  {flag} [{done}/{len(questions)}] q{qid} ({file_name})  ETA {eta/60:.1f} min")
            time.sleep(REQUEST_DELAY)

    summary = summarize(graded, errors)
    summary["model"] = args.model or "(défaut backend)"
    summary["total_time_s"] = round(time.time() - started, 1)
    summary["with_interpretation"] = args.with_interpretation
    summary["language"] = args.language

    args.out.write_text(
        json.dumps({"summary": summary, "results": graded, "errors": errors},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with args.responses_out.open("w", encoding="utf-8") as handle:
        for item in graded:
            handle.write(json.dumps({"id": item["id"], "response": item["response"]},
                                    ensure_ascii=False) + "\n")

    def as_pct(rate) -> str:
        return "—" if rate is None else f"{rate * 100:.1f}%"

    def as_frac(entry: dict) -> str:
        return f"{as_pct(entry['rate'])} ({entry['correct']}/{entry['total']})"

    print("\n" + "═" * 60)
    print(f"  Questions notées   : {summary['n_graded']} (erreurs : {summary['n_errors']})")
    print(f"  Accuracy           : {as_pct(summary['accuracy'])} "
          f"({summary['n_correct']}/{summary['n_graded']})")
    print(f"  Respect du format  : {as_pct(summary['format_compliance'])} "
          f"({summary['n_format_ok']}/{summary['n_graded']})")
    print("  Par niveau :")
    for key, entry in summary["accuracy_by_level"].items():
        print(f"    {key:<12} {as_frac(entry)}")
    print("  Par concept :")
    for key, entry in summary["accuracy_by_concept"].items():
        print(f"    {key:<34} {as_frac(entry)}")
    print(f"  Durée              : {summary['total_time_s']} s")
    print("═" * 60)
    print(f"→ {args.out}")
    print(f"→ {args.responses_out}  (pour le scorer amont eval_closed_form.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
