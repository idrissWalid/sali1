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
    payload = response.json()
    answer = str(payload.get("response", ""))
    # Certains providers sont actuellement normalisés par /api/chat en HTTP 200
    # avec une chaîne « Erreur <provider> : ... ». Une évaluation ne doit jamais
    # transformer une panne/quota en réponse vide puis en score nul.
    if re.match(r"^\s*Erreur\s+[A-Za-z0-9_-]+\s*:", answer, re.I):
        raise RuntimeError(answer.strip())
    return answer


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
def main_dabench() -> int:
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


# =============================================================================
#  INSIGHTEVAL (Zhu et al., ACL 2026 / arXiv:2511.22884v2)
# =============================================================================

INSIGHTEVAL_ANNOTATIONS_URL = (
    "https://huggingface.co/datasets/zhenghaozhu/InsightEval/resolve/main/"
    "annotations.jsonl"
)
INSIGHTEVAL_FILE_URL = (
    "https://huggingface.co/datasets/zhenghaozhu/InsightEval/resolve/main/{path}"
)
PROJECT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INSIGHTBENCH_TABLES_DIR = Path(__file__).resolve().parent / "data" / "insightbench" / "csvs"


def _download(url: str, destination: Path) -> Path:
    """Télécharge un fichier de benchmark de façon atomique."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temporary.replace(destination)
    return destination


def load_insighteval_annotations(path: Path, allow_download: bool = True) -> list[dict]:
    if not path.is_file():
        if not allow_download:
            raise FileNotFoundError(f"Annotations InsightEval introuvables : {path}")
        print(f"[download] Annotations InsightEval vers {path}")
        _download(INSIGHTEVAL_ANNOTATIONS_URL, path)
    rows = load_jsonl(path)
    required = {"instance_id", "goal", "insights", "summary", "table_path"}
    for line_number, row in enumerate(rows, 1):
        missing = required.difference(row)
        if missing:
            raise ValueError(
                f"Annotation {line_number} incomplète, champs absents : {sorted(missing)}"
            )
    return rows


def resolve_insighteval_table(
    annotation: dict,
    search_dirs: list[Path],
    cache_dir: Path,
    allow_download: bool = True,
) -> Path:
    """Retrouve une table locale, y compris si SALI a préfixé son nom par un UUID."""
    relative = Path(str(annotation["table_path"]).replace("\\", "/"))
    basename = relative.name
    legacy_basename = f"flag-{annotation.get('instance_id')}.csv"
    candidates: list[Path] = []
    for directory in search_dirs:
        candidates.extend((directory / relative).resolve() for _ in [0])
        candidates.append((directory / basename).resolve())
        # InsightEval a été construit à partir d'InsightBench : les tables
        # data_N.csv sont exactement les anciennes flag-N.csv.
        candidates.append((directory / legacy_basename).resolve())
        if directory.is_dir():
            candidates.extend(sorted(directory.glob(f"*_{basename}")))
    candidates.append(cache_dir / basename)
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if not allow_download:
        raise FileNotFoundError(f"CSV introuvable : {basename}")
    destination = cache_dir / basename
    print(f"  [download] {basename} absent localement, téléchargement du CSV officiel")
    quoted_path = "/".join(requests.utils.quote(part, safe="") for part in relative.parts)
    return _download(INSIGHTEVAL_FILE_URL.format(path=quoted_path), destination)


def build_evidence_prompt(annotation: dict) -> str:
    """Première passe : impose des calculs reproductibles avant l'interprétation."""
    return f"""You are the evidence-extraction stage of a data-analysis benchmark.

Analytical goal:
<goal>{annotation['goal']}</goal>

Expected dataset schema:
<schema>{annotation.get('table_schema', '')}</schema>

You MUST use Python on the uploaded dataframe to verify the actual row count,
columns, category distributions, relevant group counts, temporal patterns and
other quantities needed to address the goal. Do not estimate values from a sample
or invent plausible numbers.

Return a compact evidence report containing:
1. the executed Python code;
2. the exact outputs obtained from the dataframe;
3. a JSON object inside <evidence>...</evidence> with verified facts only.

Do not write final insights or recommendations yet."""


