from __future__ import annotations
import os, sqlite3, time, re
from typing import List, Tuple, Dict, Iterable, Optional, Set, Any
from . import StorageBase, Row

class SqliteStorage(StorageBase):
    def __init__(self, db_path: str, profile: str = "default"):
        self.db_path = os.path.abspath(db_path)
        self.profile = profile
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init()

    def _conn(self):
        cx = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            cx.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass
        try:
            cx.create_function("REGEXP", 2, lambda expr, item: 1 if (item is not None and re.search(expr, str(item))) else 0)
        except Exception:
            pass
        return cx

    def _has_column(self, cx, table: str, col: str) -> bool:
        try:
            cur = cx.execute(f"PRAGMA table_info({table})")
            return any(row[1] == col for row in cur.fetchall())
        except Exception:
            return False

    def _init(self):
        with self._conn() as cx:
            cx.execute("PRAGMA journal_mode=WAL")
            cx.execute("PRAGMA synchronous=NORMAL")
            cx.execute("""CREATE TABLE IF NOT EXISTS ledger(
                ts TEXT NOT NULL, batch TEXT NOT NULL, rec_id TEXT, word TEXT, splits TEXT, notes TEXT, profile TEXT NOT NULL DEFAULT 'default'
            )""")
            cx.execute("""CREATE TABLE IF NOT EXISTS reminders(
                profile TEXT NOT NULL DEFAULT 'default', word TEXT NOT NULL, notes TEXT, updated_at TEXT,
                PRIMARY KEY(profile, word)
            )""")
            try:
                cx.execute("ALTER TABLE ledger ADD COLUMN IF NOT EXISTS profile TEXT DEFAULT 'default'")
            except Exception:
                pass
            try:
                cx.execute("""
                    CREATE TABLE IF NOT EXISTS segmentations (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      word TEXT NOT NULL,
                      profile TEXT NOT NULL,
                      split_pos INTEGER NOT NULL,
                      left_text TEXT NOT NULL,
                      right_text TEXT NOT NULL,
                      notes TEXT,
                      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                    )
                """)
                cx.execute("CREATE INDEX IF NOT EXISTS seg_word_created ON segmentations(word, created_at DESC)")
                cx.execute("CREATE INDEX IF NOT EXISTS seg_profile_word ON segmentations(profile, word)")
            except Exception:
                pass

    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows = [(ts, batch_name, r[0], r[1], r[2], (r[5] if len(r) > 5 else ""), self.profile) for r in edited_rows]
        with self._conn() as cx:
            if self._has_column(cx, "ledger", "profile"):
                cx.executemany(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(?,?,?,?,?,?,?)",
                    rows
                )
            else:
                cx.executemany(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(?,?,?,?,?,?)",
                    [r[:-1] for r in rows]
                )
        return f"sqlite://{self.db_path}#{batch_name}"

    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
            try:
                cur = cx.execute("SELECT word FROM reminders WHERE profile=?", (self.profile,))
            except Exception:
                cur = cx.execute("SELECT word FROM reminders")
            return {row[0] for row in cur.fetchall()}

    def write_reminders(self, words: Set[str]) -> None:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rows_p = [(self.profile, w, "", ts) for w in sorted(words)]
        rows_g = [(w, "", ts) for w in sorted(words)]
        with self._conn() as cx:
            try:
                cx.execute("DELETE FROM reminders WHERE profile=?", (self.profile,))
                if rows_p:
                    cx.executemany(
                        "INSERT INTO reminders(profile,word,notes,updated_at) VALUES(?,?,?,?)",
                        rows_p
                    )
            except Exception:
                cx.execute("DELETE FROM reminders")
                if rows_g:
                    cx.executemany(
                        "INSERT INTO reminders(word,notes,updated_at) VALUES(?,?,?)",
                        rows_g
                    )

    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        with self._conn() as cx:
            if self._has_column(cx, "ledger", "profile"):
                cur = cx.execute("SELECT word, COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>'' AND profile=? GROUP BY word", (self.profile,))
            else:
                cur = cx.execute("SELECT word, COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>'' GROUP BY word")
            words, counts = set(), {}
            for w, n in cur.fetchall():
                words.add(w); counts[w] = int(n)
            return words, counts

    def summary(self) -> Dict[str, Any]:
        with self._conn() as cx:
            total_words = int((cx.execute("SELECT COUNT(*) FROM words").fetchone() or (0,))[0])
            try:
                curated_distinct = int((cx.execute("SELECT COUNT(DISTINCT word) FROM segmentations").fetchone() or (0,))[0])
                curated_entries = int((cx.execute("SELECT COUNT(*) FROM segmentations").fetchone() or (0,))[0])
                rows = cx.execute("""
                    SELECT w.glen,
                           SUM(CASE WHEN s.word IS NOT NULL THEN 1 ELSE 0 END) AS curated,
                           SUM(CASE WHEN s.word IS NULL THEN 1 ELSE 0 END)  AS remaining
                    FROM words w
                    LEFT JOIN (SELECT DISTINCT word FROM segmentations) s ON s.word = w.word
                    GROUP BY w.glen
                """).fetchall()
            except Exception:
                curated_entries = int((cx.execute("SELECT COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>''").fetchone() or (0,))[0])
                curated_distinct = int((cx.execute("SELECT COUNT(DISTINCT word) FROM ledger WHERE COALESCE(splits,'')<>''").fetchone() or (0,))[0])
                rows = cx.execute("""
                    WITH cur AS (SELECT DISTINCT word FROM ledger WHERE COALESCE(splits,'')<>'')
                    SELECT w.glen,
                           SUM(CASE WHEN w.word IN (SELECT word FROM cur) THEN 1 ELSE 0 END) AS curated,
                           SUM(CASE WHEN w.word NOT IN (SELECT word FROM cur) THEN 1 ELSE 0 END) AS remaining
                    FROM words w
                    GROUP BY w.glen
                """).fetchall()
            curated = {}
            remaining = {}
            for gl, c, r in rows:
                curated[int(gl)] = int(c)
                remaining[int(gl)] = int(r)
            return {
                "total_words": total_words,
                "curated_distinct": curated_distinct,
                "remaining_distinct": max(0, total_words - curated_distinct),
                "curation_entries": curated_entries,
                "length_distribution": {"curated": curated, "remaining": remaining},
            }
    def append_summary(self, batch_name: str, summary: Dict[str, Any]) -> str:
        import json as _json
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec_id = "__SUMMARY__"
        word = str(summary.get("total_words", ""))
        splits = ""
        notes = _json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        with self._conn() as cx:
            if self._has_column(cx, "ledger", "profile"):
                cx.execute(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(?,?,?,?,?,?,?)",
                    (ts, batch_name, rec_id, word, splits, notes, self.profile),
                )
            else:
                cx.execute(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(?,?,?,?,?,?)",
                    (ts, batch_name, rec_id, word, splits, notes),
                )
        return f"sqlite://{self.db_path}#{batch_name}"

    def ensure_words(self, records: Iterable[Tuple[str, int, int]]) -> None:
        recs = list(records or [])
        if not recs:
            return
        with self._conn() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS words(word TEXT PRIMARY KEY, freq INTEGER, glen INTEGER)")
            cx.executemany(
                "INSERT INTO words(word,freq,glen) VALUES (?,?,?) ON CONFLICT(word) DO UPDATE SET freq=excluded.freq, glen=excluded.glen",
                recs
            )

    def has_words(self) -> bool:
        with self._conn() as cx:
            try:
                cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='words'")
                if not cur.fetchone():
                    return False
                row = cx.execute("SELECT COUNT(*) FROM words").fetchone()
                return (row[0] if row else 0) > 0
            except Exception:
                return False

    def query_index(self, prefix: str, suffix: str, regex: str,
                    prefix_not: str, suffix_not: str, regex_not: str,
                    min_len: int, max_len, limit: int, curated_ratio: int) -> list:
        where = ["glen >= ?"]
        params = [int(min_len)]
        if max_len is not None:
            where.append("glen <= ?")
            params.append(int(max_len))
        if prefix:
            where.append("word LIKE ?")
            params.append(f"{prefix}%")
        if suffix:
            where.append("word LIKE ?")
            params.append(f"%{suffix}")
        if regex:
            where.append("word REGEXP ?")
            params.append(regex)
        # Note: negative filters (prefix_not/suffix_not/regex_not) and curated mixing are applied in the GUI layer.
        sql = f"""
            SELECT word, freq, glen
            FROM words
            WHERE {' AND '.join(where)}
            ORDER BY glen DESC, freq DESC, word ASC
            LIMIT ?
        """
        params.append(int(limit) if limit is not None else 1000)
        with self._conn() as cx:
            cur = cx.execute(sql, params)
            return [(row[0], int(row[1]), int(row[2])) for row in cur.fetchall()]
