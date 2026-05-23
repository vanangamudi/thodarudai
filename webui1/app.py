#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os, time, logging, math, random, json
from tools.storage import FileStorage, SqliteStorage
from tools.curation_index import CuratedIndexDB
import re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("webui")
STARTUP_TS = int(time.time())
BUILD_TAG = time.strftime("%Y%m%dT%H%M%S", time.localtime(STARTUP_TS))
from fastapi.concurrency import run_in_threadpool
from tools.word_indexer import WordIndex
from tools.curation_index import CuratedIndex
from tools.curation_core import (
    normalize_query_fields, run_query,
    parse_length_spec, compile_neg_regex,  # kept if you still use them elsewhere
    filter_eligible as core_filter_eligible,
    partition_new_old as core_partition_new_old,
    mix_curated as core_mix_curated,
    sanitize_component, default_batch_name,
    build_tsv_lines as core_build_tsv_lines,
    write_batch_file as core_write_batch_file,
    append_ledger as core_append_ledger,
    load_reminders as core_load_reminders,
    write_reminders as core_write_reminders,
    compute_summary_data as core_compute_summary_data,
)
# (This entire duplicate import block has been removed.)

# Configuration constants (reuse file paths from existing code)
WORDLIST_PATH = os.path.abspath("data/word-index.tsv")
BATCHES_DIR = os.path.abspath("data/batches")
LEDGER_PATH = os.path.abspath("data/splits-ledger.tsv")
REMINDERS_PATH = os.path.abspath("data/reminders.tsv")
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "fs")  # 'fs' or 'sqlite'
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.abspath("data/curation.db"))
# Unified storage abstraction: instantiate the storage backend below based on STORAGE_BACKEND
STORAGE = None

# Global singleton storage (simple, single user)
WORD_INDEX = None
CURATED = None

def initialize_services():
    global WORD_INDEX, CURATED, STORAGE
    WORD_INDEX = WordIndex(WORDLIST_PATH)
    if STORAGE_BACKEND.lower() == "sqlite":
        STORAGE = SqliteStorage(SQLITE_PATH)
        CURATED = CuratedIndexDB(STORAGE)
    else:
        STORAGE = FileStorage(BATCHES_DIR, LEDGER_PATH, REMINDERS_PATH)
        CURATED = CuratedIndex(BATCHES_DIR)
    CURATED.reload()
    logging.info("Initialized WORD_INDEX (%d words), CURATED (%d), storage=%s",
                 len(WORD_INDEX.words), CURATED.curated_count, STORAGE_BACKEND)
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
            "storage_path": SQLITE_PATH if STORAGE_BACKEND.lower() == "sqlite" else {"batches": BATCHES_DIR, "ledger": LEDGER_PATH, "reminders": REMINDERS_PATH},
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/query")
def query_words(request: Request,
                prefix: str = Form(""), suffix: str = Form(""),
                regex: str = Form(""), length_spec: str = Form("8-"),
                limit: int = Form(1000),
                prefix_not: str = Form(""), suffix_not: str = Form(""),
                regex_not: str = Form(""), curated_ratio: int = Form(20)):
    try:
        fields = normalize_query_fields(prefix, suffix, regex,
                                        prefix_not, suffix_not, regex_not,
                                        length_spec, limit, curated_ratio)
        t0 = time.perf_counter()
        logger.info("QUERY %s", {k: fields[k] for k in ("prefix","suffix","regex","length_spec","limit","curated_ratio","prefix_not","suffix_not","regex_not")})
        min_len, max_len = parse_length_spec(fields["length_spec"])
        probe_limit = min(fields["limit"] * 5, max(fields["limit"] + 500, 5000))
        raw = WORD_INDEX.query_words(prefix=fields["prefix"], suffix=fields["suffix"],
                                 min_len=min_len, max_len=max_len,
                                 limit=probe_limit, offset=0, regex=fields["regex"])
        neg_rx = compile_neg_regex(fields["regex_not"])
        eligible = core_filter_eligible(raw, fields["prefix_not"], fields["suffix_not"], neg_rx)
        new_rows, old_rows = core_partition_new_old(eligible, CURATED)
        combined = core_mix_curated(new_rows, old_rows, fields["limit"], fields["curated_ratio"])
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("QUERY_STATS raw=%d eligible=%d new=%d curated=%d returned=%d dur_ms=%d",
                    len(raw), len(eligible), len(new_rows), len(old_rows), len(combined), dur_ms)
        if "text/html" in (request.headers.get("accept","").lower()):
            return HTMLResponse(content=render_results_html(combined))
        return {"results": combined, "elapsed_ms": dur_ms}
    except Exception as e:
        logging.exception("Error in query")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/commit")
def commit_edits(edited_rows: str = Form(...), batch: str = Form("")):
    try:
        rows = json.loads(edited_rows) or []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid edited_rows: {e}")
    try:
        batch_name = batch if batch else f"{time.strftime('%Y%m%dT%H%M%S')}-batch.tsv"
        tsv_lines = core_build_tsv_lines(rows)
        batch_path = STORAGE.write_batch(rows, batch_name)
        ledger_abs = STORAGE.append_ledger(tsv_lines, batch_name)
        if hasattr(CURATED, "update_from_batch"):
            CURATED.update_from_batch(tsv_lines)
        else:
            CURATED.maybe_reload_on_change()
        logger.info("COMMIT done rows=%d batch=%s wrote_batch=%s wrote_ledger=%s",
                    len(rows), batch_name, batch_path, ledger_abs)
        return {"status": "committed",
                "batch": batch_name,
                "batch_path": batch_path,
                "ledger_path": ledger_abs,
                "rows": len(rows)}
    except Exception as e:
        logging.exception("Error in commit")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/summary")
def get_summary():
    try:
        return core_compute_summary_data(WORD_INDEX, CURATED)
    except Exception as e:
        logging.exception("Error in summary endpoint")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