def build_analysis_code_prompt(annotation: dict) -> str:
    """Prompt L_code des équations 6–7 : code seul, exécuté ensuite en sandbox."""
    return f"""Write Python code to analyze a pandas dataframe named `df`.

Goal:
<goal>{annotation['goal']}</goal>

Schema:
<schema>{annotation.get('table_schema', '')}</schema>

The code must calculate, from the full dataframe, all evidence needed for ten
diverse insights addressing the goal. Include exact category counts and shares,
cross-tabulations for relevant personnel/groups/locations, temporal patterns,
frequent issue descriptions or identifiers, and workload imbalances when those
columns exist. For every percentage, print its numerator, denominator, formula,
and a label stating exactly what population the denominator represents. Never
hard-code a result. Print compact, labeled textual or JSON outputs. Do not create
charts and do not train models.

Return only one executable Python code block, without commentary."""


def extract_python_code(response: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", response or "", re.I | re.S)
    code = (match.group(1) if match else response or "").strip()
    if not code:
        raise RuntimeError("Le modèle n'a produit aucun code d'analyse")
    return code


def extract_evidence_with_sandbox(csv_path: Path, annotation: dict, model: str) -> str:
    """Génère L_code, exécute Exec(C,T), puis renvoie la sortie vérifiée."""
    from app.services.gemini_service import complete_text
    from app.services.sandbox_service import execute_code

    code_response = complete_text(build_analysis_code_prompt(annotation), model=model)
    code = extract_python_code(code_response)
    dataframe_bytes = csv_path.read_bytes()
    execution = execute_code(code, dataframe_bytes, csv_path.name)
    for repair_attempt in range(3):
        if not execution.get("error"):
            break
        error = execution["error"]
        detail = error.get("technical") if isinstance(error, dict) else str(error)
        repair_prompt = f"""Fix this Python analysis code after its sandbox error.
The dataframe is named df. Preserve all requested calculations. Ensure every
printed/JSON key and value is serializable (convert pandas Period/Timestamp and
numpy scalar values to strings or native Python values).

CODE:
```python
{code}
```

ERROR:
{detail}

Return only the complete corrected Python code block."""
        repaired_response = complete_text(repair_prompt, model=model)
        code = extract_python_code(repaired_response)
        execution = execute_code(code, dataframe_bytes, csv_path.name)
    if execution.get("error"):
        final_error = execution["error"]
        final_detail = (
            final_error.get("technical")
            if isinstance(final_error, dict)
            else str(final_error)
        )
        raise RuntimeError(
            f"Code d'analyse toujours en échec après 3 réparations : {final_detail}"
        )
    output = str(execution.get("output") or "").strip()
    if not output:
        raise RuntimeError("Le code d'analyse n'a imprimé aucune preuve")
    return f"EXECUTED PYTHON CODE:\n{code}\n\nVERIFIED SANDBOX OUTPUT:\n{output}"


def build_insight_prompt(
    annotation: dict,
    n_insights: int = 10,
    evidence: str = "",
) -> str:
    """Seconde passe : synthèse fondée uniquement sur les preuves exécutées."""
    return f"""You are a data scientist performing evidence-grounded insight discovery.

Analytical goal:
<goal>{annotation['goal']}</goal>

Dataset description:
<description>{annotation.get('table_description', '')}</description>

Expected dataset schema:
<schema>{annotation.get('table_schema', '')}</schema>

Verified evidence produced by a previous Python execution:
<verified_evidence>{evidence}</verified_evidence>

Produce exactly
{n_insights} distinct, concise, non-trivial insights that directly address the goal.
Cover several perspectives where relevant: descriptive, diagnostic, predictive,
prescriptive, evaluative, and exploratory. Every factual claim must be supported by
the verified evidence above; quantify findings whenever possible. Never introduce a
number, category, person, location or trend absent from that evidence. If the evidence
is insufficient for a claim, omit the claim rather than guessing. Before emitting
each percentage or ratio, recompute it from the stated numerator and denominator.
Never swap conditional directions (for example P(Hardware|Australia) is not
P(Australia|Hardware)). Include numerator/denominator in the final insight whenever
a percentage is reported.

Return only this machine-readable structure:
<insights>
<insight>First insight</insight>
...
</insights>
<summary>A concise synthesis of the main findings.</summary>"""


def synthesize_insights_direct(prompt: str, model: str) -> str:
    """Synthèse sans le routeur /api/chat, qui impose insights_visualization."""
    from app.services.gemini_service import complete_text

    response = complete_text(prompt, model=model)
    if re.match(r"^\s*Erreur\s+[A-Za-z0-9_-]+\s*:", response, re.I):
        raise RuntimeError(response.strip())
    return response


_INSIGHT_TAG = re.compile(r"<insight>(.*?)</insight>", re.I | re.S)
_SUMMARY_TAG = re.compile(r"<summary>(.*?)</summary>", re.I | re.S)


def parse_insight_response(text: str) -> tuple[list[str], str]:
    """Parse XML demandé, avec repli JSON puis liste Markdown."""
    insights = [re.sub(r"\s+", " ", value).strip() for value in _INSIGHT_TAG.findall(text)]
    summary_match = _SUMMARY_TAG.search(text or "")
    summary = re.sub(r"\s+", " ", summary_match.group(1)).strip() if summary_match else ""
    if insights:
        return insights, summary

    try:
        payload = json.loads((text or "").strip().strip("`"))
        if isinstance(payload, dict):
            raw_insights = payload.get("insights") or []
            insights = [str(value).strip() for value in raw_insights if str(value).strip()]
            return insights, str(payload.get("summary") or "").strip()
    except (json.JSONDecodeError, TypeError):
        pass

    for line in (text or "").splitlines():
        match = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", line)
        if match:
            insights.append(match.group(1))
    return insights, summary


def _rouge1(reference: str, prediction: str) -> dict[str, float]:
    from rouge_score import rouge_scorer

    scorer = rouge_scorer.RougeScorer(["rouge1"], use_stemmer=True)
    score_value = scorer.score(reference or "", prediction or "")["rouge1"]
    return {
        "precision": score_value.precision,
        "recall": score_value.recall,
        "fmeasure": score_value.fmeasure,
    }


def score_insights(reference: list[str], predicted: list[str]) -> dict:
    """Équations 13–15 du papier avec ROUGE-1 comme similarité S."""
    matrix = [
        [_rouge1(gt, candidate)["fmeasure"] for candidate in predicted]
        for gt in reference
    ]
    recall = sum((max(row) if row else 0.0) for row in matrix) / len(reference) \
        if reference else 0.0
    precision_values = [
        max((matrix[row][column] for row in range(len(reference))), default=0.0)
        for column in range(len(predicted))
    ]
    precision = sum(precision_values) / len(precision_values) if precision_values else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "recall": round(recall, 6),
        "precision": round(precision, 6),
        "f1": round(f1, 6),
        "similarity_matrix": matrix,
    }


