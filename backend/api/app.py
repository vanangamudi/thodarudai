#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os, time, logging, math, random, json
import arichuvadi as ari
from backend.core.profile import Profile
from backend.storage.file import FileStorage
from backend.core.curation_index import CuratedIndexDB
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
from backend.indexing.word_indexer import WordIndex
from backend.core.curation_index import CuratedIndex
from backend.core.curation_core import (
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
RAW_STORAGE = os.environ.get("STORAGE_BACKEND", "auto")
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.abspath("data/curation.db"))
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "")
DISABLE_FS = os.environ.get("DISABLE_FS_BACKEND", "0") == "1"

def _auto_backend():
    if POSTGRES_DSN:
        return "postgres"
    if os.path.exists(SQLITE_PATH):
        return "sqlite"
    return "fs"

STORAGE_BACKEND = (RAW_STORAGE.lower() if RAW_STORAGE else "auto")
if STORAGE_BACKEND == "auto":
    STORAGE_BACKEND = _auto_backend()
# Enforce mutual exclusivity and prefer DB when DSN is provided
if POSTGRES_DSN and STORAGE_BACKEND == "fs":
    logger.info("POSTGRES_DSN provided; overriding FS with postgres backend")
    STORAGE_BACKEND = "postgres"
if DISABLE_FS and STORAGE_BACKEND == "fs":
    raise RuntimeError("FS backend disabled (DISABLE_FS_BACKEND=1). Set STORAGE_BACKEND=postgres with POSTGRES_DSN or use sqlite.")
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "8000"))
APP_RELOAD = os.environ.get("APP_RELOAD", "0") == "1"
# Unified storage abstraction: instantiate the storage backend below based on STORAGE_BACKEND
STORAGE = None

# Global singleton storage (simple, single user)
WORD_INDEX = None
CURATED = None

def _init_word_index(wordlist_path):
    from backend.indexing.word_indexer import WordIndex
    return WordIndex(wordlist_path)

def _ensure_fs_index_loaded():
    global WORD_INDEX
    if WORD_INDEX is None:
        logger.info("Loading FS WordIndex on demand…")
        WORD_INDEX = _init_word_index(WORDLIST_PATH)
    logging.info("Loaded FS WordIndex: %d words", len(WORD_INDEX.words))

def _init_storage_and_curated():
    sb = STORAGE_BACKEND.lower()
    if sb == "sqlite":
        from backend.storage.sqlite import SqliteStorage
        storage = SqliteStorage(SQLITE_PATH, profile=PROFILE_NAME)
        curated = CuratedIndexDB(storage)
    elif sb == "postgres":
        if not POSTGRES_DSN:
            raise RuntimeError("POSTGRES_DSN is required when STORAGE_BACKEND=postgres")
        from backend.storage.postgres import PostgresStorage
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
            CHUNK = 200000
            buf = []
            from backend.core.common import iter_word_freq_glen_from_tsv
            for w, fr, gl in iter_word_freq_glen_from_tsv(wordlist_path):
                buf.append((w, fr, gl))
                if len(buf) >= CHUNK:
                    storage.ensure_words(buf)
                    buf = []
            if buf:
                storage.ensure_words(buf)
    except Exception as e:
        logger.warning("Seeding DB words failed: %s", e)

def initialize_services():
    global WORD_INDEX, CURATED, STORAGE
    STORAGE, CURATED = _init_storage_and_curated()
    try:
        CURATED.refresh()
    except Exception:
        pass
    if STORAGE_BACKEND.lower() in ("sqlite", "postgres"):
        WORD_INDEX = None
        _seed_db_words_if_empty(STORAGE, WORDLIST_PATH)
        try:
            words_count = int(STORAGE.summary().get("total_words", 0)) if hasattr(STORAGE, "summary") else 0
        except Exception:
            words_count = 0
    else:
        WORD_INDEX = None  # lazy-load on first FS query
        words_count = 0

def _build_tsv_min(rows):
    return core_build_tsv_lines(rows)

