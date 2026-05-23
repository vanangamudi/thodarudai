#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os, time, logging, math, random, json
import arichuvadi as ari
from tools.profile import Profile
from tools.storage.file import FileStorage
from tools.curation_index import CuratedIndexDB
import re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("webui")

def render_results_html(results):
    html = []
    html.append("<table border='1'>")
    html.append("<tr><th>Word</th><th>Freq</th><th>Glen</th></tr>")
    for rec in results:
        html.append(f"<tr><td>{rec[0]}</td><td>{rec[1]}</td><td>{rec[2]}</td></tr>")
    html.append("</table>")
    return "\n".join(html)
STARTUP_TS = int(time.time())
BUILD_TAG = time.strftime("%Y%m%dT%H%M%S", time.localtime(STARTUP_TS))
from fastapi.concurrency import run_in_threadpool
from tools.word_indexer import WordIndex
from tools.curation_index import CuratedIndex
from tools.curation_core import (
    normalize_query_fields, run_query,
    parse_length_spec, compile_neg_regex,
    filter_eligible as core_filter_eligible,
    partition_new_old as core_partition_new_old,
    mix_curated as core_mix_curated,
    default_batch_name,
    build_tsv_lines as core_build_tsv_lines,
    compute_summary_data as core_compute_summary_data,
)
# (This entire duplicate import block has been removed.)

PROFILE_NAME = os.environ.get("PROFILE", "default")
BASE_DIR = os.environ.get("BASE_DIR", None)
PROF = Profile(name=PROFILE_NAME, base_dir=BASE_DIR)
WORDLIST_PATH = os.path.abspath(PROF.wordlist_path)
BATCHES_DIR = os.path.abspath(PROF.batches_dir)
LEDGER_PATH = os.path.abspath(PROF.ledger_path)
REMINDERS_PATH = os.path.abspath(PROF.reminders_path)
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "fs")  # 'fs' or 'sqlite'
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.abspath("data/curation.db"))
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
# Unified storage abstraction: instantiate the storage backend below based on STORAGE_BACKEND
STORAGE = None

# Global singleton storage (simple, single user)
WORD_INDEX = None
CURATED = None

def _init_word_index(wordlist_path):
    from tools.word_indexer import WordIndex
    return WordIndex(wordlist_path)

def _init_storage_and_curated():
    sb = STORAGE_BACKEND.lower()
    if sb == "sqlite":
        from tools.storage.sqlite import SqliteStorage
        storage = SqliteStorage(SQLITE_PATH, profile=PROFILE_NAME)
        curated = CuratedIndexDB(storage)
    elif sb == "postgres":
        if not POSTGRES_DSN:
            raise RuntimeError("POSTGRES_DSN is required when STORAGE_BACKEND=postgres")
        from tools.storage.postgres import PostgresStorage
        storage = PostgresStorage(POSTGRES_DSN, profile=PROFILE_NAME)
        curated = CuratedIndexDB(storage)
    else:
        storage = FileStorage(BATCHES_DIR, LEDGER_PATH, REMINDERS_PATH)
        curated = CuratedIndex(BATCHES_DIR)
    return storage, curated

def _seed_db_words_if_empty(storage, wordlist_path):
    sb = STORAGE_BACKEND.lower()
    if sb not in ("sqlite", "postgres"):
        return
    try:
        if not storage.has_words() and os.path.exists(wordlist_path):
            recs = []
            with open(wordlist_path, "r", encoding="utf-8") as f:
                hdr = f.readline().strip().split("\t")
                idx = {h: i for i, h in enumerate(hdr)}
                for ln in f:
                    if not ln.strip():
                        continue
                    c = ln.rstrip("\n").split("\t")
                    recs.append((c[idx["word"]], int(c[idx["freq"]]), int(c[idx["glen"]])))
            storage.ensure_words(recs)
    except Exception as e:
        logger.warning("Seeding DB words failed: %s", e)

def initialize_services():
    global WORD_INDEX, CURATED, STORAGE
    WORD_INDEX = _init_word_index(WORDLIST_PATH)
    STORAGE, CURATED = _init_storage_and_curated()
    CURATED.reload()
    _seed_db_words_if_empty(STORAGE, WORDLIST_PATH)
    logging.info("Initialized WORD_INDEX (%d words), CURATED (%d), storage=%s", len(WORD_INDEX.words), CURATED.curated_count, STORAGE_BACKEND)
def _build_tsv_min(rows):
    return core_build_tsv_lines(rows)

def _parse_split_for_commit(word, splits):
    if "-" not in (splits or ""): return None
    left, right = [x.strip() for x in splits.split("-", 1)]
    if not left or not right: return None
    try: sp = int(ari.length(left))
    except Exception: sp = max(1, len(left))
    return left, right, sp