def _parse_json_object(text: str) -> dict:
    """Extrait un objet JSON, y compris lorsqu'un fournisseur ajoute du Markdown."""
    candidate = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.I | re.S)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start:end + 1]
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("La réponse G-Eval n'est pas un objet JSON")
    return payload


def score_insights_geval(
    reference: list[str],
    predicted: list[str],
    reference_summary: str,
    predicted_summary: str,
    evaluator_model: str,
) -> tuple[dict, dict]:
    """Similarité sémantique G-Eval, puis agrégation Recall/Precision/F1.

    Un seul appel juge toute l'instance afin d'éviter un appel par paire. Les
    mêmes équations d'agrégation que ROUGE-1 sont ensuite appliquées.
    """
    from app.services.gemini_service import complete_text

    rows, columns = len(reference), len(predicted)
    prompt = f"""You are the G-Eval semantic judge for the InsightEval benchmark.
Compare each reference insight with each generated insight. A score is a real
number from 0 to 1: 1 means the same correct, data-grounded finding (including
compatible entities, direction, quantities and denominator); 0 means unrelated
or contradictory. Penalize swapped conditional directions and incompatible
numbers. Also score semantic equivalence of the two summaries from 0 to 1.

Reference insights: {json.dumps(reference, ensure_ascii=False)}
Generated insights: {json.dumps(predicted, ensure_ascii=False)}
Reference summary: {json.dumps(reference_summary or '', ensure_ascii=False)}
Generated summary: {json.dumps(predicted_summary or '', ensure_ascii=False)}

Return JSON only, exactly:
{{"similarity_matrix": <{rows} rows by {columns} columns>, "summary_score": <0..1>}}
Do not add prose or markdown."""
    payload = _parse_json_object(complete_text(prompt, model=evaluator_model))
    raw_matrix = payload.get("similarity_matrix")
    if not isinstance(raw_matrix, list) or len(raw_matrix) != rows:
        raise ValueError(f"Matrice G-Eval invalide : {rows} lignes attendues")
    matrix = []
    for row in raw_matrix:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError(f"Matrice G-Eval invalide : {columns} colonnes attendues")
        matrix.append([max(0.0, min(1.0, float(value))) for value in row])
    recall = sum((max(row) if row else 0.0) for row in matrix) / rows if rows else 0.0
    precision_values = [
        max((matrix[row][column] for row in range(rows)), default=0.0)
        for column in range(columns)
    ]
    precision = sum(precision_values) / columns if columns else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    summary_score = max(0.0, min(1.0, float(payload.get("summary_score", 0.0))))
    return (
        {"recall": round(recall, 6), "precision": round(precision, 6),
         "f1": round(f1, 6), "similarity_matrix": matrix},
        {"fmeasure": round(summary_score, 6)},
    )


