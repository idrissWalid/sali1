"""eval_analysis_server.py — Interface web d'évaluation sur InfiAgent-DABench.

Pendant de `eval_server.py` (résumés / MultiEURLEX), mais pour l'analyse de
données : mêmes usages — choisir le modèle, suivre la progression en direct,
annuler, consulter et exporter les résultats.

Toute la logique d'évaluation (upload, questionnement, parsing `@nom[valeur]`,
notation, agrégation) vit dans `eval_analysis.py` et est importée ici : le
script CLI et cette interface produisent donc rigoureusement les mêmes chiffres.

    python eval_analysis_server.py     puis  http://localhost:8002
"""

import json
import os
import time
from pathlib import Path
from threading import Thread

import requests as req_lib
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from eval_analysis import (
    ask_question,
    build_prompt,
    grade,
    load_jsonl,
    summarize,
    upload_csv,
)

DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_DATA_DIR = "data"
EVAL_PORT = 8002
REQUEST_DELAY = 0.2

state = {
    "running": False,
    "done": False,
    "progress": 0,
    "total": 0,
    "log": [],
    "results": [],
    "errors": [],
    "summary": {},
    "error": None,
    "start_time": None,
    "elapsed": 0,
    "eta": 0,
    "cancel_requested": False,
}


# ═══════════════════════════════════════════════════════════════════════════
#  WORKER
# ═══════════════════════════════════════════════════════════════════════════
def run_worker(data_dir: str, api_base: str, model: str, limit: int,
               tolerance: float, with_interpretation: bool, language: str):
    def log(msg):
        state["log"].append(msg)

    try:
        from collections import defaultdict

        base = Path(data_dir)
        questions_path = base / "da-dev-questions.jsonl"
        labels_path = base / "da-dev-labels.jsonl"
        tables_dir = base / "da-dev-tables"

        for path in (questions_path, labels_path):
            if not path.is_file():
                raise FileNotFoundError(
                    f"{path} introuvable. Récupérer le jeu DABench : "
                    "https://huggingface.co/datasets/infiagent/DAEval"
                )
        if not tables_dir.is_dir():
            raise FileNotFoundError(f"{tables_dir} introuvable (dossier des CSV).")

        log(f"📦 Chargement du jeu DABench depuis {base}…")
        questions = load_jsonl(questions_path)
        labels = {str(r.get("id")): r for r in load_jsonl(labels_path)}
        if limit:
            questions = questions[:limit]

        by_file = defaultdict(list)
        for question in questions:
            by_file[str(question.get("file_name"))].append(question)

        state["total"] = len(questions)
        state["start_time"] = time.time()
        log(f"✓ {len(questions)} questions sur {len(by_file)} fichiers · modèle : {model} · langue : {language}")
        if not with_interpretation:
            log("ℹ Upload sans texte d'accueil (2 appels LLM économisés par fichier)")

        graded, errors = [], []
        done = 0

        for file_name, file_questions in sorted(by_file.items()):
            if state.get("cancel_requested"):
                log("🛑 Évaluation annulée par l'utilisateur.")
                break

            csv_path = tables_dir / file_name
            if not csv_path.is_file():
                for question in file_questions:
                    errors.append({"id": question.get("id"), "file_name": file_name,
                                   "error": "CSV introuvable"})
                done += len(file_questions)
                state["progress"] = done
                log(f"✗ {file_name} → CSV introuvable ({len(file_questions)} questions ignorées)")
                continue

            try:
                session_id = upload_csv(api_base, csv_path, model, with_interpretation)
            except Exception as exc:
                for question in file_questions:
                    errors.append({"id": question.get("id"), "file_name": file_name,
                                   "error": f"upload : {exc}"})
                done += len(file_questions)
                state["progress"] = done
                log(f"✗ {file_name} → upload échoué : {exc}")
                continue

            for question in file_questions:
                if state.get("cancel_requested"):
                    break

                done += 1
                qid = str(question.get("id"))
                label = labels.get(qid)
                if label is None:
                    errors.append({"id": qid, "file_name": file_name, "error": "label absent"})
                    state["progress"] = done
                    continue

                try:
                    answer = ask_question(api_base, session_id,
                                          build_prompt(question, language),
                                          model, language)
                except Exception as exc:
                    errors.append({"id": qid, "file_name": file_name, "error": f"chat : {exc}"})
                    log(f"✗ [{done}/{state['total']}] q{qid} → {exc}")
                    state["progress"] = done
                    continue

                result = grade(question, label, answer, tolerance)
                graded.append(result)

                flag = "✓" if result["correct"] else ("~" if result["parsed_any"] else "✗")
                detail = "juste" if result["correct"] else (
                    "faux" if result["parsed_any"] else "format non respecté")
                log(f"{flag} [{done}/{state['total']}] q{qid} ({file_name}) → {detail}")

                elapsed = time.time() - state["start_time"]
                state["elapsed"] = elapsed
                state["eta"] = elapsed / done * (state["total"] - done)
                state["progress"] = done
                time.sleep(REQUEST_DELAY)

        summary = summarize(graded, errors)
        summary["model"] = model
        summary["with_interpretation"] = with_interpretation
        summary["language"] = language
        summary["total_time"] = time.time() - state["start_time"]

        state["results"] = graded
        state["errors"] = errors
        state["summary"] = summary
        state["eta"] = 0
        log("🎉 Évaluation terminée !")
        state["done"] = True
        state["running"] = False

    except Exception as exc:
        import traceback
        state["error"] = traceback.format_exc()
        log(f"💥 Erreur fatale : {exc}")
        state["running"] = False


