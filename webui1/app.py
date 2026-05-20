#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os, time, logging, math, random
import re
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("webui")
STARTUP_TS = int(time.time())
BUILD_TAG = time.strftime("%Y%m%dT%H%M%S", time.localtime(STARTUP_TS))
from fastapi.concurrency import run_in_threadpool
from tools.word_indexer import WordIndex
from tools.curation_index import CuratedIndex

# Configuration constants (reuse file paths from existing code)
WORDLIST_PATH = os.path.abspath("data/word-index.tsv")
BATCHES_DIR = os.path.abspath("data/batches")
LEDGER_PATH = os.path.abspath("data/splits-ledger.tsv")
REMINDERS_PATH = os.path.abspath("data/reminders.tsv")

# Global singleton storage (simple, single user)
WORD_INDEX = None
CURATED = None

def parse_length_spec(length_spec: str):
    min_len = 1
    max_len = None
    if "-" in length_spec:
        parts = length_spec.split("-", 1)
        try:
            if parts[0]:
                min_len = int(parts[0])
        except ValueError:
            min_len = 1
        try:
            if parts[1]:
                max_len = int(parts[1])
        except ValueError:
            max_len = None
    else:
        try:
            m = int(length_spec)
            min_len = m
            max_len = m
        except ValueError:
            min_len = 1
            max_len = None
    return min_len, max_len

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

def initialize_services():
    global WORD_INDEX, CURATED
    WORD_INDEX = WordIndex(WORDLIST_PATH)
    CURATED = CuratedIndex(BATCHES_DIR)
    CURATED.reload()
    logging.info("Initialized WORD_INDEX (%d words) and CURATED (%d curated)",
                 len(WORD_INDEX.words), CURATED.curated_count)
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

@app.post("/api/query")
def query_words(request: Request,
                prefix: str = Form(""),
                suffix: str = Form(""),
                regex: str = Form(""),
                length_spec: str = Form("8-"),
                limit: int = Form(1000),
                prefix_not: str = Form(""),
                suffix_not: str = Form(""),
                regex_not: str = Form(""),
                curated_ratio: int = Form(20)):
    try:
        # Normalize inputs (avoid trailing/leading spaces breaking prefix/suffix matches)
        prefix = (prefix or "").strip()
        suffix = (suffix or "").strip()
        regex = (regex or "").strip()
        prefix_not = (prefix_not or "").strip()
        suffix_not = (suffix_not or "").strip()
        regex_not = (regex_not or "").strip()
        length_spec = (length_spec or "").strip() or "8-"

        t0 = time.perf_counter()
        logger.info("QUERY prefix='%s' suffix='%s' regex='%s' len='%s' limit=%s curated_ratio=%s prefix_not='%s' suffix_not='%s' regex_not='%s'",
                    prefix, suffix, regex, length_spec, limit, curated_ratio, prefix_not, suffix_not, regex_not)
        
        min_len, max_len = parse_length_spec(length_spec)
        probe_limit = min(limit * 5, max(limit + 500, 5000))
        raw = WORD_INDEX.query_words(
            prefix=prefix, suffix=suffix,
            min_len=min_len, max_len=max_len,
            limit=probe_limit, offset=0, regex=regex
        )
        # Apply negative filters
        neg_rx = None
        if regex_not:
            try:
                neg_rx = re.compile(regex_not)
            except re.error as ex:
                logger.warning("Invalid regex_not '%s': %s", regex_not, ex)
                neg_rx = None

        eligible = []
        for rec in raw:
            w = rec[0]
            if prefix_not and w.startswith(prefix_not):
                continue
            if suffix_not and w.endswith(suffix_not):
                continue
            if neg_rx and neg_rx.search(w):
                continue
            eligible.append(rec)
        # Partition new (uncurated) vs old (curated)
        new_rows, old_rows = [], []
        for rec in eligible:
            (new_rows if not CURATED.is_curated(rec[0]) else old_rows).append(rec)
        # Curated mixing
        pct = max(0, min(int(curated_ratio), 100))
        if pct <= 0:
            combined = new_rows[:limit]
        else:
            curated_quota = int(math.floor(limit * (pct / 100.0)))
            curated_pick = []
            if old_rows and curated_quota > 0:
                curated_pick = random.sample(old_rows, k=min(curated_quota, len(old_rows)))
            remaining_slots = max(0, limit - len(curated_pick))
            new_pick = new_rows[:remaining_slots]
            leftover = max(0, limit - (len(curated_pick) + len(new_pick)))
            if leftover > 0:
                remaining_old = [r for r in old_rows if r not in curated_pick]
                if remaining_old:
                    curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old)))
            combined = (new_pick + curated_pick)[:limit]
        
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("QUERY_STATS raw=%d eligible=%d new=%d curated=%d returned=%d dur_ms=%d",
                    len(raw), len(eligible), len(new_rows), len(old_rows), len(combined), dur_ms)
        # Check if the client expects HTML. If yes, format an HTML table.
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header.lower():
            html = """
            <!DOCTYPE html>
            <html>
              <head>
                <title>Query Results</title>
                <style>
                  table, th, td { border: 1px solid black; border-collapse: collapse; padding: 4px; }
                  th { background-color: #eee; }
                </style>
              </head>
              <body>
                <h1>Query Results</h1>
                <table>
                  <thead>
                    <tr><th>#</th><th>Word</th><th>Freq</th><th>Glen</th></tr>
                  </thead>
                  <tbody>
            """
            for idx, rec in enumerate(combined, 1):
                word = rec[0]
                freq = rec[1] if len(rec) >= 2 else ""
                glen = rec[2] if len(rec) >= 3 else ""
                html += f"<tr><td>{idx}</td><td>{word}</td><td>{freq}</td><td>{glen}</td></tr>"
            html += """
                  </tbody>
                </table>
              </body>
            </html>
            """
            return HTMLResponse(content=html)
        else:
            return {"results": combined, "elapsed_ms": dur_ms}
    except Exception as e:
        logging.exception("Error in query endpoint")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/commit")