def evaluate_insighteval_instance(
    annotation: dict,
    response: str,
    evidence_response: str = "",
    evaluator_model: str | None = None,
) -> dict:
    predicted, predicted_summary = parse_insight_response(response)
    reference = [str(item) for item in annotation.get("insights") or []]
    metrics = score_insights(reference, predicted)
    summary_metrics = _rouge1(str(annotation.get("summary") or ""), predicted_summary)
    insight_geval = summary_geval = None
    geval_error = None
    if evaluator_model:
        try:
            insight_geval, summary_geval = score_insights_geval(
                reference, predicted, str(annotation.get("summary") or ""),
                predicted_summary, evaluator_model,
            )
        except Exception as exc:
            # Une panne du juge ne doit pas jeter les scores ROUGE déjà calculés.
            geval_error = str(exc)
    details = annotation.get("insights_detail") or []
    comparisons = []
    matrix = metrics["similarity_matrix"]
    for index, expected in enumerate(reference):
        row = matrix[index] if index < len(matrix) else []
        best_index = max(range(len(row)), key=row.__getitem__) if row else None
        detail = details[index] if index < len(details) and isinstance(details[index], dict) else {}
        comparisons.append({
            "question_number": index + 1,
            "question": detail.get("question") or f"Insight de référence {index + 1}",
            "data_type": detail.get("data_type"),
            "expected": expected,
            "obtained": predicted[best_index] if best_index is not None else None,
            "obtained_index": best_index + 1 if best_index is not None else None,
            "rouge1_similarity": round(row[best_index], 6) if best_index is not None else 0.0,
        })
    return {
        "instance_id": annotation["instance_id"],
        "header": annotation.get("header"),
        "category": annotation.get("category"),
        "difficulty": annotation.get("difficulty"),
        "goal": annotation["goal"],
        "reference_insights": reference,
        "predicted_insights": predicted,
        "reference_summary": annotation.get("summary"),
        "predicted_summary": predicted_summary,
        "question_comparisons": comparisons,
        "insight_rouge1": metrics,
        "summary_rouge1": {key: round(value, 6) for key, value in summary_metrics.items()},
        "insight_geval": insight_geval,
        "summary_geval": summary_geval,
        "geval_error": geval_error,
        "format_ok": bool(predicted) and bool(predicted_summary),
        "evidence_response": evidence_response,
        "raw_response": response,
    }


