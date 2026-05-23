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


def sanitize_component(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', s).strip('_')[:64]

def default_batch_name(prefix: str, suffix: str, length_spec: str) -> str:
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    return f"{ts}-{sanitize_component(prefix)}-{sanitize_component(length_spec)}-{sanitize_component(suffix)}.tsv"

def load_reminders() -> set:
    rem = set()
    try:
        with open(REMINDERS_PATH, "r", encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            idx = {h: i for i, h in enumerate(header)}
            if "word" not in idx:
                return rem
            for ln in f:
                if not ln.strip(): continue
                cols = ln.rstrip("\n").split("\t")
                w = cols[idx["word"]]
                if w:
                    rem.add(w)
    except FileNotFoundError:
        pass
    return rem

def write_reminders(words: set):
    import fcntl
    os.makedirs(os.path.dirname(REMINDERS_PATH), exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    with open(REMINDERS_PATH, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write("timestamp\tword\tnotes\n")
            for w in sorted(words):
                f.write(f"{ts}\t{w}\t\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

from typing import List, Tuple, Optional, Dict, Any

def normalize_query_fields(prefix: str, suffix: str, regex: str,
                           prefix_not: str, suffix_not: str, regex_not: str,
                           length_spec: str, limit: int, curated_ratio: int) -> Dict[str, Any]:
    return {
        "prefix": (prefix or "").strip(),
        "suffix": (suffix or "").strip(),
        "regex": (regex or "").strip(),
        "prefix_not": (prefix_not or "").strip(),
        "suffix_not": (suffix_not or "").strip(),
        "regex_not": (regex_not or "").strip(),
        "length_spec": (length_spec or "").strip() or "8-",
        "limit": int(limit),
        "curated_ratio": max(0, min(int(curated_ratio), 100)),
    }

def run_index_query(fields: Dict[str, Any]) -> Tuple[List[Tuple], int, int, Optional[re.Pattern]]:
    min_len, max_len = parse_length_spec(fields["length_spec"])
    probe_limit = min(fields["limit"] * 5, max(fields["limit"] + 500, 5000))
    raw = WORD_INDEX.query_words(prefix=fields["prefix"], suffix=fields["suffix"],
                                 min_len=min_len, max_len=max_len,
                                 limit=probe_limit, offset=0, regex=fields["regex"])
    neg_rx = None
    if fields["regex_not"]:
        try:
            neg_rx = re.compile(fields["regex_not"])
        except re.error as ex:
            logger.warning("Invalid regex_not '%s': %s", fields["regex_not"], ex)
            neg_rx = None
    return raw, min_len, max_len, neg_rx

def filter_eligible(raw: List[Tuple], fields: Dict[str, Any], neg_rx: Optional[re.Pattern]) -> List[Tuple]:
    out = []
    pre_n, suf_n = fields["prefix_not"], fields["suffix_not"]
    for rec in raw:
        w = rec[0]
        if pre_n and w.startswith(pre_n):  continue
        if suf_n and w.endswith(suf_n):    continue
        if neg_rx and neg_rx.search(w):    continue
        out.append(rec)
    return out

def partition_new_old(rows: List[Tuple]) -> Tuple[List[Tuple], List[Tuple]]:
    new_rows, old_rows = [], []
    for rec in rows:
        (new_rows if not CURATED.is_curated(rec[0]) else old_rows).append(rec)
    return new_rows, old_rows

def mix_curated(new_rows: List[Tuple], old_rows: List[Tuple], limit: int, curated_ratio: int) -> List[Tuple]:
    if curated_ratio <= 0:
        return new_rows[:limit]
    quota = int(math.floor(limit * (curated_ratio / 100.0)))
    curated_pick = random.sample(old_rows, k=min(quota, len(old_rows))) if old_rows and quota > 0 else []
    remaining_slots = max(0, limit - len(curated_pick))
    new_pick = new_rows[:remaining_slots]
    leftover = max(0, limit - (len(curated_pick) + len(new_pick)))
    if leftover > 0:
        remaining_old = [r for r in old_rows if r not in curated_pick]
        curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old))) if remaining_old else []
    return (new_pick + curated_pick)[:limit]

def render_results_html(combined: List[Tuple]) -> str:
    rows = []
    for idx, rec in enumerate(combined, 1):
        word = rec[0]; freq = (rec[1] if len(rec) >= 2 else ""); glen = (rec[2] if len(rec) >= 3 else "")
        rows.append(f"<tr><td>{idx}</td><td>{word}</td><td>{freq}</td><td>{glen}</td></tr>")
    return (
        "<!DOCTYPE html><html><head><title>Query Results</title>"
        "<style>table,th,td{border:1px solid #000;border-collapse:collapse;padding:4px;}th{background:#eee;}</style>"
        "</head><body><h1>Query Results</h1><table><thead>"
        "<tr><th>#</th><th>Word</th><th>Freq</th><th>Glen</th></tr>"
        "</thead><tbody>" + "".join(rows) + "</tbody></table></body></html>"
    )

def build_tsv_lines(rows: List[List[str]]) -> List[str]:
    lines = ["\t".join(["id", "word", "splits", "freq", "glen", "notes"])]
    for r in rows:
        lines.append("\t".join(r))
    return lines

def write_batch_file(batch_dir: str, batch_name: str, tsv_lines: List[str]) -> str:
    os.makedirs(batch_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(batch_dir, batch_name))
    with open(path, "w", encoding="utf-8") as bf:
        bf.write("\n".join(tsv_lines) + "\n")
    return path

def append_ledger(ledger_path: str, batch_name: str, tsv_lines: List[str]) -> str:
    import fcntl
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_header = not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0
    with open(ledger_path, "a", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            if write_header:
                lf.write("\t".join(["timestamp", "batch", "id", "word", "splits", "notes"]) + "\n")
            for ln in tsv_lines[1:]:
                cols = ln.split("\t")
                rec_id = cols[0].strip(); word = cols[1].strip()
                splits = cols[2].strip(); notes = (cols[5].strip() if len(cols) > 5 else "")
                lf.write(f"{ts}\t{batch_name}\t{rec_id or word}\t{word}\t{splits}\t{notes}\n")
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return os.path.abspath(ledger_path)

def compute_summary_data() -> Dict[str, Any]:
    glen_map: Dict[str, int] = {}
    index_words: set = set()
    for w, fr, gl in WORD_INDEX.words:
        glen_map[w] = gl; index_words.add(w)
    curated_set = getattr(CURATED, "curated_words", set())
    curated_in_index = curated_set & index_words
    remaining_set = index_words - curated_in_index
    from collections import Counter
    curated_len = Counter(glen_map[w] for w in curated_in_index if w in glen_map)
    remaining_len = Counter(glen_map[w] for w in remaining_set if w in glen_map)
    lengths = sorted(set(curated_len.keys()) | set(remaining_len.keys()))
    curation_counts = getattr(CURATED, "curation_counts", {})
    total_curations = int(sum(curation_counts.values())) if curation_counts else int(getattr(CURATED, "curated_count", 0))
    return {
        "total_words": len(index_words),
        "curated_distinct": len(curated_in_index),
        "remaining_distinct": len(remaining_set),
        "curation_entries": total_curations,
        "length_distribution": {
            "curated": {gl: curated_len.get(gl, 0) for gl in lengths},
            "remaining": {gl: remaining_len.get(gl, 0) for gl in lengths},
        },
    }

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