def commit_edits(batch: str = Form(None), edited_rows: str = Form(...)):
    """
    Expects:
      - edited_rows as a JSON string (list of rows, each row is a list of strings, e.g. [id, word, splits, freq, glen, notes])
      - Optional batch name, otherwise auto-generate.
    """
    import json, fcntl
    try:
        rows = json.loads(edited_rows)
        batch_name = batch if batch else f"batch-{int(time.time())}.tsv"
        batch_dir = BATCHES_DIR
        os.makedirs(batch_dir, exist_ok=True)
        batch_path = os.path.abspath(os.path.join(batch_dir, batch_name))
        logger.info("COMMIT start rows=%d batch=%s batch_path=%s", len(rows), batch_name, batch_path)
        tsv_lines = ["\t".join(["id", "word", "splits", "freq", "glen", "notes"])]
        for r in rows:
            tsv_lines.append("\t".join(r))
        # Write batch TSV to disk
        with open(batch_path, "w", encoding="utf-8") as bf:
            bf.write("\n".join(tsv_lines) + "\n")
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(LEDGER_PATH, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if os.path.getsize(LEDGER_PATH) == 0:
                    lf.write("\t".join(["timestamp", "batch", "id", "word", "splits", "notes"]) + "\n")
                for ln in tsv_lines[1:]:
                    cols = ln.split("\t")
                    rec_id = cols[0].strip()
                    word = cols[1].strip()
                    splits = cols[2].strip()
                    notes = cols[5].strip() if len(cols) > 5 else ""
                    lf.write(f"{ts}\t{batch_name}\t{rec_id or word}\t{word}\t{splits}\t{notes}\n")
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        ledger_abs = os.path.abspath(LEDGER_PATH)
        logger.info("COMMIT done rows=%d batch=%s wrote_batch=%s wrote_ledger=%s", len(rows), batch_name, batch_path, ledger_abs)
        return {
            "status": "committed",
            "batch": batch_name,
            "batch_path": batch_path,
            "ledger_path": ledger_abs,
            "rows": len(rows),
        }
    except Exception as e:
        logging.exception("Error in commit endpoint")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/summary")
def get_summary():
    logger.info("SUMMARY requested")
    try:
        # Build glen_map and index_words from WordIndex.words
        # words is list of (word, freq, glen)
        glen_map = {}
        index_words = set()
        for w, fr, gl in WORD_INDEX.words:
            glen_map[w] = gl
            index_words.add(w)
        curated_set = getattr(CURATED, "curated_words", set())
        curated_in_index = curated_set & index_words
        remaining_set = index_words - curated_in_index

        # Length distribution
        from collections import Counter
        curated_len = Counter(glen_map[w] for w in curated_in_index if w in glen_map)
        remaining_len = Counter(glen_map[w] for w in remaining_set if w in glen_map)
        lengths = sorted(set(curated_len.keys()) | set(remaining_len.keys()))
        length_distribution = {
            "curated": {gl: curated_len.get(gl, 0) for gl in lengths},
            "remaining": {gl: remaining_len.get(gl, 0) for gl in lengths},
        }

        # Total curation entries
        curation_counts = getattr(CURATED, "curation_counts", {})
        total_curations = int(sum(curation_counts.values())) if curation_counts else int(getattr(CURATED, "curated_count", 0))

        return {
            "total_words": len(index_words),
            "curated_distinct": len(curated_in_index),
            "remaining_distinct": len(remaining_set),
            "curation_entries": total_curations,
            "length_distribution": length_distribution,
        }
    except Exception as e:
        logging.exception("Error in summary endpoint")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders")
def get_reminders():
    logger.info("REMINDERS get")
    try:
        return {"words": sorted(load_reminders())}
    except Exception as e:
        logging.exception("Error in reminders get")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Body
@app.post("/api/reminders")
def update_reminders(action: str = Form(...), words_json: str = Form("[]")):
    logger.info("REMINDERS update action=%s", action)
    """
    action: 'add' or 'remove'
    words_json: JSON-serialized list of words
    """
    import json
    try:
        words = set(json.loads(words_json) or [])
        current = load_reminders()
        if action == "add":
            current |= words
        elif action == "remove":
            current -= words
        else:
            raise HTTPException(status_code=400, detail="invalid action")
        write_reminders(current)
        return {"status": "ok", "count": len(current)}
    except Exception as e:
        logging.exception("Error in reminders update")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/results")
def get_reminder_results():
    logger.info("REMINDERS results")
    try:
        rem = load_reminders()
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
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