def summarize_insighteval(results: list[dict], errors: list[dict]) -> dict:
    def average(path: tuple[str, ...]) -> float | None:
        values = []
        for item in results:
            value = item
            for key in path:
                if value is None or not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
            if value is not None:
                values.append(float(value))
        return round(sum(values) / len(values), 6) if values else None

    return {
        "n_instances": len(results) + len(errors),
        "n_evaluated": len(results),
        "n_errors": len(errors),
        "format_compliance": round(
            sum(item["format_ok"] for item in results) / len(results), 6
        ) if results else None,
        "insights_rouge1_recall": average(("insight_rouge1", "recall")),
        "insights_rouge1_precision": average(("insight_rouge1", "precision")),
        "insights_rouge1_f1": average(("insight_rouge1", "f1")),
        "insights_geval_recall": average(("insight_geval", "recall")),
        "insights_geval_precision": average(("insight_geval", "precision")),
        "insights_geval_f1": average(("insight_geval", "f1")),
        "summary_rouge1_recall": average(("summary_rouge1", "recall")),
        "summary_rouge1_precision": average(("summary_rouge1", "precision")),
        "summary_rouge1_f1": average(("summary_rouge1", "fmeasure")),
        "summary_geval_f1": average(("summary_geval", "fmeasure")),
    }