def _db_do_query(fields, min_len, max_len):
    t0 = time.perf_counter()
    rows = STORAGE.query_index(prefix=fields["prefix"], suffix=fields["suffix"], regex=fields["regex"],
        prefix_not=fields["prefix_not"], suffix_not=fields["suffix_not"], regex_not=fields["regex_not"],
        min_len=min_len, max_len=max_len, limit=fields["limit"], curated_ratio=fields["curated_ratio"])
    dur = int((time.perf_counter() - t0) * 1000)
    logger.info("QUERY_DB returned=%d dur_ms=%d", len(rows), dur)
    return rows, dur

def _fs_do_query(fields, min_len, max_len):
    t0 = time.perf_counter()
    probe = min(fields["limit"] * 5, max(fields["limit"] + 500, 5000))
    raw = WORD_INDEX.query_words(prefix=fields["prefix"], suffix=fields["suffix"],
                                 min_len=min_len, max_len=max_len,
                                 limit=probe, offset=0, regex=fields["regex"])
    neg_rx = compile_neg_regex(fields["regex_not"])
    eligible = core_filter_eligible(raw, fields["prefix_not"], fields["suffix_not"], neg_rx)
    new_rows, old_rows = core_partition_new_old(eligible, CURATED)
    combined = core_mix_curated(new_rows, old_rows, fields["limit"], fields["curated_ratio"])
    dur = int((time.perf_counter() - t0) * 1000)
    logger.info("QUERY_FS raw=%d eligible=%d new=%d curated=%d returned=%d dur_ms=%d", len(raw), len(eligible), len(new_rows), len(old_rows), len(combined), dur); return combined, dur


def _render_query_result(request, rows, dur_ms):
    acc = (request.headers.get("accept","").lower())
    if "text/html" in acc:
        return HTMLResponse(content=render_results_html(rows))
    return {"results": rows, "elapsed_ms": dur_ms}

def _commit_db_rows(rows, batch_name, tsv_lines):
    saved = 0
    for rec in rows:
        rec_id, word, splits, freq, glen, notes = (rec + ["", "", "", ""])[:6]
        ps = _parse_split_for_commit(word, splits)
        if not ps: continue
        lt, rt, sp = ps; STORAGE.add_segmentation(word, lt, rt, sp, notes or ""); saved += 1
    return f"{STORAGE_BACKEND}://segmentations#{batch_name}", f"{STORAGE_BACKEND}://ledger#{batch_name}", saved

def _commit_fs_rows(rows, batch_name, tsv_lines):
    bp = STORAGE.write_batch(rows, batch_name)
    lp = STORAGE.append_ledger(tsv_lines, batch_name)
    return bp, lp

def _update_curated_after_commit(tsv_lines):
    if hasattr(CURATED, "update_from_batch"): CURATED.update_from_batch(tsv_lines)
    else: CURATED.maybe_reload_on_change()

app = FastAPI(title="Tamil Splits Web UI")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # Adjust according to your front-end URL in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    await run_in_threadpool(initialize_services)
    logging.info("Startup complete – services initialized")
    logger.info("Backend build_tag=%s app_file=%s mtime=%s",
                BUILD_TAG, __file__, int(os.path.getmtime(__file__)))

# Optional: mount a static directory if you need to serve assets, e.g. CSS/JS.
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    method = request.method
    path = request.url.path
    query = request.url.query
    origin = request.headers.get("origin", "-")
    ctype = request.headers.get("content-type", "-")
    clen = request.headers.get("content-length", "-")
    logger.info("REQ %s %s%s origin=%s ctype=%s clen=%s",
                method, path, f"?{query}" if query else "", origin, ctype, clen)
    try:
        response = await call_next(request)
        status = getattr(response, "status_code", 0)
        dur_ms = int((time.perf_counter() - start) * 1000)
        logger.info("RES %s %s status=%s dur_ms=%d", method, path, status, dur_ms)
        return response
    except Exception as e:
        dur_ms = int((time.perf_counter() - start) * 1000)
        logger.exception("ERR %s %s dur_ms=%d: %s", method, path, dur_ms, e)
        raise

@app.get("/", response_class=HTMLResponse)
def get_ui():
    html_content = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Tamil Splits Web UI</title>
      </head>
      <body>
        <h1>Welcome to Tamil Splits Web UI</h1>
        <form action="/api/query" method="post">
          <label for="prefix">Prefix:</label>
          <input type="text" id="prefix" name="prefix" value=""><br>
          <label for="suffix">Suffix:</label>
          <input type="text" id="suffix" name="suffix" value=""><br>
          <label for="regex">Regex:</label>
          <input type="text" id="regex" name="regex" value=""><br>
          <label for="length_spec">Length Spec:</label>
          <input type="text" id="length_spec" name="length_spec" value="8-"><br>
          <label for="limit">Limit:</label>
          <input type="number" id="limit" name="limit" value="1000"><br>
          <input type="submit" value="Query">
        </form>
      </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/reminders")
