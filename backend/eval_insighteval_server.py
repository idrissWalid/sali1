"""Interface web pour évaluer SALI sur InsightEval.

Lancer le backend principal, puis ce fichier et ouvrir http://127.0.0.1:8002.
La logique de génération et de notation reste dans eval_analysis.py.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from threading import Thread

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from eval_analysis import (
    DEFAULT_API_BASE,
    INSIGHTBENCH_TABLES_DIR,
    PROJECT_DATA_DIR,
    ask_question,
    build_evidence_prompt,
    build_insight_prompt,
    evaluate_insighteval_instance,
    extract_evidence_with_sandbox,
    load_insighteval_annotations,
    resolve_insighteval_table,
    summarize_insighteval,
    synthesize_insights_direct,
    upload_csv,
)

EVAL_PORT = 8002
DEFAULT_CACHE = PROJECT_DATA_DIR / "insighteval"


def fresh_state() -> dict:
    return {
        "running": False,
        "done": False,
        "cancel_requested": False,
        "progress": 0,
        "total": 0,
        "log": [],
        "results": [],
        "errors": [],
        "summary": {},
        "error": None,
        "started_at": None,
        "elapsed": 0.0,
        "eta": 0.0,
    }


state = fresh_state()


class RunConfig(BaseModel):
    data_dir: str = str(DEFAULT_CACHE)
    api_base: str = DEFAULT_API_BASE
    model: str = ""
    limit: int = Field(default=1, ge=0, le=100)
    instance_ids: list[int] = Field(default_factory=list)
    n_insights: int = Field(default=10, ge=1, le=30)
    language: str = Field(default="en", pattern="^(en|fr)$")
    with_interpretation: bool = False
    with_geval: bool = True
    evaluator_model: str = "gemini-3.1-flash-lite"
    allow_download: bool = True


def run_worker(config: RunConfig) -> None:
    def log(message: str) -> None:
        state["log"].append(message)

    try:
        data_dir = Path(config.data_dir).expanduser()
        annotations = load_insighteval_annotations(
            data_dir / "annotations.jsonl", config.allow_download
        )
        if config.instance_ids:
            selected = set(config.instance_ids)
            annotations = [
                row for row in annotations if int(row["instance_id"]) in selected
            ]
        elif config.limit:
            annotations = annotations[: config.limit]
        if not annotations:
            raise ValueError("Aucune instance InsightEval sélectionnée")

        state["total"] = len(annotations)
        state["started_at"] = time.time()
        search_dirs = [INSIGHTBENCH_TABLES_DIR, PROJECT_DATA_DIR / "uploads", data_dir / "csvs"]
        results: list[dict] = []
        errors: list[dict] = []
        log(
            f"InsightEval : {len(annotations)} instance(s), "
            f"modèle {config.model or 'défaut backend'}"
        )

        if config.with_geval:
            from app.core.config import get_default_model
            evaluator_model = config.evaluator_model or config.model or get_default_model()
            log(f"Juge G-Eval : {evaluator_model}")
        else:
            evaluator_model = None

        for position, annotation in enumerate(annotations, 1):
            if state["cancel_requested"]:
                log("Évaluation annulée.")
                break
            instance_id = int(annotation["instance_id"])
            try:
                log(f"#{instance_id} : préparation de {annotation['table_path']}")
                csv_path = resolve_insighteval_table(
                    annotation,
                    search_dirs,
                    data_dir / "csvs",
                    config.allow_download,
                )
                session_id = upload_csv(
                    config.api_base,
                    csv_path,
                    config.model or None,
                    config.with_interpretation,
                )
                log(f"#{instance_id} : extraction des preuves par exécution Python")
                if config.model:
                    evidence_response = extract_evidence_with_sandbox(
                        csv_path, annotation, config.model
                    )
                else:
                    evidence_response = ask_question(
                        config.api_base,
                        session_id,
                        build_evidence_prompt(annotation),
                        None,
                        config.language,
                    )
                log(f"#{instance_id} : génération des insights depuis les preuves")
                synthesis_prompt = build_insight_prompt(
                    annotation, config.n_insights, evidence_response
                )
                if config.model:
                    response = synthesize_insights_direct(
                        synthesis_prompt, config.model
                    )
                else:
                    response = ask_question(
                        config.api_base,
                        session_id,
                        synthesis_prompt,
                        None,
                        config.language,
                    )
                result = evaluate_insighteval_instance(
                    annotation,
                    response,
                    evidence_response,
                    evaluator_model,
                )
                if result.get("geval_error"):
                    log(f"#{instance_id} : G-Eval indisponible — {result['geval_error']}")
                results.append(result)
                metrics = result["insight_rouge1"]
                log(
                    f"#{instance_id} terminé — R {metrics['recall']:.3f} · "
                    f"P {metrics['precision']:.3f} · F1 {metrics['f1']:.3f}"
                )
            except Exception as exc:
                errors.append({"instance_id": instance_id, "error": str(exc)})
                log(f"#{instance_id} en erreur — {exc}")

            state["progress"] = position
            state["results"] = results
            state["errors"] = errors
            elapsed = time.time() - state["started_at"]
            state["elapsed"] = elapsed
            state["eta"] = elapsed / position * (len(annotations) - position)

        summary = summarize_insighteval(results, errors)
        def optional_average(items: list[dict], metric: str, key: str) -> float | None:
            values = [float(item[metric][key]) for item in items if item.get(metric)]
            return round(sum(values) / len(values), 6) if values else None

        for dimension in ("category", "difficulty"):
            groups: dict[str, list[dict]] = {}
            for item in results:
                groups.setdefault(str(item.get(dimension) or "(non renseigné)"), []).append(item)
            summary[f"by_{dimension}"] = {
                key: {
                    "n": len(items),
                    "recall": round(sum(x["insight_rouge1"]["recall"] for x in items) / len(items), 6),
                    "precision": round(sum(x["insight_rouge1"]["precision"] for x in items) / len(items), 6),
                    "f1": round(sum(x["insight_rouge1"]["f1"] for x in items) / len(items), 6),
                    "summary_f1": round(sum(x["summary_rouge1"]["fmeasure"] for x in items) / len(items), 6),
                    "geval_f1": optional_average(items, "insight_geval", "f1"),
                    "summary_geval": optional_average(items, "summary_geval", "fmeasure"),
                }
                for key, items in sorted(groups.items())
            }
        summary.update(
            {
                "benchmark": "InsightEval",
                "model": config.model or "(défaut backend)",
                "language": config.language,
                "n_insights_requested": config.n_insights,
                "with_interpretation": config.with_interpretation,
                "with_geval": config.with_geval,
                "evaluator_model": evaluator_model or "(désactivé)",
                "data_dir": str(data_dir),
                "total_time_s": round(time.time() - state["started_at"], 1),
            }
        )
        state["summary"] = summary
        state["done"] = True
        state["running"] = False
        state["eta"] = 0
        log("Évaluation terminée.")
    except Exception:
        state["error"] = traceback.format_exc()
        state["running"] = False
        log("Erreur fatale pendant l'évaluation.")


app = FastAPI(title="InsightEval — Évaluation SALI")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.post("/run")
def start_evaluation(config: RunConfig):
    if state["running"]:
        raise HTTPException(409, "Une évaluation est déjà en cours")
    state.clear()
    state.update(fresh_state())
    state["running"] = True
    Thread(target=run_worker, args=(config,), daemon=True).start()
    return {"status": "started"}


@app.post("/cancel")
def cancel_evaluation():
    state["cancel_requested"] = True
    return {"status": "cancelling"}


@app.get("/progress")
def progress():
    def events():
        last_log = 0
        while True:
            payload = {
                key: state[key]
                for key in (
                    "running", "done", "progress", "total", "error", "eta", "elapsed"
                )
            }
            payload["log"] = state["log"][last_log:]
            last_log = len(state["log"])
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if state["done"] or (not state["running"] and state["error"]):
                break
            time.sleep(0.7)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/results")
def results():
    if not state["done"]:
        raise HTTPException(425, "Évaluation non terminée")
    return JSONResponse(
        {"summary": state["summary"], "results": state["results"], "errors": state["errors"]}
    )


@app.get("/models")
def models(api_base: str = DEFAULT_API_BASE):
    try:
        response = requests.get(f"{api_base}/api/llm-models", timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"models": [], "default": "", "error": str(exc)}


@app.get("/health")
def health():
    return {"status": "ok", "running": state["running"], "done": state["done"]}


@app.post("/save_pdf")
async def save_pdf(request: Request):
    pdf_bytes = await request.body()
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(400, "Le contenu reçu n'est pas un PDF")
    filename = f"eval_insighteval_report_{int(time.time())}.pdf"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    with open(filepath, "wb") as handle:
        handle.write(pdf_bytes)
    return {"status": "ok", "filename": filename}


HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InsightEval · SALI</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
:root{--green:#16a34a;--green2:#22c55e;--dark:#0d0f14;--panel:#171a21;--muted:#9298a8;--line:#2b303b;--white:#f4f5f7;--red:#fb7185}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#20242d 0,transparent 35%),var(--dark);color:var(--white);font-family:Inter,system-ui,sans-serif;min-height:100vh}
nav{height:62px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 34px;background:#0d0f14dd;backdrop-filter:blur(12px)}
.brand{font-weight:800;letter-spacing:.4px}.brand i{display:inline-block;width:9px;height:9px;background:var(--green2);border-radius:50%;margin-right:10px;box-shadow:0 0 18px var(--green2)}
.tag{color:var(--muted);font:12px ui-monospace,monospace}.page{max-width:980px;margin:auto;padding:55px 24px 80px}
h1{font-size:clamp(36px,7vw,68px);line-height:.96;margin:0 0 14px;letter-spacing:-3px}h1 span{color:var(--green2)}
.lead{color:var(--muted);max-width:700px;line-height:1.6;margin-bottom:34px}.card{background:#171a21e8;border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:18px;box-shadow:0 20px 60px #0004}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.field label{display:block;color:var(--muted);font:11px ui-monospace,monospace;text-transform:uppercase;letter-spacing:1px;margin-bottom:7px}
input,select{width:100%;background:#101218;color:var(--white);border:1px solid var(--line);border-radius:9px;padding:11px 12px;outline:none}input:focus,select:focus{border-color:var(--green2)}
.checks{display:flex;gap:24px;margin:18px 0;color:var(--muted);font-size:13px}.checks input{width:auto}.actions{display:flex;gap:10px}
button{border:0;border-radius:9px;padding:12px 21px;font-weight:750;cursor:pointer;background:var(--green);color:white}button:hover{background:var(--green2)}button:disabled{opacity:.45;cursor:not-allowed}.outline{background:transparent;border:1px solid var(--line);color:var(--muted)}
#runbox,#result{display:none}.progress{height:7px;background:#101218;border-radius:10px;overflow:hidden;margin:14px 0}.fill{height:100%;width:0;background:linear-gradient(90deg,var(--green),#86efac);transition:width .4s}
.status{display:flex;justify-content:space-between;color:var(--muted);font:12px ui-monospace,monospace}.terminal{height:220px;overflow:auto;background:#0b0d11;border:1px solid var(--line);border-radius:10px;padding:14px;color:#b8bdc9;font:12px/1.7 ui-monospace,monospace;white-space:pre-wrap}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stat{background:#101218;border:1px solid var(--line);border-radius:12px;padding:17px}.stat b{display:block;font-size:27px;color:var(--green2)}.stat span{color:var(--muted);font:10px ui-monospace,monospace;text-transform:uppercase}.error{color:var(--red);white-space:pre-wrap;margin-top:12px}
.toolbar{display:flex;flex-wrap:wrap;gap:9px;margin:20px 0}.toolbar button{background:#20242d;border:1px solid var(--line);color:var(--white);padding:9px 14px}.toolbar button:hover{border-color:var(--green);background:#252a34}
.section-title{margin:30px 0 12px;font-size:17px}.breakdown{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.metric-row{display:grid;grid-template-columns:minmax(120px,1fr) 2fr 58px;align-items:center;gap:10px;margin:10px 0;color:var(--muted);font-size:12px}.bar{height:7px;background:#252a34;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:var(--green);border-radius:8px}.metric-row strong{color:var(--white);text-align:right}
.detail{border:1px solid var(--line);border-radius:11px;margin:10px 0;overflow:hidden}.detail summary{cursor:pointer;padding:14px 16px;background:#13161c;display:flex;justify-content:space-between;gap:15px}.detail summary:hover{background:#1b1f27}.detail-body{padding:16px;color:var(--muted);font-size:13px;line-height:1.55}.detail-body h4{color:var(--white);margin:15px 0 6px}.detail-body ol{padding-left:22px}.pill{font:10px ui-monospace,monospace;border:1px solid var(--line);border-radius:20px;padding:3px 8px;color:var(--green2);white-space:nowrap}.errors{border-color:#602936}.errors summary{color:var(--red)}
.comparison{background:#101218;border:1px solid var(--line);border-radius:10px;padding:14px;margin:10px 0}.comparison-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px;color:var(--white)}.answer-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.answer{border-left:3px solid var(--line);padding:9px 11px;background:#0b0d11;border-radius:0 7px 7px 0}.answer.expected{border-color:#64748b}.answer.obtained{border-color:var(--green)}.answer label{display:block;font:10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px}.answer p{margin:0;color:#d7dae1}.score-low{color:#fb7185}.score-mid{color:#fbbf24}.score-high{color:var(--green2)}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:10px}.baseline-table{border-collapse:collapse;width:100%;min-width:900px;font-size:11px}.baseline-table th,.baseline-table td{padding:9px 8px;border-bottom:1px solid var(--line);text-align:right}.baseline-table th:first-child,.baseline-table td:first-child{text-align:left;position:sticky;left:0;background:#13161c}.baseline-table thead th{color:var(--muted);background:#101218}.baseline-table tr.sali td{color:var(--green2);font-weight:800}.chart-tools{display:flex;align-items:center;gap:12px;margin-bottom:10px}.chart-tools select{width:auto}.chart-wrap{background:#101218;border:1px solid var(--line);border-radius:10px;padding:10px;overflow:auto}#baselineChart{width:100%;min-width:720px;height:430px}
@media(max-width:700px){.grid,.stats,.breakdown,.answer-grid{grid-template-columns:1fr}.comparison-head{display:block}.comparison-head .pill{display:inline-block;margin-top:8px}.page{padding-top:35px}h1{letter-spacing:-2px}}
</style>
</head>
<body><nav><div class="brand"><i></i>SALI · InsightEval</div><div class="tag">arXiv:2511.22884v2 · port 8002</div></nav>
<main class="page"><h1>Évaluer les <span>insights.</span></h1><p class="lead">Benchmark expert-curated : génération de dix insights fondés sur les données, puis mesure du rappel, de la précision, du F1 et de la qualité du résumé.</p>
<section class="card"><div class="grid">
<div class="field"><label>Modèle (LLM évalué)</label><select id="model"><option value="">Défaut du backend</option></select><small id="modelHint" style="color:var(--muted)"></small></div>
<div class="field"><label>Dossier du jeu InsightEval</label><input id="dataDir" value="../data/insighteval"><small style="color:var(--muted)">annotations.jsonl et csvs/</small></div>
<div class="field"><label>Nombre d'instances (0 = toutes)</label><input id="limit" type="number" min="0" max="100" value="1"></div>
<div class="field"><label>API SALI</label><input id="api" value="http://127.0.0.1:8000" onchange="loadModels()"></div>
<div class="field"><label>Nombre d'insights demandés</label><input id="nInsights" type="number" min="1" max="30" value="10"><small style="color:var(--muted)">10 dans le protocole officiel</small></div>
<div class="field"><label>Langue des réponses</label><select id="language"><option value="en" selected>Anglais (langue du benchmark)</option><option value="fr">Français (comportement produit)</option></select></div>
<div class="field"><label>IDs précis (optionnel)</label><input id="ids" placeholder="1, 8, 42"><small style="color:var(--muted)">séparés par des virgules</small></div>
<div class="field"><label>Modèle juge G-Eval (optionnel)</label><input id="evaluatorModel" value="gemini-3.1-flash-lite" placeholder="Vide = même modèle / défaut backend"><small style="color:var(--muted)">Juge par défaut : Gemini 3.1 Flash-Lite</small></div>
</div><div class="checks"><label><input id="download" type="checkbox" checked> Télécharger les annotations/CSV manquants</label><label><input id="interpret" type="checkbox"> Laisser l'upload produire son texte d'accueil</label><label><input id="withGeval" type="checkbox" checked> Calculer G-Eval</label></div>
<div class="actions"><button id="start" onclick="startEval()">Lancer l'évaluation</button><button id="cancel" class="outline" onclick="cancelEval()" disabled>Annuler</button></div><div id="err" class="error"></div></section>
<section id="runbox" class="card"><div class="status"><span id="counter">Préparation…</span><span id="eta"></span></div><div class="progress"><div id="fill" class="fill"></div></div><div id="terminal" class="terminal"></div></section>
<section id="result" class="card"><div id="report"><h2>Résultats InsightEval</h2><div class="stats"><div class="stat"><span>Recall ROUGE-1</span><b id="recall">—</b></div><div class="stat"><span>Recall G-Eval</span><b id="gRecall">—</b></div><div class="stat"><span>Precision ROUGE-1</span><b id="precision">—</b></div><div class="stat"><span>Precision G-Eval</span><b id="gPrecision">—</b></div><div class="stat"><span>Insight F1 ROUGE-1</span><b id="f1">—</b></div><div class="stat"><span>Insight F1 G-Eval</span><b id="gF1">—</b></div><div class="stat"><span>Résumé ROUGE-1</span><b id="summary">—</b></div><div class="stat"><span>Résumé G-Eval</span><b id="gSummary">—</b></div></div><p id="counts" class="lead" style="margin:18px 0 0"></p><h3 class="section-title">Comparaison aux baselines publiées</h3><div class="chart-tools"><label for="chartMetric">Métrique</label><select id="chartMetric" onchange="renderBaselineChart()"></select></div><div class="chart-wrap"><canvas id="baselineChart"></canvas></div><div id="baselineTable" class="table-wrap" style="margin-top:12px"></div><h3 class="section-title">Par catégorie</h3><div id="categories" class="breakdown"></div><h3 class="section-title">Par difficulté</h3><div id="difficulties" class="breakdown"></div><h3 class="section-title">Détail des instances</h3><div id="details"></div><div id="errorDetails"></div></div><div class="toolbar"><button onclick="downloadJSON()">Exporter JSON</button><button onclick="downloadCSV()">Exporter CSV</button><button onclick="downloadPDF(false)">Télécharger PDF</button><button onclick="downloadPDF(true)">Sauvegarder PDF sur le serveur</button></div></section>
</main><script>
const $=id=>document.getElementById(id);let source,resultData=null;
const METRICS=[['ir','Recall R-1'],['ig','Recall G-Eval'],['pr','Precision R-1'],['pg','Precision G-Eval'],['fr','F1 R-1'],['fg','F1 G-Eval'],['sr','Summary R-1'],['sg','Summary G-Eval']];
const BASELINES=[['LLM-only','GPT-4o',.2304,.3389,.2445,.3506,.2372,.3447,.2423,.3282],['LLM-only','DeepSeek-V3',.2183,.3402,.2295,.3554,.2238,.3476,.2405,.3332],['LLM-only','Claude-3.7-Sonnet',.2219,.3265,.2364,.3492,.2289,.3375,.2439,.3250],['Single-Agent','ReAct (GPT-4o)',.2506,.3977,.2573,.4069,.2539,.4022,.2654,.3913],['Single-Agent','CodeGen (GPT-4o)',.2488,.4289,.2579,.4412,.2533,.4350,.2598,.3991],['Multi-Agents','DeepResearchAgent (GPT-4o)',.2993,.5017,.3079,.5198,.3035,.5106,.3363,.4279],['Multi-Agents','Pandas Agent (GPT-4o)',.3024,.4973,.3112,.5133,.3067,.5052,.3289,.4021],['Multi-Agents','Agent Poirot (GPT-4o)',.2907,.5293,.2945,.5487,.2926,.5388,.3496,.4334],['Multi-Agents','Agent Poirot (Deepseek-V3)',.2590,.4984,.2658,.5453,.2624,.5208,.3165,.4772],['Multi-Agents','Agent Poirot (Claude-3.7-Sonnet)',.2623,.5519,.2673,.6261,.2648,.5867,.3178,.4746]];
async function loadModels(){const sel=$('model'),hint=$('modelHint'),previous=sel.value,api=$('api').value;sel.innerHTML='<option value="">Chargement…</option>';hint.textContent='';try{const r=await fetch('/models?api_base='+encodeURIComponent(api));const d=await r.json();sel.innerHTML='';if(d.error){sel.innerHTML='<option value="">Défaut du backend</option>';hint.textContent='Backend injoignable : '+d.error;return}const add=(label,list)=>{if(!list||!list.length)return;const group=document.createElement('optgroup');group.label=label;for(const item of list){const value=typeof item==='string'?item:(item.id||item.name);if(!value)continue;const option=document.createElement('option');option.value=value;option.textContent=value;group.appendChild(option)}sel.appendChild(group)};add('Modèles locaux (Ollama)',d.models);add('Modèles propriétaires',d.proprietary);if(!sel.options.length)sel.innerHTML='<option value="">Défaut du backend</option>';if(previous&&[...sel.options].some(o=>o.value===previous))sel.value=previous;else if(d.default)sel.value=d.default;hint.textContent=d.default?'Défaut du backend : '+d.default:''}catch(e){sel.innerHTML='<option value="">Défaut du backend</option>';hint.textContent='Impossible de charger les modèles : '+e.message}}
async function startEval(){$('err').textContent='';$('result').style.display='none';$('runbox').style.display='block';$('terminal').textContent='';$('start').disabled=true;$('cancel').disabled=false;const ids=$('ids').value.split(',').map(x=>parseInt(x.trim())).filter(Number.isFinite);const body={data_dir:$('dataDir').value.trim(),api_base:$('api').value.trim(),model:$('model').value,limit:parseInt($('limit').value)||0,instance_ids:ids,n_insights:parseInt($('nInsights').value)||10,language:$('language').value,allow_download:$('download').checked,with_interpretation:$('interpret').checked,with_geval:$('withGeval').checked,evaluator_model:$('evaluatorModel').value.trim()};const r=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){$('err').textContent=await r.text();$('start').disabled=false;return}watch()}
function watch(){source=new EventSource('/progress');source.onmessage=e=>{const d=JSON.parse(e.data);for(const line of d.log){$('terminal').textContent+=line+'\n';$('terminal').scrollTop=$('terminal').scrollHeight}const pct=d.total?100*d.progress/d.total:0;$('fill').style.width=pct+'%';$('counter').textContent=`${d.progress} / ${d.total}`;$('eta').textContent=d.eta?`ETA ${Math.ceil(d.eta/60)} min`:'';if(d.error){$('err').textContent=d.error}if(d.done){source.close();finish()}if(!d.running&&d.error){source.close();$('start').disabled=false;$('cancel').disabled=true}}}
async function finish(){const r=await fetch('/results');resultData=await r.json();const d=resultData,s=d.summary;const fmt=x=>x==null?'—':(100*x).toFixed(1)+' %';$('recall').textContent=fmt(s.insights_rouge1_recall);$('gRecall').textContent=fmt(s.insights_geval_recall);$('precision').textContent=fmt(s.insights_rouge1_precision);$('gPrecision').textContent=fmt(s.insights_geval_precision);$('f1').textContent=fmt(s.insights_rouge1_f1);$('gF1').textContent=fmt(s.insights_geval_f1);$('summary').textContent=fmt(s.summary_rouge1_f1);$('gSummary').textContent=fmt(s.summary_geval_f1);$('counts').textContent=`${s.n_evaluated} instance(s) évaluée(s), ${s.n_errors} erreur(s) · modèle ${s.model} · juge ${s.evaluator_model} · ${s.total_time_s} s.`;renderBaselines();renderBreakdown('categories',s.by_category||{});renderBreakdown('difficulties',s.by_difficulty||{});renderDetails(d.results||[],d.errors||[]);$('result').style.display='block';$('start').disabled=false;$('cancel').disabled=true}
function saliRow(){const s=resultData.summary;return ['SALI',s.model,s.insights_rouge1_recall,s.insights_geval_recall,s.insights_rouge1_precision,s.insights_geval_precision,s.insights_rouge1_f1,s.insights_geval_f1,s.summary_rouge1_f1,s.summary_geval_f1]}
function renderBaselines(){const rows=[...BASELINES,saliRow()],fmt=x=>x==null?'—':Number(x).toFixed(4);$('chartMetric').innerHTML=METRICS.map(([k,n],i)=>`<option value="${i}">${n}</option>`).join('');$('baselineTable').innerHTML=`<table class="baseline-table"><thead><tr><th>Baseline</th>${METRICS.map(x=>`<th>${x[1]}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr class="${r[0]==='SALI'?'sali':''}"><td>${esc(r[0]==='SALI'?'SALI ('+r[1]+')':r[1])}</td>${r.slice(2).map(v=>`<td>${fmt(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;renderBaselineChart()}
function renderBaselineChart(){if(!resultData)return;const canvas=$('baselineChart'),ctx=canvas.getContext('2d'),rows=[...BASELINES,saliRow()],mi=Number($('chartMetric').value)||0,dpr=devicePixelRatio||1,w=Math.max(720,canvas.clientWidth),h=430;canvas.width=w*dpr;canvas.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);ctx.font='11px system-ui';const left=235,right=35,top=20,rowH=(h-45)/rows.length,max=.7;ctx.strokeStyle='#2b303b';ctx.fillStyle='#9298a8';for(let i=0;i<=7;i++){const x=left+(w-left-right)*i/7;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,h-22);ctx.stroke();ctx.fillText((max*i/7).toFixed(1),x-8,h-7)}rows.forEach((r,i)=>{const v=r[2+mi],y=top+i*rowH+4;ctx.fillStyle=r[0]==='SALI'?'#22c55e':'#64748b';ctx.fillText(r[0]==='SALI'?'SALI ('+r[1]+')':r[1],5,y+10);if(v!=null){ctx.fillRect(left,y,Math.max(1,(w-left-right)*v/max),Math.max(8,rowH-7));ctx.fillStyle='#f4f5f7';ctx.fillText(Number(v).toFixed(4),left+(w-left-right)*v/max+5,y+10)}})}
function esc(v){const e=document.createElement('div');e.textContent=v==null?'':String(v);return e.innerHTML}
function renderBreakdown(id,data){const fmt=x=>x==null?'—':(100*x).toFixed(1)+' %';$(id).innerHTML=Object.entries(data).map(([name,m])=>`<div class="stat"><span>${esc(name)} · n=${m.n}</span><div class="metric-row"><em>Insight F1 R-1</em><span class="bar"><i style="width:${100*m.f1}%"></i></span><strong>${fmt(m.f1)}</strong></div><div class="metric-row"><em>Insight F1 G-Eval</em><span class="bar"><i style="width:${100*(m.geval_f1||0)}%"></i></span><strong>${fmt(m.geval_f1)}</strong></div><div class="metric-row"><em>Résumé R-1</em><span class="bar"><i style="width:${100*m.summary_f1}%"></i></span><strong>${fmt(m.summary_f1)}</strong></div><div class="metric-row"><em>Résumé G-Eval</em><span class="bar"><i style="width:${100*(m.summary_geval||0)}%"></i></span><strong>${fmt(m.summary_geval)}</strong></div></div>`).join('')||'<p class="lead">Pas de données.</p>'}
function renderDetails(results,errors){const fmt=x=>(100*x).toFixed(1)+' %';const comparisons=x=>(x.question_comparisons||[]).map(c=>{const cls=c.rouge1_similarity>=.5?'score-high':c.rouge1_similarity>=.25?'score-mid':'score-low';return `<div class="comparison"><div class="comparison-head"><b>Question ${c.question_number} · ${esc(c.question)}</b><span class="pill ${cls}">${esc(c.data_type||'')} · ${fmt(c.rouge1_similarity)}</span></div><div class="answer-grid"><div class="answer expected"><label>Réponse attendue</label><p>${esc(c.expected)}</p></div><div class="answer obtained"><label>Meilleure réponse obtenue${c.obtained_index?' · insight '+c.obtained_index:''}</label><p>${esc(c.obtained||'Aucune réponse obtenue')}</p></div></div></div>`}).join('');$('details').innerHTML=results.map(x=>`<details class="detail"><summary><span>#${x.instance_id} · ${esc(x.header||'Sans titre')}</span><span class="pill">F1 ${fmt(x.insight_rouge1.f1)}</span></summary><div class="detail-body"><b>${esc(x.category||'')} · difficulté ${esc(x.difficulty||'—')}</b><h4>Objectif</h4><p>${esc(x.goal)}</p><details class="detail"><summary>Preuves Python utilisées</summary><div class="detail-body"><pre style="white-space:pre-wrap">${esc(x.evidence_response||'Aucune trace de preuve')}</pre></div></details><h4>Comparaison par question</h4>${comparisons(x)}<h4>Résumé attendu</h4><div class="answer expected"><p>${esc(x.reference_summary||'Aucun résumé de référence')}</p></div><h4>Résumé obtenu</h4><div class="answer obtained"><p>${esc(x.predicted_summary||'Aucun résumé parsé')}</p></div><p>Recall ${fmt(x.insight_rouge1.recall)} · Precision ${fmt(x.insight_rouge1.precision)} · Format ${x.format_ok?'respecté':'incomplet'}</p></div></details>`).join('');$('errorDetails').innerHTML=errors.length?`<details class="detail errors"><summary>${errors.length} erreur(s)</summary><div class="detail-body"><ul>${errors.map(e=>`<li>#${e.instance_id}: ${esc(e.error)}</li>`).join('')}</ul></div></details>`:''}
function blobDownload(content,type,name){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)}
function downloadJSON(){if(resultData)blobDownload(JSON.stringify(resultData,null,2),'application/json','insighteval_results.json')}
function downloadCSV(){if(!resultData)return;const q=v=>'"'+String(v??'').replaceAll('"','""')+'"';const rows=[['instance_id','header','category','difficulty','recall_rouge1','recall_geval','precision_rouge1','precision_geval','f1_rouge1','f1_geval','summary_rouge1','summary_geval','format_ok'],...resultData.results.map(x=>[x.instance_id,x.header,x.category,x.difficulty,x.insight_rouge1.recall,x.insight_geval?.recall,x.insight_rouge1.precision,x.insight_geval?.precision,x.insight_rouge1.f1,x.insight_geval?.f1,x.summary_rouge1.fmeasure,x.summary_geval?.fmeasure,x.format_ok])];blobDownload(rows.map(r=>r.map(q).join(',')).join('\n'),'text/csv;charset=utf-8','insighteval_results.csv')}
async function downloadPDF(save){const options={margin:8,filename:'insighteval_report.pdf',image:{type:'jpeg',quality:.96},html2canvas:{scale:2,backgroundColor:'#0d0f14'},jsPDF:{unit:'mm',format:'a4',orientation:'portrait'}};if(!save){await html2pdf().set(options).from($('report')).save();return}const blob=await html2pdf().set(options).from($('report')).outputPdf('blob');const r=await fetch('/save_pdf',{method:'POST',headers:{'Content-Type':'application/pdf'},body:blob});const d=await r.json();alert(r.ok?'Rapport sauvegardé : '+d.filename:'Erreur : '+JSON.stringify(d))}
async function cancelEval(){await fetch('/cancel',{method:'POST'});$('cancel').disabled=true}loadModels();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


if __name__ == "__main__":
    print(f"InsightEval UI: http://127.0.0.1:{EVAL_PORT}")
    uvicorn.run(app, host="127.0.0.1", port=EVAL_PORT)
