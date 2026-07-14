# ═══════════════════════════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
import ssl
import certifi

# Patch SSLContext to prevent Windows ASN.1 certificate store loading issues
orig_load_default_certs = ssl.SSLContext.load_default_certs

def patched_load_default_certs(self, *args, **kwargs):
    try:
        return orig_load_default_certs(self, *args, **kwargs)
    except Exception:
        return self.load_verify_locations(cafile=certifi.where())

ssl.SSLContext.load_default_certs = patched_load_default_certs

import torch


import io, json, random, time
from pathlib import Path
from threading import Thread

import pdfplumber
import requests as req_lib
from rouge_score import rouge_scorer
from bert_score import score as bert_score_fn

# ── Nouvelles métriques ──────────────────────────────────────────────────────
import sacrebleu                                  # BLEU
import transformers.models.barthez.tokenization_barthez as tb
if hasattr(tb, "Unigram"):
    orig_unigram = tb.Unigram
    tb.Unigram = lambda vocab, *args, **kwargs: orig_unigram(list(vocab.items()) if isinstance(vocab, dict) else vocab, *args, **kwargs)
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM  # BARTScore
try:
    from bleurt import score as bleurt_score_lib  # BLEURT
except ImportError:
    bleurt_score_lib = None

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_JUSTIFY

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG PAR DÉFAUT
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULT_API_URL     = "http://127.0.0.1:8000/api/upload"
DEFAULT_SUMMARY_KEY = "summary"
DEFAULT_N_SAMPLES   = 150
DEFAULT_SPLIT       = "test"
RANDOM_SEED         = 42
REQUEST_DELAY       = 0.2
EVAL_PORT           = 8001

# ── Config nouvelles métriques ───────────────────────────────────────────────
try:
    import torch_directml
    DEVICE = torch_directml.device()
    print("[INFO] Acceleration GPU AMD (DirectML) activee pour PyTorch !")
except ImportError:
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Checkpoint BLEURT multilingue (FR inclus). À télécharger une fois :
#   wget https://storage.googleapis.com/bleurt-oss-21/BLEURT-20-D12.zip
#   unzip BLEURT-20-D12.zip
BLEURT_CHECKPOINT = "BLEURT-20-D12"

# Modèle seq2seq français pour BARTScore (Barthez). Téléchargé automatiquement
# par transformers au premier appel (~500 Mo).
BARTSCORE_MODEL    = "moussaKam/barthez"
BARTSCORE_MAXLEN   = 1024
BARTSCORE_BATCH    = 4

# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAT GLOBAL (partagé entre le thread worker et FastAPI)
# ═══════════════════════════════════════════════════════════════════════════════
state = {
    "running":  False,
    "done":     False,
    "progress": 0,
    "total":    0,
    "log":      [],
    "results":  [],
    "averages": {},
    "error":    None,
    "start_time": None,
    "elapsed": 0,
    "eta": 0,
    "cancel_requested": False,
}

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS PDF
# ═══════════════════════════════════════════════════════════════════════════════
def text_to_pdf_bytes(text: str, title: str = "Document") -> bytes:
    buf    = io.BytesIO()
    styles = getSampleStyleSheet()
    body   = ParagraphStyle("Body", parent=styles["Normal"],
                            fontSize=10, leading=14, alignment=TA_JUSTIFY)
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)
    story = [Paragraph(title[:120], styles["Heading1"]), Spacer(1, .4*cm)]
    for p in text.split("\n"):
        p = p.strip()
        if p:
            p = p.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            story += [Paragraph(p, body), Spacer(1, .15*cm)]
    doc.build(story)
    return buf.getvalue()

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return " ".join(p.extract_text() or "" for p in pdf.pages).strip()

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTRIQUES — ROUGE
# ═══════════════════════════════════════════════════════════════════════════════
_rscorer = rouge_scorer.RougeScorer(["rouge1","rouge2","rougeL"], use_stemmer=True)

def compute_rouge(ref: str, hyp: str) -> dict:
    s = _rscorer.score(ref, hyp)
    return {k: {"precision": round(s[k].precision, 4),
                "recall":    round(s[k].recall,    4),
                "f1":        round(s[k].fmeasure,  4)}
            for k in ["rouge1","rouge2","rougeL"]}

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTRIQUES — BLEU (sacrebleu, calcul léger par document)
# ═══════════════════════════════════════════════════════════════════════════════
def compute_bleu(ref: str, hyp: str) -> float:
    """BLEU phrase-level (sacrebleu), normalisé en [0,1] pour homogénéité avec
    les autres métriques (score brut sacrebleu est sur 0-100)."""
    if not ref.strip() or not hyp.strip():
        return 0.0
    b = sacrebleu.sentence_bleu(hyp, [ref])
    return round(b.score / 100, 4)

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTRIQUES — BLEURT (chargement paresseux, batch en fin de run)
# ═══════════════════════════════════════════════════════════════════════════════
_bleurt_scorer = None

def get_bleurt_scorer():
    global _bleurt_scorer
    if _bleurt_scorer is None:
        if bleurt_score_lib is None:
            raise ImportError("La bibliothèque 'bleurt' n'est pas installée.")
        _bleurt_scorer = bleurt_score_lib.BleurtScorer(BLEURT_CHECKPOINT)
    return _bleurt_scorer