def _parse_split_for_commit(word, splits):
    if not splits:
        return None
    # Accept ASCII hyphen and common Unicode dashes (‐‑‒–—, and minus sign)
    parts = re.split(r"\s*[-\u2010-\u2015\u2212]\s*", splits, maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = [x.strip() for x in parts]
    if not left or not right:
        return None
    try:
        sp = int(ari.length(left))
    except Exception:
        sp = max(1, len(left))
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
    _ensure_fs_index_loaded()
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
    # Build valid segmentation tuples
    items = []
    for rec in rows:
        rec_id, word, splits, freq, glen, notes = (rec + ["", "", "", ""])[:6]
        ps = _parse_split_for_commit(word, splits)
        if not ps:
            continue
        lt, rt, sp = ps
        items.append((word, lt, rt, sp, notes or ""))
    saved = 0
    if hasattr(STORAGE, "commit_segmentations"):
        try:
            saved = STORAGE.commit_segmentations(items, batch_name)
        except Exception as e:
            logger.warning("commit_segmentations failed, falling back to per-row: %s", e)
    if saved == 0 and items:
        for (word, lt, rt, sp, notes) in items:
            STORAGE.add_segmentation(word, lt, rt, sp, notes)
        saved = len(items)
    return f"{STORAGE_BACKEND}://segmentations#{batch_name}", f"{STORAGE_BACKEND}://ledger#{batch_name}", saved

def _commit_fs_rows(rows, batch_name, tsv_lines):
    bp = STORAGE.write_batch(rows, batch_name)
    lp = STORAGE.append_ledger(tsv_lines, batch_name)
    return bp, lp

def _update_curated_after_commit(tsv_lines):
    if hasattr(CURATED, "update_from_batch"):
        CURATED.update_from_batch(tsv_lines)
    else:
        CURATED.refresh()

app = FastAPI(title="Tamil Splits Web UI")
from fastapi.middleware.cors import CORSMiddleware

ALLOW_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOW_ORIGINS if o.strip()],
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
        import json
        rows = json.loads(edited_rows) or []
        logger.info("API /api/commit rows=%d batch=%s", len(rows), batch or "(auto)")
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="edited_rows must be a JSON list")
        tsv_lines = _build_tsv_min(rows)
        batch_name = batch or default_batch_name("", "", "8-")
        if STORAGE_BACKEND.lower() in ("sqlite", "postgres"):
            # DB mode: write to segmentations table, and append a ledger event
            batch_path, _lp_placeholder, saved = _commit_db_rows(rows, batch_name, tsv_lines)
            try:
                ledger_path = STORAGE.append_ledger(tsv_lines, batch_name)
            except Exception as e:
                logger.warning("API /api/commit: DB append_ledger failed: %s", e)
                ledger_path = f"{STORAGE_BACKEND}://ledger#{batch_name}"
            if saved == 0:
                logger.info("API /api/commit: no segmentations saved (likely no '-' in splits)")
            _update_curated_after_commit(tsv_lines)
            logger.info("API /api/commit handled_by=db rows=%d batch=%s", saved, batch_name)
            return {
                "status": "ok",
                "rows": saved,
                "batch": batch_name,
                "batch_path": batch_path,
                "ledger_path": ledger_path
            }
        # FS mode: write TSV batch + append ledger file
        batch_path = STORAGE.write_batch(rows, batch_name)
        ledger_path = STORAGE.append_ledger(tsv_lines, batch_name)
        _update_curated_after_commit(tsv_lines)
        logger.info("API /api/commit handled_by=fs rows=%d batch=%s batch_path=%s ledger_path=%s",
                    len(rows), batch_name, batch_path, ledger_path)
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
        if not rem:
            return {"results": []}
        if STORAGE_BACKEND.lower() in ("sqlite", "postgres") and hasattr(STORAGE, "_conn"):
            words = sorted(rem)
            with STORAGE._conn() as cx:
                if STORAGE_BACKEND.lower() == "sqlite":
                    q = f"SELECT word, freq, glen FROM words WHERE word IN ({','.join(['?']*len(words))})"
                    rows = cx.execute(q, words).fetchall()
                else:
                    with cx.cursor() as cur:
                        q = f"SELECT word, freq, glen FROM words WHERE word IN ({','.join(['%s']*len(words))})"
                        cur.execute(q, tuple(words))
                        rows = cur.fetchall()
            results = [(w, int(fr), int(gl)) for (w, fr, gl) in rows]
            return {"results": results}
        # FS/list fallback
        words_map = {w: (w, fr, gl) for (w, fr, gl) in (WORD_INDEX.words if WORD_INDEX else [])}
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
        import json
        fields = normalize_query_fields(prefix, suffix, regex, prefix_not, suffix_not, regex_not, length_spec, limit, curated_ratio)
        logger.info("API /api/query fields=%s", json.dumps(fields, ensure_ascii=False))
        min_len, max_len = parse_length_spec(fields["length_spec"])
        if hasattr(STORAGE, "query_index"):
            rows, dur_ms = _db_do_query(fields, min_len, max_len)
            logger.info("API /api/query handled_by=db returned=%d dur_ms=%d", len(rows), dur_ms)
        else:
            rows, dur_ms = _fs_do_query(fields, min_len, max_len)
            logger.info("API /api/query handled_by=fs returned=%d dur_ms=%d", len(rows), dur_ms)
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
            "word_count": (
                len(WORD_INDEX.words) if WORD_INDEX
                else (int(STORAGE.summary().get("total_words", 0)) if hasattr(STORAGE, "summary") else 0)
            ),
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
        logger.info("API /api/summary requested")
        if hasattr(STORAGE, "summary"):
            s = STORAGE.summary()
            logger.info("API /api/summary handled_by=storage")
            return s
        logger.info("API /api/summary handled_by=fs")
        return core_compute_summary_data(WORD_INDEX, CURATED)
    except Exception as e:
        logger.exception("Error in summary endpoint")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, reload=APP_RELOAD)