# ═══════════════════════════════════════════════════════════════════════════
#  FASTAPI
# ═══════════════════════════════════════════════════════════════════════════
app = FastAPI(title="Eval Analyse de données — DABench")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class RunConfig(BaseModel):
    data_dir: str = DEFAULT_DATA_DIR
    api_base: str = DEFAULT_API_BASE
    model: str = ""
    limit: int = 0
    tolerance: float = 1e-6
    with_interpretation: bool = False
    language: str = "en"


@app.post("/run")
def route_run(cfg: RunConfig):
    if state["running"]:
        raise HTTPException(409, "Une évaluation est déjà en cours")
    state.update({
        "running": True, "done": False,
        "progress": 0, "total": 0,
        "log": [], "results": [], "errors": [], "summary": {},
        "error": None, "start_time": None, "elapsed": 0, "eta": 0,
        "cancel_requested": False,
    })
    Thread(
        target=run_worker,
        args=(cfg.data_dir, cfg.api_base, cfg.model, cfg.limit,
              cfg.tolerance, cfg.with_interpretation, cfg.language),
        daemon=True,
    ).start()
    return {"status": "started"}


@app.post("/cancel")
def route_cancel():
    state["cancel_requested"] = True
    return {"status": "cancelling"}


@app.get("/progress")
def route_progress():
    def generate():
        last = 0
        while True:
            chunk = json.dumps({
                "running": state["running"],
                "done": state["done"],
                "progress": state["progress"],
                "total": state["total"],
                "log": state["log"][last:],
                "error": state["error"],
                "eta": state.get("eta", 0),
                "elapsed": state.get("elapsed", 0),
            }, ensure_ascii=False)
            yield f"data: {chunk}\n\n"
            last = len(state["log"])
            if state["done"] or (not state["running"] and state["error"]):
                break
            time.sleep(0.8)
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/results")
def route_results():
    if not state["done"]:
        raise HTTPException(425, "Évaluation pas encore terminée")
    return JSONResponse({
        "summary": state["summary"],
        "results": state["results"],
        "errors": state["errors"],
    })


@app.get("/health")
def health():
    return {"status": "ok", "running": state["running"], "done": state["done"]}


@app.get("/models")
def get_models(api_base: str = DEFAULT_API_BASE):
    """Relaie la liste du backend : celui-ci n'annonce que les modèles dont la
    clé API est réellement configurée, ce qu'une liste codée en dur ici ne
    saurait pas."""
    try:
        response = req_lib.get(f"{api_base}/api/llm-models", timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"models": [], "proprietary": [], "default": "", "error": str(exc)}