def compute_bleurt_batch(refs: list, hyps: list) -> list:
    """Retourne une liste de scores BLEURT (≈ [0,1], peut légèrement dépasser)."""
    scorer = get_bleurt_scorer()
    return scorer.score(references=refs, candidates=hyps)

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTRIQUES — BARTScore (modèle français Barthez, chargement paresseux GPU)
# ═══════════════════════════════════════════════════════════════════════════════
class BARTScorer:
    """Calcule log P(résumé | document) avec un modèle seq2seq (Barthez).
    Score brut = log-vraisemblance moyenne par token (négatif, proche de 0
    = meilleur). On fournit aussi une version normalisée exp(score) ∈ (0,1]."""

    def __init__(self, model_name: str = BARTSCORE_MODEL,
                 device: str = DEVICE, max_length: int = BARTSCORE_MAXLEN):
        self.device     = device
        self.max_length = max_length
        self.tokenizer  = AutoTokenizer.from_pretrained(model_name)
        self.model      = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(device)
        self.model.eval()

    @torch.no_grad()
    def score(self, srcs: list, tgts: list, batch_size: int = BARTSCORE_BATCH) -> list:
        scores = []
        for i in range(0, len(srcs), batch_size):
            src_batch = srcs[i:i+batch_size]
            tgt_batch = tgts[i:i+batch_size]

            enc = self.tokenizer(src_batch, max_length=self.max_length, truncation=True,
                                  padding=True, return_tensors="pt").to(self.device)
            dec = self.tokenizer(tgt_batch, max_length=self.max_length, truncation=True,
                                  padding=True, return_tensors="pt").to(self.device)

            output = self.model(input_ids=enc.input_ids,
                                 attention_mask=enc.attention_mask,
                                 labels=dec.input_ids)

            logits = output.logits.view(-1, self.model.config.vocab_size)
            loss = torch.nn.functional.cross_entropy(
                logits, dec.input_ids.view(-1), reduction="none",
                ignore_index=self.tokenizer.pad_token_id,
            ).view(dec.input_ids.shape)

            mask     = (dec.input_ids != self.tokenizer.pad_token_id).float()
            seq_loss = (loss * mask).sum(dim=1) / mask.sum(dim=1)  # NLL moyenne/token

            scores.extend((-seq_loss).tolist())
        return scores

_bart_scorer = None

def get_bart_scorer():
    global _bart_scorer
    if _bart_scorer is None:
        _bart_scorer = BARTScorer()
    return _bart_scorer

def compute_bartscore_batch(docs: list, summaries: list) -> list:
    """Retourne une liste de dicts {raw, norm} : raw = log-vraisemblance
    moyenne/token (négatif), norm = exp(raw) ∈ (0,1] pour l'affichage."""
    scorer = get_bart_scorer()
    raw = scorer.score(docs, summaries)
    out = []
    for r in raw:
        import math
        norm = math.exp(max(r, -20))  # clip pour éviter underflow
        out.append({"raw": round(r, 4), "norm": round(min(norm, 1.0), 4)})
    return out

# ═══════════════════════════════════════════════════════════════════════════════
#  AGRÉGATION
# ═══════════════════════════════════════════════════════════════════════════════
def mean(v: list) -> float:
    return sum(v)/len(v) if v else 0.0

def compute_averages(results: list) -> dict:
    ok = [r for r in results if r["status"] == "success"]
    if not ok:
        return {}
    def ar(m, s): return round(mean([r["rouge"][m][s] for r in ok]), 4)
    def ab(s):
        bs = [r["bert_score"][s] for r in ok if r.get("bert_score")]
        return round(mean(bs), 4) if bs else None
    def af(field):
        vals = [r[field] for r in ok if r.get(field) is not None]
        return round(mean(vals), 4) if vals else None
    def afn(field, sub):
        vals = [r[field][sub] for r in ok if r.get(field)]
        return round(mean(vals), 4) if vals else None

    return {
        "n_success":       len(ok),
        "n_error":         len([r for r in results if r["status"] == "error"]),
        "n_skipped":       len([r for r in results if r["status"] == "skipped"]),
        "avg_compression": round(mean([r["compression_pct"] for r in ok]), 2),
        "avg_doc_words":   round(mean([r["document_words"]  for r in ok])),
        "avg_sum_words":   round(mean([r["summary_words"]   for r in ok])),
        "rouge": {
            "rouge1": {"precision": ar("rouge1","precision"), "recall": ar("rouge1","recall"), "f1": ar("rouge1","f1")},
            "rouge2": {"precision": ar("rouge2","precision"), "recall": ar("rouge2","recall"), "f1": ar("rouge2","f1")},
            "rougeL": {"precision": ar("rougeL","precision"), "recall": ar("rougeL","recall"), "f1": ar("rougeL","f1")},
        },
        "bert_score": {"precision": ab("precision"), "recall": ab("recall"), "f1": ab("f1")},
        "bleu":       af("bleu"),
        "bleurt":     af("bleurt"),
        "bart_score": {"raw": afn("bart_score","raw"), "norm": afn("bart_score","norm")},
    }