def main_insighteval() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Évalue SALI sur InsightEval (arXiv:2511.22884v2) : insights "
            "ROUGE-1 rappel/précision/F1 et résumé."
        )
    )
    default_cache = PROJECT_DATA_DIR / "insighteval"
    parser.add_argument("--annotations", type=Path,
                        default=default_cache / "annotations.jsonl")
    parser.add_argument("--tables-dir", type=Path, action="append", default=[],
                        help="dossier local de CSV (répétable); data/uploads est inspecté par défaut")
    parser.add_argument("--cache-dir", type=Path, default=default_cache / "csvs")
    parser.add_argument("--no-download", action="store_true",
                        help="interdit le téléchargement des fichiers officiels manquants")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default=None, help="modèle SALI évalué")
    parser.add_argument("--language", choices=["en", "fr"], default="en")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--instance-id", type=int, action="append", default=[],
                        help="n'évaluer que cet ID (option répétable)")
    parser.add_argument("--n-insights", type=int, default=10)
    parser.add_argument("--with-interpretation", action="store_true")
    parser.add_argument("--responses", type=Path,
                        help="JSONL de réponses existantes; évite les appels à SALI")
    parser.add_argument("--out", type=Path,
                        default=Path("eval_analysis_results.json"))
    args = parser.parse_args()

    allow_download = not args.no_download
    try:
        annotations = load_insighteval_annotations(args.annotations, allow_download)
    except Exception as exc:
        print(f"ERREUR Chargement InsightEval impossible : {exc}", file=sys.stderr)
        return 1

    if args.instance_id:
        wanted = set(args.instance_id)
        annotations = [row for row in annotations if int(row["instance_id"]) in wanted]
    if args.limit:
        annotations = annotations[:args.limit]
    if not annotations:
        print("ERREUR Aucun cas InsightEval sélectionné.", file=sys.stderr)
        return 1

    saved_responses: dict[int, str] = {}
    if args.responses:
        for row in load_jsonl(args.responses):
            saved_responses[int(row["instance_id"])] = str(
                row.get("response") or row.get("raw_response") or ""
            )
    else:
        try:
            requests.get(f"{args.api_base}/health", timeout=10).raise_for_status()
        except Exception as exc:
            print(f"ERREUR Backend injoignable sur {args.api_base} : {exc}", file=sys.stderr)
            print("  Lancez d'abord : python run_server.py", file=sys.stderr)
            return 1

    search_dirs = args.tables_dir or [
        INSIGHTBENCH_TABLES_DIR,
        PROJECT_DATA_DIR / "uploads",
        default_cache / "csvs",
    ]
    results, errors = [], []
    started = time.time()
    print(f"InsightEval : {len(annotations)} instance(s), modèle : {args.model or 'défaut backend'}")

    for position, annotation in enumerate(annotations, 1):
        instance_id = int(annotation["instance_id"])
        try:
            if instance_id in saved_responses:
                response = saved_responses[instance_id]
            else:
                csv_path = resolve_insighteval_table(
                    annotation, search_dirs, args.cache_dir, allow_download
                )
                session_id = upload_csv(
                    args.api_base, csv_path, args.model, args.with_interpretation
                )
                if args.model:
                    evidence_response = extract_evidence_with_sandbox(
                        csv_path, annotation, args.model
                    )
                else:
                    evidence_response = ask_question(
                        args.api_base,
                        session_id,
                        build_evidence_prompt(annotation),
                        args.model,
                        args.language,
                    )
                synthesis_prompt = build_insight_prompt(
                    annotation, args.n_insights, evidence_response
                )
                if args.model:
                    response = synthesize_insights_direct(synthesis_prompt, args.model)
                else:
                    response = ask_question(
                        args.api_base,
                        session_id,
                        synthesis_prompt,
                        args.model,
                        args.language,
                    )
            result = evaluate_insighteval_instance(
                annotation,
                response,
                evidence_response if instance_id not in saved_responses else "",
            )
            results.append(result)
            metrics = result["insight_rouge1"]
            print(
                f"  OK [{position}/{len(annotations)}] #{instance_id} "
                f"R={metrics['recall']:.3f} P={metrics['precision']:.3f} "
                f"F1={metrics['f1']:.3f} ({len(result['predicted_insights'])} insights)"
            )
        except Exception as exc:
            errors.append({"instance_id": instance_id, "error": str(exc)})
            print(f"  ERREUR [{position}/{len(annotations)}] #{instance_id} : {exc}")
        time.sleep(REQUEST_DELAY)

    summary = summarize_insighteval(results, errors)
    summary.update({
        "benchmark": "InsightEval",
        "paper": "https://arxiv.org/abs/2511.22884v2",
        "model": args.model or "(défaut backend)",
        "total_time_s": round(time.time() - started, 1),
        "metric_note": (
            "ROUGE-1 local selon les équations 13–15. G-Eval et novelty ne sont "
            "pas calculés sans configuration explicite de trois modèles juges."
        ),
    })
    args.out.write_text(
        json.dumps({"summary": summary, "results": results, "errors": errors},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n" + "=" * 60)
    print(f"  Évaluées : {summary['n_evaluated']} · erreurs : {summary['n_errors']}")
    print(f"  Insights ROUGE-1 rappel    : {summary['insights_rouge1_recall']}")
    print(f"  Insights ROUGE-1 précision : {summary['insights_rouge1_precision']}")
    print(f"  Insights ROUGE-1 F1        : {summary['insights_rouge1_f1']}")
    print(f"  Résumé ROUGE-1 F1          : {summary['summary_rouge1_f1']}")
    print("=" * 60)
    print(f"Resultats : {args.out}")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main_insighteval())