@app.post("/save_pdf")
async def save_pdf(request: Request):
    pdf_bytes = await request.body()
    filename = f"eval_analysis_report_{int(time.time())}.pdf"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    with open(filepath, "wb") as handle:
        handle.write(pdf_bytes)
    return {"status": "ok", "filename": filename}


# ═══════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>EvalSuite — Analyse de données (DABench)</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#0d0f14;--ink2:#3a3f4e;--ink3:#7a8099;
  --bg:#f6f5f0;--surface:#fff;--surface2:#f0efe9;
  --accent:#0b6fd4;--accent2:#2889e8;
  --green:#1a7a4a;--amber:#b06000;--red:#b02020;
  --border:rgba(0,0,0,.08);--border2:rgba(0,0,0,.15);
  --r:10px;--mono:'DM Mono',monospace;--title:'Syne',sans-serif;
}
body{background:var(--bg);color:var(--ink);font-family:var(--title);min-height:100vh;}
nav{background:var(--ink);color:#fff;padding:0 40px;height:56px;display:flex;align-items:center;justify-content:space-between;}
.nav-logo{font-size:15px;font-weight:700;letter-spacing:.5px;display:flex;align-items:center;gap:10px;}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent2);}
.nav-sub{font-family:var(--mono);font-size:11px;color:rgba(255,255,255,.4);letter-spacing:1px;}
.page{max-width:940px;margin:0 auto;padding:48px 24px 80px;}
.hero{margin-bottom:40px;}
.hero h1{font-size:clamp(30px,5vw,50px);font-weight:800;line-height:1.05;letter-spacing:-1.5px;margin-bottom:8px;}
.hero h1 em{font-style:normal;color:var(--accent);}
.hero p{font-family:var(--mono);font-size:11px;color:var(--ink3);}
.sl{font-family:var(--mono);font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--ink3);margin-bottom:10px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px 28px;margin-bottom:20px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px;}
.fld label{display:block;font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:var(--ink3);margin-bottom:6px;}
.fld input,.fld select{width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:6px;padding:9px 12px;font-family:var(--mono);font-size:12px;color:var(--ink);outline:none;transition:border-color .2s;}
.fld input:focus,.fld select:focus{border-color:var(--accent);}
.chk{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;color:var(--ink2);margin-bottom:18px;}
.chk input{width:auto;}
.hint{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-top:5px;line-height:1.5;}
.btn{background:var(--ink);color:#fff;font-family:var(--title);font-weight:700;font-size:14px;border:none;border-radius:8px;padding:12px 28px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:background .2s,transform .1s;}
.btn:hover{background:var(--accent);}
.btn:active{transform:scale(.98);}
.btn:disabled{opacity:.35;cursor:not-allowed;transform:none;}
.btn-o{background:transparent;color:var(--ink);border:1px solid var(--border2);border-radius:8px;padding:10px 20px;font-family:var(--title);font-weight:600;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:7px;transition:background .15s;}
.btn-o:hover{background:var(--surface2);}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:28px;}
#term-wrap{display:none;margin-bottom:20px;}
.term-box{background:#0d0f14;border-radius:var(--r);padding:20px 24px;}
.prog-lbl{font-family:var(--mono);font-size:10px;color:#4a5a70;margin-bottom:8px;}
.prog-bar{height:3px;background:rgba(255,255,255,.07);border-radius:2px;margin-bottom:14px;}
.prog-fill{height:100%;background:var(--accent2);border-radius:2px;transition:width .5s ease;width:0;}
.term{max-height:240px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.75;color:#7a8fa8;}
.lok{color:#4fd68a;}.lerr{color:#f07070;}.linf{color:#7ab8f5;}.ldone{color:#f5c542;}.lwarn{color:#f5a742;}
#err-box{display:none;background:#fff5f5;border:1px solid #f5b5b5;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-family:var(--mono);font-size:12px;color:var(--red);white-space:pre-wrap;}
#res-section{display:none;}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:24px;}
.stat-box{background:var(--surface2);border-radius:8px;padding:16px 18px;}
.stat-box .sv{font-size:26px;font-weight:800;letter-spacing:-1px;}
.stat-box .sk{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:var(--ink3);margin-bottom:4px;}
.stat-box .sd{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-top:2px;}
.mblock{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:22px 26px;margin-bottom:14px;}
.mhead{font-size:14px;font-weight:700;margin-bottom:2px;}
.msub{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-bottom:16px;}
.mrow{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.mrow:last-child{margin-bottom:0;}
.mkey{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--ink3);width:120px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;}
.bwrap{flex:1;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden;}
.bfill{height:100%;border-radius:3px;transition:width 1s cubic-bezier(.4,0,.2,1);width:0%;}
.fa{background:var(--accent);}.fb{background:var(--ink2);}
.mval{font-family:var(--mono);font-size:12px;font-weight:500;width:56px;text-align:right;}
.mval.wide{width:62px;}
/* Effectifs à côté du pourcentage : « 60,0 % » ne dit pas s'il porte sur 5
   questions ou sur 200. Largeur fixe pour que la colonne reste alignée. */
.mfrac{font-family:var(--mono);font-size:11px;color:var(--ink3);width:64px;text-align:right;flex-shrink:0;}
.badge{font-family:var(--mono);font-size:10px;padding:2px 9px;border-radius:20px;margin-left:8px;font-weight:500;}
.bg{background:#e2f5ea;color:var(--green);}.ba{background:#fef3e0;color:var(--amber);}.bb{background:#fde8e8;color:var(--red);}
#det-section{display:none;margin-top:4px;}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;}
.chart-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px 22px;}
.chart-card .ct{font-size:13px;font-weight:700;margin-bottom:2px;}
.chart-card .cd{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-bottom:12px;}
.tbl{width:100%;border-collapse:collapse;font-size:12px;}
.tbl th{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--ink3);font-weight:500;text-align:left;padding:6px 10px 8px;border-bottom:1px solid var(--border);}
.tbl td{padding:8px 10px;border-bottom:1px solid var(--border);font-family:var(--mono);}
.tbl tr:last-child td{border-bottom:none;}
.tbl td.ok{color:var(--green);}.tbl td.ko{color:var(--red);}
.scroll{max-height:420px;overflow-y:auto;}
@media(max-width:600px){.grid2,.chart-grid{grid-template-columns:1fr;}}
@media print{
  nav,.hero,.actions,#term-wrap,#err-box,.btn,.card:not(#term-wrap){display:none !important;}
  body{background:#fff !important;}
  .page{padding:0 !important;max-width:100% !important;}
  .mblock,.stat-box,.chart-card{break-inside:avoid;border:1px solid #ddd !important;}
  .bfill{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
}
</style>
</head>
<body>
<nav>
  <div class="nav-logo"><div class="dot"></div>EvalSuite</div>
  <div class="nav-sub">InfiAgent-DABench · exact match · accuracy / format</div>
</nav>
<div class="page">

  <div class="hero">
    <h1>Évaluation<br/><em>Analyse de données</em></h1>
    <p>// InfiAgent-DABench &nbsp;·&nbsp; questions en forme fermée &nbsp;·&nbsp; @nom[valeur] &nbsp;·&nbsp; accuracy · respect du format · par niveau · par concept</p>
  </div>

  <div class="sl">Configuration</div>
  <div class="card">
    <div class="grid2">
      <div class="fld"><label>Modèle (LLM évalué)</label>
        <select id="cfg-model"></select>
        <div class="hint" id="model-hint"></div></div>
      <div class="fld"><label>Dossier du jeu DABench</label>
        <input id="cfg-data" value="data"/>
        <div class="hint">doit contenir da-dev-questions.jsonl, da-dev-labels.jsonl, da-dev-tables/</div></div>
      <div class="fld"><label>Nombre de questions (0 = toutes)</label>
        <input id="cfg-limit" type="number" value="20" min="0"/></div>
      <div class="fld"><label>API Sali AI</label>
        <input id="cfg-api" value="http://127.0.0.1:8000"/></div>
      <div class="fld"><label>Tolérance numérique</label>
        <input id="cfg-tol" value="0.000001"/>
        <div class="hint">écart absolu accepté entre deux nombres</div></div>
      <div class="fld"><label>Langue des réponses</label>
        <select id="cfg-lang">
          <option value="en" selected>Anglais (comme le jeu DABench)</option>
          <option value="fr">Français (comportement du produit)</option>
        </select>
        <div class="hint">l'agent répond en français en usage normal ; DABench pose ses questions en anglais</div></div>
    </div>
    <div class="chk">
      <input type="checkbox" id="cfg-interp"/>
      <label for="cfg-interp" style="margin:0;text-transform:none;letter-spacing:0;font-size:11px;">
        Laisser l'upload produire son texte d'accueil (2 appels LLM de plus par fichier, sans effet sur les réponses)
      </label>
    </div>
    <button class="btn" id="btn-run" onclick="startEval()">&#9654; Lancer l'évaluation</button>
  </div>

  <div id="term-wrap">
    <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:10px;">
      <div class="sl" style="margin-bottom:0;">Progression en temps réel</div>
      <button class="btn-o" id="btn-cancel" onclick="cancelEval()" style="padding:4px 10px;font-size:10px;color:#f07070;border-color:#f07070;">🛑 Arrêter</button>
    </div>
    <div class="card term-box" style="border-color:rgba(255,255,255,.06);margin-bottom:0;">
      <div class="prog-lbl" id="prog-lbl">0 / 0</div>
      <div class="prog-bar"><div class="prog-fill" id="prog-fill"></div></div>
      <div class="term" id="term"></div>
    </div>
  </div>

  <div id="err-box"></div>

  <div id="res-section">
    <div class="sl">Résultats</div>
    <div class="stat-grid" id="stat-grid"></div>
    <div id="main-block" class="mblock"></div>
    <div id="level-block" class="mblock"></div>

    <div class="actions">
      <button class="btn-o" id="btn-det" onclick="toggleDetail()">&#9707; Détail par question</button>
      <button class="btn-o" onclick="exportJSON()">&#8675; Exporter JSON</button>
      <button class="btn-o" onclick="exportPDF()">&#128462; Exporter PDF</button>
    </div>

    <div id="det-section">
      <div class="sl">Par concept</div>
      <div class="mblock" id="concept-block"></div>
      <div class="chart-grid">
        <div class="chart-card"><div class="ct">Accuracy par niveau</div><div class="cd">proportion de réponses justes</div>
          <div style="position:relative;height:190px;"><canvas id="c-level"></canvas></div></div>
        <div class="chart-card"><div class="ct">Répartition des issues</div><div class="cd">juste · faux · format non respecté · erreur</div>
          <div style="position:relative;height:190px;"><canvas id="c-outcome"></canvas></div></div>
      </div>
      <div class="sl">Questions</div>
      <div class="mblock scroll" id="q-block"></div>
      <div class="sl">Erreurs</div>
      <div class="mblock scroll" id="e-block"></div>
    </div>
  </div>

</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
let _data=null,_detOpen=false,_charts={};
const esc = s => String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const pct = v => v==null ? '—' : (v*100).toFixed(1)+'%';
// Un pourcentage seul est intrompable : « 100 % » sur 2 questions n'a pas le
// même poids que sur 80. Chaque score est donc affiché avec sa fraction.
const frac = e => e ? e.correct+' / '+e.total : '—';
const pctFrac = e => e ? pct(e.rate)+'  ('+e.correct+'/'+e.total+')' : '—';

window.addEventListener('DOMContentLoaded', loadModels);

async function loadModels(){
  const sel=document.getElementById('cfg-model');
  const hint=document.getElementById('model-hint');
  try{
    const api=document.getElementById('cfg-api').value.trim();
    const d=await (await fetch('/models?api_base='+encodeURIComponent(api))).json();
    sel.innerHTML='';
    if(d.error){ hint.textContent='Backend injoignable : '+d.error; return; }
    const add=(label,list)=>{
      if(!list||!list.length) return;
      const g=document.createElement('optgroup'); g.label=label;
      list.forEach(m=>{ const o=document.createElement('option'); o.value=m; o.textContent=m; g.appendChild(o); });
      sel.appendChild(g);
    };
    add('Modèles locaux (Ollama)', d.models);
    add('Modèles propriétaires', d.proprietary);
    if(d.default) sel.value=d.default;
    hint.textContent = d.default ? ('défaut du backend : '+d.default) : '';
  }catch(e){ hint.textContent='Impossible de charger la liste : '+e.message; }
}

async function startEval(){
  const btn=document.getElementById('btn-run');
  btn.disabled=true;
  document.getElementById('err-box').style.display='none';
  document.getElementById('res-section').style.display='none';
  document.getElementById('term-wrap').style.display='block';
  const c=document.getElementById('btn-cancel');
  c.style.display='inline-flex'; c.disabled=false; c.textContent='🛑 Arrêter';
  document.getElementById('term').innerHTML='';
  document.getElementById('prog-fill').style.width='0%';
  document.getElementById('prog-lbl').textContent='Démarrage…';

  const body={
    data_dir: document.getElementById('cfg-data').value.trim(),
    api_base: document.getElementById('cfg-api').value.trim(),
    model:    document.getElementById('cfg-model').value.trim(),
    limit:    parseInt(document.getElementById('cfg-limit').value)||0,
    tolerance:parseFloat(document.getElementById('cfg-tol').value)||1e-6,
    with_interpretation: document.getElementById('cfg-interp').checked,
    language: document.getElementById('cfg-lang').value,
  };
  try{
    const r=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){ const e=await r.json().catch(()=>({})); throw new Error(e.detail||('HTTP '+r.status)); }
    listenSSE();
  }catch(e){ showErr(e.message); btn.disabled=false; }
}

async function cancelEval(){
  const c=document.getElementById('btn-cancel');
  c.disabled=true; c.textContent='Arrêt en cours…';
  await fetch('/cancel',{method:'POST'});
}

function showErr(msg){
  const b=document.getElementById('err-box');
  b.textContent='⚠  '+msg; b.style.display='block';
}

function fmtTime(s){
  if(!s||s<0) return '--:--';
  const m=Math.floor(s/60), sec=Math.floor(s%60);
  return m+'m '+(sec<10?'0':'')+sec+'s';
}

function listenSSE(){
  const es=new EventSource('/progress');
  const term=document.getElementById('term');
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.error){ showErr(d.error); es.close(); document.getElementById('btn-run').disabled=false; return; }
    (d.log||[]).forEach(line=>{
      const div=document.createElement('div');
      div.className = line.startsWith('✓')?'lok' : (line.startsWith('✗')||line.startsWith('💥'))?'lerr'
                    : line.startsWith('~')?'lwarn' : line.startsWith('🎉')?'ldone':'linf';
      div.textContent=line; term.appendChild(div);
    });
    term.scrollTop=term.scrollHeight;
    if(d.total>0){
      const p=Math.round(d.progress/d.total*100);
      document.getElementById('prog-fill').style.width=p+'%';
      document.getElementById('prog-lbl').textContent=
        d.progress+' / '+d.total+' ('+p+'%)'+(d.done?'':'  ·  ETA '+fmtTime(d.eta));
    }
    if(d.done){ document.getElementById('btn-cancel').style.display='none'; es.close(); fetchAndRender(); }
  };
  es.onerror=()=>es.close();
}

async function fetchAndRender(){
  const r=await fetch('/results');
  if(!r.ok){ showErr('Impossible de récupérer les résultats'); document.getElementById('btn-run').disabled=false; return; }
  _data=await r.json();
  render(_data);
  document.getElementById('btn-run').disabled=false;
}

function box(k,v,sub,small){
  return '<div class="stat-box"><div class="sk">'+k+'</div><div class="sv"'+(small?' style="font-size:15px;letter-spacing:0;"':'')+'>'+v+'</div><div class="sd">'+sub+'</div></div>';
}
const badge = v => v==null?'' : v>=.6?'<span class="badge bg">Bon</span>' : v>=.3?'<span class="badge ba">Moyen</span>' : '<span class="badge bb">Faible</span>';

function render(data){
  const s=data.summary;
  document.getElementById('stat-grid').innerHTML=
    box('Modèle', esc(s.model||'—'),'LLM évalué',true)+
    box('Langue', esc((s.language||'en').toUpperCase()),'réponses de l\'agent')+
    box('Accuracy', pct(s.accuracy), (s.n_correct??0)+' / '+(s.n_graded??0)+' justes')+
    box('Format', pct(s.format_compliance), (s.n_format_ok??0)+' / '+(s.n_graded??0)+' parsables')+
    box('Notées', s.n_graded,'sur '+s.n_questions+' questions')+
    box('Erreurs', s.n_errors,'upload / chat / label')+
    box('Durée', fmtTime(s.total_time),'temps total');

  document.getElementById('main-block').innerHTML=
    '<div class="mhead">Score global '+badge(s.accuracy)+'</div>'+
    '<div class="msub">// exact match sur les réponses en forme fermée, tolérance numérique appliquée</div>'+
    '<div class="mrow"><span class="mkey">Accuracy</span><div class="bwrap"><div class="bfill fa" id="b-acc"></div></div><span class="mval wide">'+pct(s.accuracy)+'</span><span class="mfrac">'+(s.n_correct??0)+'/'+(s.n_graded??0)+'</span></div>'+
    '<div class="mrow"><span class="mkey">Format</span><div class="bwrap"><div class="bfill fb" id="b-fmt"></div></div><span class="mval wide">'+pct(s.format_compliance)+'</span><span class="mfrac">'+(s.n_format_ok??0)+'/'+(s.n_graded??0)+'</span></div>';
  setTimeout(()=>{
    const a=document.getElementById('b-acc'), f=document.getElementById('b-fmt');
    if(a) a.style.width=((s.accuracy||0)*100).toFixed(1)+'%';
    if(f) f.style.width=((s.format_compliance||0)*100).toFixed(1)+'%';
  },120);

  const lv=s.accuracy_by_level||{};
  document.getElementById('level-block').innerHTML=
    '<div class="mhead">Par niveau de difficulté</div><div class="msub">// champ `level` du jeu DABench</div>'+
    (Object.keys(lv).length? Object.entries(lv).map(([k,v],i)=>
      '<div class="mrow"><span class="mkey">'+esc(k)+'</span><div class="bwrap"><div class="bfill fa" id="lvl'+i+'"></div></div><span class="mval wide">'+pct(v.rate)+'</span><span class="mfrac">'+v.correct+'/'+v.total+'</span></div>').join('')
      : '<div class="msub">aucune donnée</div>');
  setTimeout(()=>Object.entries(lv).forEach(([,v],i)=>{
    const el=document.getElementById('lvl'+i); if(el) el.style.width=(((v&&v.rate)||0)*100).toFixed(1)+'%';
  }),120);

  document.getElementById('res-section').style.display='block';
  document.getElementById('det-section').style.display='none';
  _detOpen=false;
  document.getElementById('btn-det').textContent='◈ Détail par question';
}

function toggleDetail(){
  if(!_data) return;
  _detOpen=!_detOpen;
  document.getElementById('det-section').style.display=_detOpen?'block':'none';
  document.getElementById('btn-det').textContent=_detOpen?'▲ Masquer le détail':'◈ Détail par question';
  if(_detOpen) renderDetail();
}

function renderDetail(){
  const s=_data.summary, docs=_data.results||[], errs=_data.errors||[];

  const bc=s.accuracy_by_concept||{};
  document.getElementById('concept-block').innerHTML=
    '<div class="mhead">Accuracy par concept</div><div class="msub">// champ `concepts` du jeu DABench</div>'+
    (Object.keys(bc).length?
      '<table class="tbl"><thead><tr><th>Concept</th><th>Accuracy</th><th>Justes</th><th>Total</th></tr></thead><tbody>'+
      Object.entries(bc).sort((a,b)=>((b[1]&&b[1].rate)||0)-((a[1]&&a[1].rate)||0)).map(([k,v])=>
        '<tr><td>'+esc(k)+'</td><td>'+pct(v.rate)+'</td><td>'+v.correct+'</td><td>'+v.total+'</td></tr>').join('')+'</tbody></table>'
      : '<div class="msub">aucune donnée</div>');

  document.getElementById('q-block').innerHTML=
    '<table class="tbl"><thead><tr><th>ID</th><th>Fichier</th><th>Niveau</th><th>Issue</th><th>Attendu</th><th>Obtenu</th></tr></thead><tbody>'+
    docs.map(d=>{
      const exp=(d.sub_answers||[]).map(a=>a.answer_name+'='+a.expected).join(', ');
      const got=(d.sub_answers||[]).map(a=>a.answer_name+'='+(a.got==null?'∅':a.got)).join(', ');
      const st=d.correct?'<td class="ok">juste</td>':(d.parsed_any?'<td class="ko">faux</td>':'<td class="ko">format</td>');
      return '<tr><td>'+esc(d.id)+'</td><td>'+esc(d.file_name)+'</td><td>'+esc(d.level)+'</td>'+st+
             '<td>'+esc(exp)+'</td><td>'+esc(got)+'</td></tr>';
    }).join('')+'</tbody></table>';

  document.getElementById('e-block').innerHTML= errs.length?
    '<table class="tbl"><thead><tr><th>ID</th><th>Fichier</th><th>Erreur</th></tr></thead><tbody>'+
    errs.map(e=>'<tr><td>'+esc(e.id)+'</td><td>'+esc(e.file_name)+'</td><td>'+esc(e.error)+'</td></tr>').join('')+
    '</tbody></table>' : '<div class="msub">aucune erreur</div>';

  const lv=s.accuracy_by_level||{};
  mkBar('c-level',
        Object.entries(lv).map(([k,v])=>k+' ('+v.correct+'/'+v.total+')'),
        Object.values(lv).map(v=>((v&&v.rate)||0)*100), '#0b6fd4');

  const nJuste=docs.filter(d=>d.correct).length;
  const nFaux=docs.filter(d=>!d.correct&&d.parsed_any).length;
  const nFmt=docs.filter(d=>!d.parsed_any).length;
  mkDoughnut('c-outcome',
    ['Juste ('+nJuste+')','Faux ('+nFaux+')','Format ('+nFmt+')','Erreur ('+errs.length+')'],
    [nJuste,nFaux,nFmt,errs.length]);
}

function mkBar(id,labels,values,color){
  if(_charts[id]) _charts[id].destroy();
  const el=document.getElementById(id); if(!el) return;
  _charts[id]=new Chart(el.getContext('2d'),{
    type:'bar',
    data:{labels,datasets:[{data:values,backgroundColor:color+'bb',borderColor:color,borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{y:{beginAtZero:true,max:100,ticks:{font:{size:9},callback:v=>v+'%'}},
              x:{ticks:{font:{size:9}},grid:{display:false}}}}
  });
}

function mkDoughnut(id,labels,values){
  if(_charts[id]) _charts[id].destroy();
  const el=document.getElementById(id); if(!el) return;
  _charts[id]=new Chart(el.getContext('2d'),{
    type:'doughnut',
    data:{labels,datasets:[{data:values,backgroundColor:['#1a7a4a','#b02020','#b06000','#7a8099']}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{position:'right',labels:{font:{size:10},boxWidth:12}}}}
  });
}

function exportJSON(){
  if(!_data) return;
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(_data,null,2)],{type:'application/json'}));
  a.download='eval_analysis_'+new Date().toISOString().slice(0,10)+'.json';
  a.click();
}

async function exportPDF(){
  if(!_detOpen) toggleDetail();
  await new Promise(r=>setTimeout(r,500));
  const hide=['.actions','nav','.hero'].map(s=>document.querySelector(s)).filter(Boolean);
  const prev=hide.map(el=>el.style.display);
  hide.forEach(el=>el.style.display='none');
  try{
    const blob=await html2pdf().set({
      margin:10, filename:'eval_analysis.pdf',
      image:{type:'jpeg',quality:.98}, html2canvas:{scale:2},
      jsPDF:{unit:'mm',format:'a4',orientation:'portrait'}
    }).from(document.body).output('blob');
    hide.forEach((el,i)=>el.style.display=prev[i]);
    const r=await fetch('/save_pdf',{method:'POST',headers:{'Content-Type':'application/pdf'},body:blob});
    if(!r.ok) showErr('Erreur lors de la sauvegarde du PDF sur le serveur.');
  }catch(e){
    hide.forEach((el,i)=>el.style.display=prev[i]);
    showErr('Erreur html2pdf : '+e);
  }
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def route_index():
    return HTML


if __name__ == "__main__":
    uvicorn.run("eval_analysis_server:app", host="0.0.0.0", port=EVAL_PORT, reload=False)