def get_reminders():
    logger.info("REMINDERS get")
    try:
        return {"words": sorted(STORAGE.load_reminders())}
    except Exception as e:
        logging.exception("Error in reminders get")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/commit")
def api_commit(edited_rows: str = Form(...), batch: str = Form(None)):
    try:
        rows = json.loads(edited_rows) or []
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="edited_rows must be a JSON list")
        # Build TSV lines for ledger append and curated fast-path update
        tsv_lines = _build_tsv_min(rows)
        batch_name = batch or default_batch_name("", "", "8-")
        # For now, always go through storage’s write_batch + append_ledger (works for fs/sqlite/postgres)
        batch_path = STORAGE.write_batch(rows, batch_name)
        ledger_path = STORAGE.append_ledger(tsv_lines, batch_name)
        _update_curated_after_commit(tsv_lines)
        return {"status": "ok", "rows": len(rows), "batch": batch_name, "batch_path": batch_path, "ledger_path": ledger_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/commit")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Body
@app.post("/api/reminders")
def update_reminders(action: str = Form(...), words_json: str = Form("[]")):
    logger.info("REMINDERS update action=%s", action)
    import json
    try:
        words = set(json.loads(words_json) or [])
        current = STORAGE.load_reminders()
        if action == "add":
            current |= words
        elif action == "remove":
            current -= words
        else:
            raise HTTPException(status_code=400, detail="invalid action")
        STORAGE.write_reminders(current)
        return {"status": "ok", "count": len(current)}
    except Exception as e:
        logging.exception("Error in reminders update")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/results")
def get_reminder_results():
    logger.info("REMINDERS results")
    try:
        rem = STORAGE.load_reminders()
        words_map = {w: (w, fr, gl) for (w, fr, gl) in WORD_INDEX.words}
        results = [words_map[w] for w in sorted(rem) if w in words_map]
        return {"results": results}
    except Exception as e:
        logging.exception("Error in reminders results")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate_batch_name")
def api_generate_batch_name(prefix: str = Form(""), suffix: str = Form(""), length_spec: str = Form("8-")):
    try:
        return {"batch": default_batch_name(prefix, suffix, length_spec)}
    except Exception as e:
        logging.exception("Error generating batch name")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/query")
def api_query(
    request: Request,
    prefix: str = Form(""),
    suffix: str = Form(""),
    regex: str = Form(""),
    prefix_not: str = Form(""),
    suffix_not: str = Form(""),
    regex_not: str = Form(""),
    length_spec: str = Form("8-"),
    limit: int = Form(1000),
    curated_ratio: int = Form(20),
):
    try:
        fields = normalize_query_fields(prefix, suffix, regex, prefix_not, suffix_not, regex_not, length_spec, limit, curated_ratio)
        min_len, max_len = parse_length_spec(fields["length_spec"])
        if STORAGE_BACKEND.lower() == "sqlite":
            rows, dur_ms = _db_do_query(fields, min_len, max_len)
        else:
            rows, dur_ms = _fs_do_query(fields, min_len, max_len)
        return _render_query_result(request, rows, dur_ms)
    except Exception as e:
        logger.exception("Error in /api/query")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def health():
    try:
        return {
            "status": "ok",
            "build_tag": BUILD_TAG,
            "app_file": __file__,
            "app_mtime": int(os.path.getmtime(__file__)),
            "wordlist_path": WORDLIST_PATH,
            "word_count": len(WORD_INDEX.words) if WORD_INDEX else 0,
            "curated_count": int(getattr(CURATED, "curated_count", 0) or 0),
            "startup_ts": STARTUP_TS,
            "now": int(time.time()),
            "storage_backend": STORAGE_BACKEND,
            "storage_path": (
                SQLITE_PATH if STORAGE_BACKEND.lower() == "sqlite"
                else ({"dsn": POSTGRES_DSN.replace("://", "://***:***@") if "://" in POSTGRES_DSN else POSTGRES_DSN.replace("password=", "password=***")} if STORAGE_BACKEND.lower() == "postgres"
                      else {"batches": BATCHES_DIR, "ledger": LEDGER_PATH, "reminders": REMINDERS_PATH})
            ),
            "profile": PROFILE_NAME,
            "base_dir": PROF.base_dir,
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/summary")
def get_summary():
    try:
        if hasattr(STORAGE, "summary"):
            return STORAGE.summary()
        return core_compute_summary_data(WORD_INDEX, CURATED)
    except Exception as e:
        logging.exception("Error in summary endpoint")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
