from typing import List, Tuple, Optional, Dict, Any
import os, re, time, math, random

def parse_length_spec(length_spec: str) -> Tuple[int, Optional[int]]:
    s = (length_spec or "").strip()
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            min_len = int(a) if a else 1
        except ValueError:
            min_len = 1
        try:
            max_len = int(b) if b else None
        except ValueError:
            max_len = None
        return min_len, max_len
    try:
        n = int(s)
        return n, n
    except ValueError:
        return 1, None

def sanitize_component(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', (s or '')).strip('_')[:64]

def default_batch_name(prefix: str, suffix: str, length_spec: str) -> str:
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    return f"{ts}-{sanitize_component(prefix)}-{sanitize_component(length_spec)}-{sanitize_component(suffix)}.tsv"

def compile_neg_regex(pattern: str) -> Optional[re.Pattern]:
    p = (pattern or "").strip()
    if not p:
        return None
    try:
        return re.compile(p)
    except re.error:
        return None

def filter_eligible(raw: List[Tuple], prefix_not: str, suffix_not: str, neg_rx: Optional[re.Pattern]) -> List[Tuple]:
    pre_n, suf_n = (prefix_not or ""), (suffix_not or "")
    out = []
    for rec in raw:
        w = rec[0]
        if pre_n and w.startswith(pre_n):
            continue
        if suf_n and w.endswith(suf_n):
            continue
        if neg_rx and neg_rx.search(w):
            continue
        out.append(rec)
    return out

def partition_new_old(rows: List[Tuple], curated_index) -> Tuple[List[Tuple], List[Tuple]]:
    new_rows, old_rows = [], []
    for rec in rows:
        (new_rows if not curated_index.is_curated(rec[0]) else old_rows).append(rec)
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
        if remaining_old:
            curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old)))
    return (new_pick + curated_pick)[:limit]

def mix_curated_with_counts(new_rows: List[Tuple], old_rows: List[Tuple], limit: int, curated_ratio: float) -> Tuple[List[Tuple], int, int]:
    if curated_ratio <= 0.0:
        pick = new_rows[:limit]
        return pick, len(pick), 0
    quota = int(math.floor(limit * curated_ratio))
    curated_pick = random.sample(old_rows, k=min(quota, len(old_rows))) if old_rows and quota > 0 else []
    remaining_slots = max(0, limit - len(curated_pick))
    new_pick = new_rows[:remaining_slots]
    leftover = max(0, limit - (len(curated_pick) + len(new_pick)))
    if leftover > 0:
        remaining_old = [r for r in old_rows if r not in curated_pick]
        if remaining_old:
            curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old)))
    combined = (new_pick + curated_pick)[:limit]
    return combined, len(new_pick), len(curated_pick)

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
    import fcntl  # keep local to avoid hard dep for importers
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_header = not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0
    with open(ledger_path, "a", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            if write_header:
                lf.write("\t".join(["timestamp", "batch", "id", "word", "splits", "notes"]) + "\n")
            for ln in tsv_lines[1:]:
                if not ln.strip():
                    continue
                cols = ln.split("\t")
                rec_id = cols[0].strip()
                word = cols[1].strip()
                splits = cols[2].strip()
                notes = (cols[5].strip() if len(cols) > 5 else "")
                lf.write(f"{ts}\t{batch_name}\t{rec_id or word}\t{word}\t{splits}\t{notes}\n")
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    return os.path.abspath(ledger_path)

def load_reminders(path: str) -> set:
    rem = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            idx = {h: i for i, h in enumerate(header)}
            if "word" not in idx:
                return rem
            for ln in f:
                if not ln.strip():
                    continue
                cols = ln.rstrip("\n").split("\t")
                w = cols[idx["word"]]
                if w:
                    rem.add(w)
    except FileNotFoundError:
        pass
    return rem

def write_reminders(path: str, words: set) -> None:
    import fcntl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    with open(path, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write("timestamp\tword\tnotes\n")
            for w in sorted(words):
                f.write(f"{ts}\t{w}\t\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def compute_summary_data(word_index, curated_index) -> Dict[str, Any]:
    glen_map: Dict[str, int] = {}
    index_words: set = set()
    for w, fr, gl in word_index.words:
        glen_map[w] = gl
        index_words.add(w)
    curated_set = getattr(curated_index, "curated_words", set())
    curated_in_index = curated_set & index_words
    remaining_set = index_words - curated_in_index
    from collections import Counter
    curated_len = Counter(glen_map[w] for w in curated_in_index if w in glen_map)
    remaining_len = Counter(glen_map[w] for w in remaining_set if w in glen_map)
    lengths = sorted(set(curated_len.keys()) | set(remaining_len.keys()))
    curation_counts = getattr(curated_index, "curation_counts", {})
    total_curations = int(sum(curation_counts.values())) if curation_counts else int(getattr(curated_index, "curated_count", 0))
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
# Shared normalization and full query pipeline
from typing import Dict, Any, List, Tuple, Optional
import time

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

def run_query(word_index, curated_index, fields: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    min_len, max_len = parse_length_spec(fields["length_spec"])
    probe_limit = min(fields["limit"] * 5, max(fields["limit"] + 500, 5000))
    raw = word_index.query_words(prefix=fields["prefix"], suffix=fields["suffix"],
                                 min_len=min_len, max_len=max_len,
                                 limit=probe_limit, offset=0, regex=fields["regex"])
    neg_rx = compile_neg_regex(fields.get("regex_not", ""))
    eligible = filter_eligible(raw, fields.get("prefix_not", ""), fields.get("suffix_not", ""), neg_rx)
    new_rows, old_rows = partition_new_old(eligible, curated_index)
    combined = mix_curated(new_rows, old_rows, fields["limit"], fields["curated_ratio"])
    return {
        "combined": combined,
        "stats": {"raw": len(raw), "eligible": len(eligible), "new": len(new_rows), "curated": len(old_rows)},
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
