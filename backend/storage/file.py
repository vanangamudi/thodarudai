import os, time
from typing import List, Set, Dict, Tuple, Any
import logging
logger = logging.getLogger("storage.file")

class FileStorage:
    def __init__(self, batches_dir: str, ledger_path: str, reminders_path: str):
        self.batches_dir = os.path.abspath(batches_dir)
        self.ledger_path = os.path.abspath(ledger_path)
        self.reminders_path = os.path.abspath(reminders_path)
        os.makedirs(self.batches_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.reminders_path), exist_ok=True)

    def write_batch(self, edited_rows: List[List[str]], batch_name: str) -> str:
        path = os.path.abspath(os.path.join(self.batches_dir, batch_name))
        logger.info("write_batch: path=%s rows=%d", path, len(edited_rows))
        with open(path, "w", encoding="utf-8") as f:
            print("id\tword\tsplits\tfreq\tglen\tnotes", file=f)
            for r in edited_rows:
                print("\t".join(r), file=f)
            return path
    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        # For the filesystem backend, overwrite the ledger TSV rather than append,
        # so that WordIndex reads a unique aggregated TSV (one row per word) without duplicates.
        logger.info("append_ledger: overwriting path=%s batch=%s", self.ledger_path, batch_name)
        import fcntl, json as _json
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.ledger_path, "w", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                lf.write("timestamp\tbatch\tid\tword\tsplits\tnotes\n")
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
        logger.info("append_ledger: overwritten path=%s", os.path.abspath(self.ledger_path))
        return os.path.abspath(self.ledger_path)

    def load_reminders(self) -> Set[str]:
        out = set()
        try:
            with open(self.reminders_path, "r", encoding="utf-8") as f:
                hdr = f.readline().strip().split("\t")
                idx = {h:i for i,h in enumerate(hdr)}
                if "word" not in idx:
                    return out
                for ln in f:
                    if not ln.strip():
                        continue
                    out.add(ln.rstrip("\n").split("\t")[idx["word"]])
        except FileNotFoundError:
            pass
        return out

    def write_reminders(self, words: Set[str]) -> None:
        logger.info("write_reminders: path=%s words=%d", self.reminders_path, len(words or set()))
        import fcntl
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        os.makedirs(os.path.dirname(self.reminders_path), exist_ok=True)
        with open(self.reminders_path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write("timestamp\tword\tnotes\n")
                for w in sorted(words):
                    f.write(f"{ts}\t{w}\t\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        words, counts = set(), {}
        try:
            for name in os.listdir(self.batches_dir):
                if not name.lower().endswith(".tsv"):
                    continue
                p = os.path.join(self.batches_dir, name)
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        hdr = f.readline().strip().split("\t")
                        idx = {h:i for i,h in enumerate(hdr)}
                        if not {"word","splits"}.issubset(idx):
                            continue
                        for ln in f:
                            if not ln.strip():
                                continue
                            cols = ln.rstrip("\n").split("\t")
                            w = cols[idx["word"]]
                            s = cols[idx["splits"]]
                            if w and s:
                                words.add(w)
                                counts[w] = counts.get(w, 0) + 1
                except (OSError, UnicodeDecodeError):
                    continue
        except FileNotFoundError:
            pass
        return words, counts

    def append_summary(self, batch_name: str, summary: dict) -> str:
        logger.info("append_summary: batch=%s ledger=%s", batch_name, self.ledger_path)
        import json as _json, fcntl
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec_id = "__SUMMARY__"
        word = str(summary.get("total_words", ""))
        splits = ""
        notes = _json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        import os
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        write_header = not os.path.exists(self.ledger_path) or os.path.getsize(self.ledger_path) == 0
        with open(self.ledger_path, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
                    lf.write("timestamp\tbatch\tid\tword\tsplits\tnotes\n")
                lf.write(f"{ts}\t{batch_name}\t{rec_id}\t{word}\t{splits}\t{notes}\n")
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        return self.ledger_path