# ═══════════════════════════════════════════════════════════════════════════════
#  WORKER THREAD
# ═══════════════════════════════════════════════════════════════════════════════
def run_worker(api_url: str, summary_key: str, n_samples: int, split: str, model_name: str):
    def log(msg): state["log"].append(msg)

    try:
        from datasets import load_dataset

        log("📦 Chargement du dataset MultiEURLEX (fr)…")
        _parquet_url = (
            "https://huggingface.co/datasets/nlpaueb/multi_eurlex"
            f"/resolve/refs%2Fconvert%2Fparquet/fr/{split}/0000.parquet"
        )
        ds = load_dataset("parquet", data_files=_parquet_url, split="train")
        log(f"✓ {len(ds)} documents disponibles (split={split})")

        random.seed(RANDOM_SEED)
        n = min(n_samples, len(ds))
        indices = random.sample(range(len(ds)), n)
        samples = [ds[i] for i in indices]
        state["total"] = n
        state["start_time"] = time.time()
        log(f"🎲 {n} documents sélectionnés aléatoirement (seed={RANDOM_SEED})")

        results    = []
        sample_map = {}   # celex_id → texte original (pour BERTScore / BLEURT / BARTScore)

        for i, sample in enumerate(samples, 1):
            if state.get("cancel_requested"):
                log("🛑 Évaluation annulée par l'utilisateur.")
                break

            # ── Champs du dataset MultiEURLEX ──────────────────────────────
            text    = sample.get("text", "").strip()
            doc_id  = sample.get("celex_id", f"doc_{i:04d}")
            sample_map[doc_id] = text

            if not text:
                results.append({"doc_id": doc_id, "status": "skipped", "reason": "empty"})
                state["progress"] = i
                continue

            # ── Génération PDF ─────────────────────────────────────────────
            try:
                pdf_bytes = text_to_pdf_bytes(text, title=doc_id)
            except Exception as e:
                results.append({"doc_id": doc_id, "status": "error", "error": f"pdf_gen: {e}"})
                state["progress"] = i
                continue

            # Texte de référence extrait du PDF (cohérence avec ce que reçoit l'API)
            ref_text = extract_text_from_pdf(pdf_bytes)

            # ── Appel API résumé ───────────────────────────────────────────
            summary = None
            try:
                resp = req_lib.post(
                    api_url,
                    data={"model": model_name, "index_doc": "false"},
                    files={"file": (f"{doc_id}.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                    timeout=600,
                )
                resp.raise_for_status()

                # Décodage réponse NDJSON (streaming)
                for line in resp.text.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("status") == "error":
                        raise ValueError(data.get("message", "erreur API"))
                    if data.get("status") == "completed":
                        payload = data.get("data", {})
                        if summary_key in payload:
                            summary = payload[summary_key]
                            break

                if not summary:
                    raise ValueError(f"clé '{summary_key}' introuvable dans la réponse")

            except Exception as e:
                results.append({"doc_id": doc_id, "status": "error",
                                 "error": str(e), "text_length": len(text)})
                log(f"✗ [{i}/{n}] {doc_id} → {e}")
                state["progress"] = i
                time.sleep(REQUEST_DELAY)
                continue

            # ── ROUGE + BLEU (peu coûteux, calculés à la volée) ─────────────
            rouge = compute_rouge(ref_text, summary)
            bleu  = compute_bleu(ref_text, summary)
            n_doc = len(ref_text.split())
            n_sum = len(summary.split())

            results.append({
                "doc_id":          doc_id,
                "status":          "success",
                "text_length":     len(text),
                "document_words":  n_doc,
                "summary_words":   n_sum,
                "compression_pct": round(n_sum / n_doc * 100, 2) if n_doc else 0,
                "summary": summary,
                "rouge":           rouge,
                "bleu":            bleu,
                "bert_score":      None,
                "bleurt":          None,
                "bart_score":      None,
            })

            log(f"✓ [{i}/{n}] {doc_id} | "
                f"R1={rouge['rouge1']['f1']:.3f}  "
                f"R2={rouge['rouge2']['f1']:.3f}  "
                f"RL={rouge['rougeL']['f1']:.3f}  "
                f"BLEU={bleu:.3f}")

            elapsed = time.time() - state["start_time"]
            avg_time = elapsed / i
            state["eta"] = avg_time * (n - i)
            state["elapsed"] = elapsed
            state["progress"] = i
            time.sleep(REQUEST_DELAY)

        # ── Métriques batch (BERTScore, BLEURT, BARTScore) ──────────────────
        ok_items = [r for r in results if r["status"] == "success"]
        if ok_items:
            refs = [sample_map.get(r["doc_id"], "") for r in ok_items]
            hyps = [r.get("summary", "") for r in ok_items]

            # BERTScore
            log(f"🧠 Calcul BERTScore batch sur {len(ok_items)} documents…")
            try:
                chunk_size = 100
                for i in range(0, len(ok_items), chunk_size):
                    chk_refs = refs[i:i+chunk_size]
                    chk_hyps = hyps[i:i+chunk_size]
                    P, R, F1 = bert_score_fn(chk_hyps, chk_refs, lang="fr", verbose=False, device=DEVICE)
                    for r, p, rc, f in zip(ok_items[i:i+chunk_size], P.tolist(), R.tolist(), F1.tolist()):
                        r["bert_score"] = {
                            "precision": round(p,  4),
                            "recall":    round(rc, 4),
                            "f1":        round(f,  4),
                        }
                    log(f"  BERT batch {i//chunk_size + 1}/{(len(ok_items)-1)//chunk_size + 1} traité")
            except Exception as e:
                log(f"⚠ BERTScore indisponible : {e}")

            # BLEURT
            log(f"📐 Calcul BLEURT batch sur {len(ok_items)} documents (checkpoint={BLEURT_CHECKPOINT})…")
            try:
                chunk_size = 100
                all_bleurt = []
                for i in range(0, len(ok_items), chunk_size):
                    chk_refs = refs[i:i+chunk_size]
                    chk_hyps = hyps[i:i+chunk_size]
                    batch_scores = compute_bleurt_batch(chk_refs, chk_hyps)
                    all_bleurt.extend(batch_scores)
                    log(f"  BLEURT batch {i//chunk_size + 1}/{(len(ok_items)-1)//chunk_size + 1} traité")
                for r, b in zip(ok_items, all_bleurt):
                    r["bleurt"] = round(float(b), 4)
            except Exception as e:
                log(f"⚠ BLEURT indisponible : {e}")

            # BARTScore
            log(f"📐 Calcul BARTScore batch sur {len(ok_items)} documents (modèle={BARTSCORE_MODEL}, device={DEVICE})…")
            try:
                chunk_size = 100
                all_bart = []
                for i in range(0, len(ok_items), chunk_size):
                    chk_refs = refs[i:i+chunk_size]
                    chk_hyps = hyps[i:i+chunk_size]
                    batch_scores = compute_bartscore_batch(chk_refs, chk_hyps)
                    all_bart.extend(batch_scores)
                    log(f"  BARTScore batch {i//chunk_size + 1}/{(len(ok_items)-1)//chunk_size + 1} traité")
                for r, s in zip(ok_items, all_bart):
                    r["bart_score"] = s
            except Exception as e:
                log(f"⚠ BARTScore indisponible : {e}")

        state["results"]  = results
        state["averages"] = compute_averages(results)
        state["averages"]["model"] = model_name
        state["averages"]["total_time"] = time.time() - state["start_time"]
        state["eta"] = 0
        log("🎉 Évaluation terminée !")
        state["done"]    = True
        state["running"] = False

    except Exception as e:
        import traceback
        state["error"]   = traceback.format_exc()
        log(f"💥 Erreur fatale : {e}")
        state["running"] = False

# ═══════════════════════════════════════════════════════════════════════════════
#  FASTAPI
# ═══════════════════════════════════════════════════════════════════════════════
app = FastAPI(title="Eval Résumés")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

class RunConfig(BaseModel):
    api_url:     str = DEFAULT_API_URL
    summary_key: str = DEFAULT_SUMMARY_KEY
    n_samples:   int = DEFAULT_N_SAMPLES
    split:       str = DEFAULT_SPLIT
    model:       str = "gemini-3.1-flash-lite-preview"

@app.post("/run")
def route_run(cfg: RunConfig):
    if state["running"]:
        raise HTTPException(409, "Une évaluation est déjà en cours")
    # Reset complet
    state.update({
        "running": True, "done": False,
        "progress": 0,   "total": 0,
        "log": [],        "results": [],
        "averages": {},   "error": None,
        "start_time": None, "elapsed": 0, "eta": 0,
        "cancel_requested": False
    })
    Thread(
        target=run_worker,
        args=(cfg.api_url, cfg.summary_key, cfg.n_samples, cfg.split, cfg.model),
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
                "running":  state["running"],
                "done":     state["done"],
                "progress": state["progress"],
                "total":    state["total"],
                "log":      state["log"][last:],
                "error":    state["error"],
                "eta":      state.get("eta", 0),
                "elapsed":  state.get("elapsed", 0),
            })
            yield f"data: {chunk}\n\n"
            last = len(state["log"])
            if state["done"] or (not state["running"] and state["error"]):
                break
            time.sleep(0.8)
    return StreamingResponse(generate(), media_type="text/event-stream")

import math

def sanitize_floats(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(x) for x in obj]
    return obj

@app.get("/results")
def route_results():
    if not state["done"]:
        raise HTTPException(425, "Évaluation pas encore terminée")
    payload = {"averages": state["averages"], "documents": state["results"]}
    return JSONResponse(sanitize_floats(payload))

@app.get("/health")
def health():
    return {"status": "ok", "running": state["running"], "done": state["done"]}

import os
from fastapi import Request

@app.post("/save_pdf")
async def save_pdf(request: Request):
    pdf_bytes = await request.body()
    import time
    filename = f"eval_report_{int(time.time())}.pdf"
    filepath = os.path.join(os.path.dirname(__file__), filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)
    return {"status": "ok", "filename": filename}

import subprocess
@app.get("/models")
def get_models():
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')[1:] # Skip header
        models = [line.split()[0] for line in lines if line]
        return {"models": ["gemini-3.1-flash-lite-preview"] + models}
    except Exception as e:
        return {"models": ["gemini-3.1-flash-lite-preview"]}

# ═══════════════════════════════════════════════════════════════════════════════
#  UI HTML (intégrée dans le même fichier)
# ═══════════════════════════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>EvalSuite — Résumés MultiEURLEX</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#0d0f14;--ink2:#3a3f4e;--ink3:#7a8099;
  --bg:#f6f5f0;--surface:#fff;--surface2:#f0efe9;
  --accent:#d4410b;--accent2:#e85d28;
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
.fld input, .fld select{width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:6px;padding:9px 12px;font-family:var(--mono);font-size:12px;color:var(--ink);outline:none;transition:border-color .2s;}
.fld input:focus, .fld select:focus{border-color:var(--accent);}
.btn{background:var(--ink);color:#fff;font-family:var(--title);font-weight:700;font-size:14px;border:none;border-radius:8px;padding:12px 28px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:background .2s,transform .1s;}
.btn:hover{background:var(--accent);}
.btn:active{transform:scale(.98);}
.btn:disabled{opacity:.35;cursor:not-allowed;transform:none;}
.btn-o{background:transparent;color:var(--ink);border:1px solid var(--border2);border-radius:8px;padding:10px 20px;font-family:var(--title);font-weight:600;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:7px;transition:background .15s;}
.btn-o:hover{background:var(--surface2);}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:28px;}
/* terminal */
#term-wrap{display:none;margin-bottom:20px;}
.term-box{background:#0d0f14;border-radius:var(--r);padding:20px 24px;}
.prog-lbl{font-family:var(--mono);font-size:10px;color:#4a5a70;margin-bottom:8px;}
.prog-bar{height:3px;background:rgba(255,255,255,.07);border-radius:2px;margin-bottom:14px;}
.prog-fill{height:100%;background:var(--accent2);border-radius:2px;transition:width .5s ease;width:0;}
.term{max-height:240px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.75;color:#7a8fa8;}
.lok{color:#4fd68a;}.lerr{color:#f07070;}.linf{color:#7ab8f5;}.ldone{color:#f5c542;font-weight:500;}
#err-box{display:none;background:#fff5f5;border:1px solid #f5b5b5;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-family:var(--mono);font-size:12px;color:var(--red);}
/* results */
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
.mkey{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--ink3);width:84px;flex-shrink:0;}
.bwrap{flex:1;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden;}
.bfill{height:100%;border-radius:3px;transition:width 1s cubic-bezier(.4,0,.2,1);width:0%;}
.fa{background:var(--accent);}.fb{background:var(--ink2);}.fc{background:#8a8f9e;}
.mval{font-family:var(--mono);font-size:12px;font-weight:500;width:60px;text-align:right;}
.sub3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px;}
.sub3item{background:var(--surface2);border-radius:6px;padding:10px 12px;}
.sub3item .k{font-family:var(--mono);font-size:9px;color:var(--ink3);text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;}
.sub3item .v{font-family:var(--mono);font-size:11px;font-weight:500;}
.badge{font-family:var(--mono);font-size:10px;padding:2px 9px;border-radius:20px;margin-left:8px;font-weight:500;}
.bg{background:#e2f5ea;color:var(--green);}.ba{background:#fef3e0;color:var(--amber);}.bb{background:#fde8e8;color:var(--red);}
/* detail */
#det-section{display:none;margin-top:4px;}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;}
.chart-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px 22px;}
.chart-card .ct{font-size:13px;font-weight:700;margin-bottom:2px;}
.chart-card .cd{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-bottom:12px;}
.tbl{width:100%;border-collapse:collapse;font-size:12px;}
.tbl th{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--ink3);font-weight:500;text-align:left;padding:6px 10px 8px;border-bottom:1px solid var(--border);}
.tbl td{padding:8px 10px;border-bottom:1px solid var(--border);font-family:var(--mono);}
.tbl tr:last-child td{border-bottom:none;}
@media(max-width:600px){.grid2,.chart-grid{grid-template-columns:1fr;}}
@media print {
  nav, .hero, .actions, #term-wrap, #err-box, .btn, .card:not(#term-wrap), .sl:first-of-type { display: none !important; }
  body { background: #fff !important; color: #000 !important; }
  .page { padding: 0 !important; max-width: 100% !important; }
  .card, .mblock, .stat-box, .sub3item, .chart-card { break-inside: avoid; border: 1px solid #ddd !important; background: #fff !important; }
  .bfill { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .prog-bar, .prog-fill { display: none !important; }
}
</style>
</head>
<body>
<nav>
  <div class="nav-logo"><div class="dot"></div>EvalSuite</div>
  <div class="nav-sub">MultiEURLEX · ROUGE + BLEU + BERTScore + BLEURT + BARTScore</div>
</nav>
<div class="page">

  <div class="hero">
    <h1>Évaluation<br/><em>Agent Résumé</em></h1>
    <p>// MultiEURLEX FR &nbsp;·&nbsp; celex_id / text / labels &nbsp;·&nbsp; ROUGE-1/2/L · BLEU · BERTScore · BLEURT · BARTScore</p>
  </div>

  <div class="sl">Configuration</div>
  <div class="card">
    <div class="grid2">
      <div class="fld"><label>URL API résumé</label>
        <input id="cfg-api" value="http://127.0.0.1:8000/api/upload"/></div>
      <div class="fld"><label>Clé JSON du résumé</label>
        <input id="cfg-key" value="summary"/></div>
      <div class="fld"><label>Nombre de documents</label>
        <input id="cfg-n" type="number" value="150" min="1" max="9999"/></div>
      <div class="fld"><label>Split dataset</label>
        <input id="cfg-split" value="test"/></div>
      <div class="fld" style="grid-column: 1 / -1;"><label>Modèle (LLM)</label>
        <select id="cfg-model"></select></div>
    </div>
    <button class="btn" id="btn-run" onclick="startEval()">&#9654; Lancer l'évaluation</button>
  </div>

  <div id="term-wrap" style="display:none; margin-bottom:20px;">
    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 10px;">
      <div class="sl" style="margin-bottom: 0;">Progression en temps réel</div>
      <button class="btn-o" id="btn-cancel" onclick="cancelEval()" style="padding: 4px 10px; font-size: 10px; color: #f07070; border-color: #f07070;">🛑 Arrêter</button>
    </div>
    <div class="card term-box" style="background:#0d0f14;border-color:rgba(255,255,255,.06); margin-bottom:0;">
      <div class="prog-lbl" id="prog-lbl">0 / 0</div>
      <div class="prog-bar"><div class="prog-fill" id="prog-fill"></div></div>
      <div class="term" id="term"></div>
    </div>
  </div>

  <div id="err-box"></div>

  <div id="res-section">
    <div class="sl">Résultats moyens</div>
    <div class="stat-grid" id="stat-grid"></div>
    <div id="rouge-block" class="mblock"></div>
    <div id="bert-block"  class="mblock"></div>
    <div id="extra-block" class="mblock"></div>

    <div class="actions">
      <button class="btn-o" id="btn-det" onclick="toggleDetail()">&#9707; Statistiques détaillées</button>
      <button class="btn-o" onclick="exportJSON()">&#8675; Exporter JSON</button>
      <button class="btn-o" onclick="exportPDF()">&#128462; Exporter PDF</button>
    </div>

    <div id="det-section">
      <div class="sl">Distribution & statistiques</div>
      <div class="mblock" id="minmax-block"></div>
      <div class="chart-grid">
        <div class="chart-card"><div class="ct">ROUGE-1 F1</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-r1" role="img" aria-label="Histogramme ROUGE-1 F1">ROUGE-1 F1</canvas></div></div>
        <div class="chart-card"><div class="ct">ROUGE-2 F1</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-r2" role="img" aria-label="Histogramme ROUGE-2 F1">ROUGE-2 F1</canvas></div></div>
        <div class="chart-card"><div class="ct">ROUGE-L F1</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-rl" role="img" aria-label="Histogramme ROUGE-L F1">ROUGE-L F1</canvas></div></div>
        <div class="chart-card"><div class="ct">BLEU</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-bleu" role="img" aria-label="Histogramme BLEU">BLEU</canvas></div></div>
        <div class="chart-card"><div class="ct">BERTScore F1</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-bf" role="img" aria-label="Histogramme BERTScore F1">BERTScore F1</canvas></div></div>
        <div class="chart-card"><div class="ct">BLEURT</div><div class="cd">distribution sur les documents</div>
          <div style="position:relative;height:190px;"><canvas id="h-bleurt" role="img" aria-label="Histogramme BLEURT">BLEURT</canvas></div></div>
        <div class="chart-card"><div class="ct">BARTScore (norm.)</div><div class="cd">exp(log-vraisemblance moyenne/token)</div>
          <div style="position:relative;height:190px;"><canvas id="h-bart" role="img" aria-label="Histogramme BARTScore">BARTScore</canvas></div></div>
        <div class="chart-card"><div class="ct">Taux de compression</div><div class="cd">% mots résumé / mots document</div>
          <div style="position:relative;height:190px;"><canvas id="h-cp" role="img" aria-label="Histogramme compression">Compression</canvas></div></div>
        <div class="chart-card"><div class="ct">ROUGE-1 vs BERTScore</div><div class="cd">corrélation entre les deux métriques</div>
          <div style="position:relative;height:190px;"><canvas id="sc-rb" role="img" aria-label="Scatter ROUGE vs BERT">Scatter</canvas></div></div>
      </div>
    </div>
  </div>

</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
let _data = null, _detOpen = false, _charts = {};

window.addEventListener('DOMContentLoaded', async () => {
  try {
    const res = await fetch('/models');
    const data = await res.json();
    const sel = document.getElementById('cfg-model');
    data.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m; opt.textContent = m;
      sel.appendChild(opt);
    });
  } catch(e) {}
});

async function startEval(){
  const btn = document.getElementById('btn-run');
  btn.disabled = true;
  document.getElementById('err-box').style.display = 'none';
  document.getElementById('res-section').style.display = 'none';
  document.getElementById('term-wrap').style.display = 'block';
  document.getElementById('btn-cancel').style.display = 'inline-flex';
  document.getElementById('btn-cancel').disabled = false;
  document.getElementById('btn-cancel').textContent = '🛑 Arrêter';
  document.getElementById('term').innerHTML = '';
  document.getElementById('prog-fill').style.width = '0%';
  document.getElementById('prog-lbl').textContent = 'Démarrage…';

  const body = {
    api_url:     document.getElementById('cfg-api').value.trim(),
    summary_key: document.getElementById('cfg-key').value.trim(),
    n_samples:   parseInt(document.getElementById('cfg-n').value),
    split:       document.getElementById('cfg-split').value.trim(),
    model:       document.getElementById('cfg-model').value.trim(),
  };

  try {
    const r = await fetch('/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || 'HTTP ' + r.status);
    }
    listenSSE();
  } catch(e) {
    showErr(e.message);
    btn.disabled = false;
  }
}

async function cancelEval() {
  document.getElementById('btn-cancel').disabled = true;
  document.getElementById('btn-cancel').textContent = 'Arrêt en cours...';
  await fetch('/cancel', { method: 'POST' });
}

function showErr(msg){
  const b = document.getElementById('err-box');
  b.textContent = '⚠  ' + msg;
  b.style.display = 'block';
}

function listenSSE(){
  const es = new EventSource('/progress');
  const term = document.getElementById('term');
  const fill = document.getElementById('prog-fill');
  const lbl  = document.getElementById('prog-lbl');

  const formatTime = (s) => {
    if (!s || s < 0) return "--:--";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}m ${sec < 10 ? '0' : ''}${sec}s`;
  };

  es.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.error) { showErr(d.error); es.close(); document.getElementById('btn-run').disabled=false; return; }
    (d.log||[]).forEach(line => {
      const div = document.createElement('div');
      div.className = line.startsWith('✓') ? 'lok' : line.startsWith('✗')||line.startsWith('💥') ? 'lerr' : line.startsWith('🎉') ? 'ldone' : 'linf';
      div.textContent = line;
      term.appendChild(div);
    });
    term.scrollTop = term.scrollHeight;
    if (d.total > 0) {
      const pct = Math.round(d.progress / d.total * 100);
      fill.style.width = pct + '%';
      const etaStr = d.done ? '' : `  ·  ETA: ${formatTime(d.eta)}`;
      lbl.textContent  = d.progress + ' / ' + d.total + '  (' + pct + '%)' + etaStr;
    }
    if (d.done) { 
      document.getElementById('btn-cancel').style.display = 'none';
      es.close(); 
      fetchAndRender(); 
    }
  };
  es.onerror = () => es.close();
}

async function fetchAndRender(){
  const r = await fetch('/results');
  if (!r.ok) { showErr('Impossible de récupérer les résultats'); document.getElementById('btn-run').disabled=false; return; }
  _data = await r.json();
  render(_data);
  document.getElementById('btn-run').disabled = false;
  
  // Sauvegarde automatique du PDF après l'affichage des résultats
  setTimeout(() => exportPDF(), 1000);
}

const pct = v => (v*100).toFixed(1)+'%';
const badge = f1 => f1>=.5 ? '<span class="badge bg">Très bon</span>' : f1>=.3 ? '<span class="badge ba">Acceptable</span>' : '<span class="badge bb">À améliorer</span>';
const setBar = (id, v) => setTimeout(() => { const el=document.getElementById(id); if(el) el.style.width=(v*100).toFixed(1)+'%'; }, 120);

function render(data){
  const a = data.averages;
  const formatTime = (s) => {
    if (!s || s < 0) return "--:--";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}m ${sec < 10 ? '0' : ''}${sec}s`;
  };
  document.getElementById('stat-grid').innerHTML =
    box('Modèle', a.model || 'Inconnu', 'LLM utilisé') +
    box('Temps', a.total_time ? formatTime(a.total_time) : '--:--', 'Durée totale') +
    box('Docs traités', a.n_success, 'sur '+(a.n_success+a.n_error+a.n_skipped)) +
    box('Mots / doc',   (a.avg_doc_words||0).toLocaleString('fr'), 'mots en moyenne') +
    box('Mots / résumé',(a.avg_sum_words||0).toLocaleString('fr'), 'mots en moyenne') +
    box('Compression',  (a.avg_compression||0)+'%', 'résumé / document');

  const r = a.rouge;
  document.getElementById('rouge-block').innerHTML = `
    <div class="mhead">ROUGE ${badge(r.rouge1.f1)}</div>
    <div class="msub">// recouvrement lexical entre le résumé et le document source</div>
    <div class="mrow"><span class="mkey">ROUGE-1</span><div class="bwrap"><div class="bfill fa" id="br1"></div></div><span class="mval">${pct(r.rouge1.f1)}</span></div>
    <div class="mrow"><span class="mkey">ROUGE-2</span><div class="bwrap"><div class="bfill fa" id="br2"></div></div><span class="mval">${pct(r.rouge2.f1)}</span></div>
    <div class="mrow"><span class="mkey">ROUGE-L</span><div class="bwrap"><div class="bfill fa" id="brl"></div></div><span class="mval">${pct(r.rougeL.f1)}</span></div>
    <div class="sub3">${['rouge1','rouge2','rougeL'].map(k=>`
      <div class="sub3item"><div class="k">${k}</div>
      <div class="v">P&nbsp;${pct(r[k].precision)}&nbsp;&nbsp;R&nbsp;${pct(r[k].recall)}&nbsp;&nbsp;F1&nbsp;${pct(r[k].f1)}</div></div>`).join('')}
    </div>`;
  setBar('br1',r.rouge1.f1); setBar('br2',r.rouge2.f1); setBar('brl',r.rougeL.f1);

  const b = a.bert_score;
  if (b && b.f1 != null) {
    document.getElementById('bert-block').innerHTML = `
      <div class="mhead">BERTScore ${badge(b.f1)}</div>
      <div class="msub">// similarité sémantique via embeddings BERT (lang=fr)</div>
      <div class="mrow"><span class="mkey">Précision</span><div class="bwrap"><div class="bfill fb" id="bbp"></div></div><span class="mval">${pct(b.precision)}</span></div>
      <div class="mrow"><span class="mkey">Rappel</span>   <div class="bwrap"><div class="bfill fb" id="bbr"></div></div><span class="mval">${pct(b.recall)}</span></div>
      <div class="mrow"><span class="mkey">F1</span>       <div class="bwrap"><div class="bfill fb" id="bbf"></div></div><span class="mval">${pct(b.f1)}</span></div>`;
    setBar('bbp',b.precision); setBar('bbr',b.recall); setBar('bbf',b.f1);
  } else {
    document.getElementById('bert-block').innerHTML = '<div class="mhead">BERTScore</div><div class="msub">// non calculé (aucun document traité avec succès)</div>';
  }

  // ── Bloc métriques complémentaires : BLEU, BLEURT, BARTScore ────────────
  const bleu   = a.bleu;
  const bleurt = a.bleurt;
  const bart   = a.bart_score || {};
  let extraRows = '';

  if (bleu != null) {
    extraRows += `<div class="mrow"><span class="mkey">BLEU</span><div class="bwrap"><div class="bfill fc" id="ebleu"></div></div><span class="mval">${pct(bleu)}</span></div>`;
  }
  if (bleurt != null) {
    extraRows += `<div class="mrow"><span class="mkey">BLEURT</span><div class="bwrap"><div class="bfill fc" id="ebleurt"></div></div><span class="mval">${pct(bleurt)}</span></div>`;
  }
  if (bart.norm != null) {
    extraRows += `<div class="mrow"><span class="mkey">BARTScore</span><div class="bwrap"><div class="bfill fc" id="ebart"></div></div><span class="mval">${pct(bart.norm)}</span></div>`;
  }

  if (extraRows) {
    document.getElementById('extra-block').innerHTML = `
      <div class="mhead">Métriques complémentaires</div>
      <div class="msub">// BLEU (précision n-grammes) · BLEURT (modèle appris) · BARTScore (log-vraisemblance normalisée, modèle Barthez)</div>
      ${extraRows}
      ${bart.raw != null ? `<div class="sub3item" style="margin-top:14px;"><div class="k">bartscore raw</div><div class="v">${bart.raw}</div></div>` : ''}`;
    if (bleu   != null) setBar('ebleu',   bleu);
    if (bleurt != null) setBar('ebleurt', Math.max(0, Math.min(1, bleurt)));
    if (bart.norm != null) setBar('ebart', bart.norm);
  } else {
    document.getElementById('extra-block').innerHTML = '<div class="mhead">Métriques complémentaires</div><div class="msub">// BLEU/BLEURT/BARTScore non disponibles</div>';
  }

  document.getElementById('res-section').style.display = 'block';
  document.getElementById('det-section').style.display = 'none';
  _detOpen = false;
}

function box(label, val, sub){ 
  const svStyle = label === 'Modèle' ? ' style="font-size: 15px; letter-spacing: 0;"' : '';
  return `<div class="stat-box"><div class="sk">${label}</div><div class="sv"${svStyle}>${val}</div><div class="sd">${sub}</div></div>`; 
}

function toggleDetail(){
  if (!_data) return;
  _detOpen = !_detOpen;
  document.getElementById('det-section').style.display = _detOpen ? 'block' : 'none';
  document.getElementById('btn-det').textContent = _detOpen ? '▲ Masquer les détails' : '▼ Statistiques détaillées';
  if (_detOpen) renderDetail();
}

function calcStats(arr){
  if (!arr.length) return {min:0,max:0,mean:0,median:0,p25:0,p75:0};
  const s=[...arr].sort((a,b)=>a-b), n=s.length;
  return {
    min:   s[0],
    max:   s[n-1],
    mean:  s.reduce((a,b)=>a+b,0)/n,
    median:n%2===0 ? (s[n/2-1]+s[n/2])/2 : s[Math.floor(n/2)],
    p25:   s[Math.floor(n*.25)],
    p75:   s[Math.floor(n*.75)],
  };
}

function mkHisto(arr, bins=14){
  if (!arr.length) return {labels:[],counts:[]};
  const mn=Math.min(...arr), mx=Math.max(...arr), w=(mx-mn)/bins||1;
  const counts=Array(bins).fill(0);
  arr.forEach(v=>{ counts[Math.min(Math.floor((v-mn)/w),bins-1)]++; });
  return { labels: Array.from({length:bins},(_,i)=>((mn+i*w)*100).toFixed(0)+'%'), counts };
}

function mkChart(id, arr, label, color){
  if (_charts[id]) _charts[id].destroy();
  const {labels,counts} = mkHisto(arr);
  _charts[id] = new Chart(document.getElementById(id).getContext('2d'),{
    type:'bar',
    data:{labels,datasets:[{label,data:counts,backgroundColor:color+'bb',borderColor:color,borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{x:{ticks:{font:{size:9},maxRotation:45,autoSkip:false},grid:{display:false}},
              y:{ticks:{font:{size:9}},grid:{color:'rgba(0,0,0,.05)'}}}}
  });
}

function renderDetail(){
  const docs = _data.documents.filter(d=>d.status==='success');
  const r1=docs.map(d=>d.rouge.rouge1.f1);
  const r2=docs.map(d=>d.rouge.rouge2.f1);
  const rl=docs.map(d=>d.rouge.rougeL.f1);
  const bf=docs.map(d=>d.bert_score?.f1).filter(v=>v!=null);
  const cp=docs.map(d=>d.compression_pct/100);
  const bleu   = docs.map(d=>d.bleu).filter(v=>v!=null);
  const bleurt = docs.map(d=>d.bleurt).filter(v=>v!=null);
  const bart   = docs.map(d=>d.bart_score?.norm).filter(v=>v!=null);

  const metrics=[
    ['ROUGE-1 F1',r1],['ROUGE-2 F1',r2],['ROUGE-L F1',rl],
    ['BLEU',bleu],['BERTScore F1',bf],['BLEURT',bleurt],
    ['BARTScore (norm.)',bart],['Compression',cp],
  ];
  document.getElementById('minmax-block').innerHTML = `
    <div class="mhead">Statistiques descriptives</div>
    <div class="msub">// min · max · médiane · moyenne · P25 · P75 pour chaque métrique</div>
    <table class="tbl">
      <thead><tr><th>Métrique</th><th>Min</th><th>Max</th><th>Médiane</th><th>Moyenne</th><th>P25</th><th>P75</th></tr></thead>
      <tbody>${metrics.map(([name,arr])=>{
        const s=calcStats(arr);
        const f=v=>(v*100).toFixed(1)+'%';
        return `<tr><td>${name}</td><td>${f(s.min)}</td><td>${f(s.max)}</td><td>${f(s.median)}</td><td>${f(s.mean)}</td><td>${f(s.p25)}</td><td>${f(s.p75)}</td></tr>`;
      }).join('')}</tbody>
    </table>`;

  mkChart('h-r1',r1,'ROUGE-1 F1','#d4410b');
  mkChart('h-r2',r2,'ROUGE-2 F1','#d4410b');
  mkChart('h-rl',rl,'ROUGE-L F1','#d4410b');
  mkChart('h-bleu',bleu,'BLEU','#8a8f9e');
  mkChart('h-bf',bf,'BERTScore F1','#3a3f4e');
  mkChart('h-bleurt',bleurt,'BLEURT','#8a8f9e');
  mkChart('h-bart',bart,'BARTScore (norm.)','#8a8f9e');
  mkChart('h-cp',cp,'Compression','#3a3f4e');

  if (_charts['sc-rb']) _charts['sc-rb'].destroy();
  const paired = docs.filter(d=>d.bert_score!=null).map(d=>({x:d.rouge.rouge1.f1,y:d.bert_score.f1}));
  _charts['sc-rb'] = new Chart(document.getElementById('sc-rb').getContext('2d'),{
    type:'scatter',
    data:{datasets:[{label:'Documents',data:paired,backgroundColor:'#d4410b88',pointRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{x:{title:{display:true,text:'ROUGE-1 F1',font:{size:10}},ticks:{font:{size:9}}},
              y:{title:{display:true,text:'BERTScore F1',font:{size:10}},ticks:{font:{size:9}}}}}
  });
}

function exportJSON(){
  if(!_data) return;
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(_data,null,2)],{type:'application/json'}));
  a.download='eval_results_'+new Date().toISOString().slice(0,10)+'.json';
  a.click();
}

async function exportPDF(){
  if(!_detOpen) toggleDetail();
  
  await new Promise(r => setTimeout(r, 500));
  
  const actions = document.querySelector('.actions');
  const nav = document.querySelector('nav');
  const hero = document.querySelector('.hero');
  
  actions.style.display = 'none';
  nav.style.display = 'none';
  hero.style.display = 'none';

  const element = document.body;
  const opt = {
    margin:       10,
    filename:     'eval_results.pdf',
    image:        { type: 'jpeg', quality: 0.98 },
    html2canvas:  { scale: 2 },
    jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
  };
  
  try {
    const pdfBlob = await html2pdf().set(opt).from(element).output('blob');
    
    actions.style.display = 'flex';
    nav.style.display = 'flex';
    hero.style.display = 'block';

    const res = await fetch('/save_pdf', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/pdf'},
        body: pdfBlob 
    });
    if(res.ok) {
       console.log('PDF sauvegardé automatiquement sur le serveur.');
    } else {
       showErr('Erreur lors de la sauvegarde du PDF sur le serveur.');
    }
  } catch(e) {
    actions.style.display = 'flex';
    nav.style.display = 'flex';
    hero.style.display = 'block';
    showErr('Erreur html2pdf: ' + e);
  }
}
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def route_index():
    return HTML

# ═══════════════════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run("eval_server:app", host="0.0.0.0", port=EVAL_PORT, reload=False)