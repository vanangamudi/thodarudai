from __future__ import annotations
import os, sqlite3, time
from typing import List, Tuple, Dict, Iterable, Optional, Set, Any

Row = List[str]

class StorageBase:
    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:  raise NotImplementedError
    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:   raise NotImplementedError
    def load_reminders(self) -> Set[str]:                                     raise NotImplementedError
    def write_reminders(self, words: Set[str]) -> None:                       raise NotImplementedError
    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:            raise NotImplementedError
    def append_summary(self, batch_name: str, summary: Dict[str, Any]) -> str: raise NotImplementedError


class FileStorage(StorageBase):
    def __init__(self, batches_dir: str, ledger_path: str, reminders_path: str):
        self.batches_dir = os.path.abspath(batches_dir)
        self.ledger_path = os.path.abspath(ledger_path)
        self.reminders_path = os.path.abspath(reminders_path)
        os.makedirs(self.batches_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.reminders_path), exist_ok=True)

    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        path = os.path.abspath(os.path.join(self.batches_dir, batch_name))
        with open(path, "w", encoding="utf-8") as f:
            print("id\tword\tsplits\tfreq\tglen\tnotes", file=f)
            for r in edited_rows:
                print("\t".join(r), file=f)
        return path

    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        import fcntl, json as _json
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_header = not os.path.exists(self.ledger_path) or os.path.getsize(self.ledger_path) == 0
        with open(self.ledger_path, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
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
        return self.ledger_path

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
        import fcntl
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
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
class SqliteStorage(StorageBase):
    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init()

    def _conn(self):
        cx = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            cx.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass
        return cx

    def _init(self):
        with self._conn() as cx:
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("PRAGMA synchronous=NORMAL")
            cx.execute("""CREATE TABLE IF NOT EXISTS ledger(
                ts TEXT NOT NULL, batch TEXT NOT NULL, rec_id TEXT, word TEXT, splits TEXT, notes TEXT
            )""")
            cx.execute("""CREATE TABLE IF NOT EXISTS reminders(
                word TEXT PRIMARY KEY, notes TEXT, updated_at TEXT
            )""")

    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows = [(ts, batch_name, r[0], r[1], r[2], (r[5] if len(r) > 5 else "")) for r in edited_rows]
        with self._conn() as cx:
            cx.executemany("INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(?,?,?,?,?,?)", rows)
        return f"sqlite://{self.db_path}#{batch_name}"

    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M%SZ", time.gmtime())
        rows = []
        for ln in tsv_lines[1:]:
            if not ln.strip(): continue
            cols = ln.split("\t")
            rec_id = cols[0].strip(); word = cols[1].strip()
            splits = cols[2].strip(); notes = (cols[5].strip() if len(cols) > 5 else "")
            rows.append((ts, batch_name, rec_id or word, word, splits, notes))
        with self._conn() as cx:
            cx.executemany("INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(?,?,?,?,?,?)", rows)
        return self.db_path

    def load_reminders(self) -> Set[str]:
        with self._conn() as cx:
            cur = cx.execute("SELECT word FROM reminders")
            return {row[0] for row in cur.fetchall()}

    def write_reminders(self, words: Set[str]) -> None:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with self._conn() as cx:
            cx.execute("DELETE FROM reminders")
            cx.executemany("INSERT INTO reminders(word,notes,updated_at) VALUES(?,?,?)",
                           [(w, "", ts) for w in sorted(words)])

    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        with self._conn() as cx:
            cur = cx.execute("SELECT word, COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>'' GROUP BY word")
            words, counts = set(), {}
            for w, n in cur.fetchall():
                words.add(w); counts[w] = int(n)
            return words, counts
    def append_summary(self, batch_name: str, summary: Dict[str, Any]) -> str:
        import json as _json
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec_id = "__SUMMARY__"
        word = str(summary.get("total_words", ""))
        splits = ""
        notes = _json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(?,?,?,?,?,?)",
                (ts, batch_name, rec_id, word, splits, notes),
            )
        return f"sqlite://{self.db_path}#{batch_name}"
