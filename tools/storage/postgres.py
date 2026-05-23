from __future__ import annotations
import time, logging
from typing import List, Tuple, Dict, Iterable, Optional, Set, Any
from . import StorageBase, Row, psycopg2, execute_batch

logger = logging.getLogger("storage.postgres")

class PostgresStorage(StorageBase):
    def __init__(self, dsn: str, profile: str = "default"):
        if psycopg2 is None:
            raise ImportError("psycopg2 is required for PostgresStorage. Install with: pip install psycopg2-binary")
        self.dsn = dsn
        self.profile = profile
        logger.info("PostgresStorage: dsn=%s profile=%s", self._mask_dsn_for_path(), self.profile)
        self._init()

    def _conn(self):
        cx = psycopg2.connect(self.dsn)
        cx.autocommit = True
        return cx

    def _init(self):
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute("""
                  CREATE TABLE IF NOT EXISTS ledger(
                      id BIGSERIAL PRIMARY KEY,
                      ts TIMESTAMPTZ NOT NULL,
                      batch TEXT NOT NULL,
                      rec_id TEXT,
                      word TEXT,
                      splits TEXT,
                      notes TEXT
                  )
              """)
            cur.execute("""
                  CREATE TABLE IF NOT EXISTS reminders(
                      word TEXT PRIMARY KEY,
                      notes TEXT,
                      updated_at TIMESTAMPTZ
                  )
              """)
            cur.execute("ALTER TABLE ledger ADD COLUMN IF NOT EXISTS profile TEXT")
            cur.execute("ALTER TABLE reminders ADD COLUMN IF NOT EXISTS profile TEXT")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS reminders_profile_word_idx ON reminders (profile, word)")
            # Core tables for words and segmentations
            cur.execute("""
                CREATE TABLE IF NOT EXISTS words (
                    word TEXT PRIMARY KEY,
                    freq INTEGER NOT NULL,
                    glen INTEGER NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS segmentations (
                    id BIGSERIAL PRIMARY KEY,
                    word TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    split_pos INTEGER NOT NULL,
                    left_text TEXT NOT NULL,
                    right_text TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS seg_word_created ON segmentations(word, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS seg_profile_word ON segmentations(profile, word)")

    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        logger.info("write_batch: batch=%s rows=%d profile=%s", batch_name, len(edited_rows), self.profile)
        logger.info("write_batch: method=%s", "execute_batch" if execute_batch else "executemany")
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows = [(ts, batch_name, r[0], r[1], r[2], (r[5] if len(r) > 5 else ""), self.profile) for r in edited_rows]
        with self._conn() as cx, cx.cursor() as cur:
            if execute_batch:
                execute_batch(cur, "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows, page_size=1000)
            else:
                cur.executemany("INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows)
        return f"postgres://{self._mask_dsn_for_path()}#{batch_name}"


    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        logger.info("append_ledger: batch=%s lines=%d profile=%s", batch_name, max(0, len(tsv_lines)-1), self.profile)
        logger.info("append_ledger: method=%s", "execute_batch" if execute_batch else "executemany")
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows = []
        for ln in tsv_lines[1:]:
            if not ln.strip():
                continue
            cols = ln.split("\t")
            rec_id = cols[0].strip(); word = cols[1].strip()
            splits = cols[2].strip(); notes = (cols[5].strip() if len(cols) > 5 else "")
            rows.append((ts, batch_name, rec_id or word, word, splits, notes, self.profile))
        with self._conn() as cx, cx.cursor() as cur:
            if execute_batch:
                execute_batch(cur, "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows, page_size=1000)
            else:
                cur.executemany("INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows)
        return f"postgres://{self._mask_dsn_for_path()}#{batch_name}"

    def load_reminders(self) -> Set[str]:
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute("SELECT word FROM reminders WHERE profile=%s", (self.profile,))
            except Exception:
                cur.execute("SELECT word FROM reminders")
            rows = cur.fetchall()
            words = {row[0] for row in rows}
            logger.info("load_reminders: profile=%s count=%d", self.profile, len(words))
            return words

    def write_reminders(self, words: Set[str]) -> None:
        logger.info("write_reminders: profile=%s words=%d", self.profile, len(words or []))
        logger.info("write_reminders: method=%s", "execute_batch" if execute_batch else "executemany")
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute("DELETE FROM reminders WHERE profile=%s", (self.profile,))
            except Exception:
                cur.execute("DELETE FROM reminders")
            if words:
                data = [(self.profile, w, "", ts) for w in sorted(words)]
                sql = "INSERT INTO reminders(profile,word,notes,updated_at) VALUES(%s,%s,%s,%s) ON CONFLICT (profile, word) DO UPDATE SET notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at"
                if execute_batch:
                    execute_batch(cur, sql, data, page_size=1000)
                else:
                    cur.executemany(sql, data)
        logger.info("write_reminders: updated reminders for profile=%s", self.profile)

    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute("SELECT word, COUNT(*) FROM segmentations GROUP BY word")
            except Exception:
                cur.execute("SELECT word, COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>'' GROUP BY word")
            words, counts = set(), {}
            rows = cur.fetchall()
            for w, n in rows:
                words.add(w); counts[w] = int(n)
            logger.info("get_curated_sets: curated_distinct=%d total_entries=%d", len(words), sum(counts.values()))
            return words, counts

    def append_summary(self, batch_name: str, summary: Dict[str, Any]) -> str:
        import json as _json
        logger.info("append_summary: batch=%s profile=%s", batch_name, self.profile)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec_id = "__SUMMARY__"
        word = str(summary.get("total_words", ""))
        splits = ""
        notes = _json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (ts, batch_name, rec_id, word, splits, notes, self.profile),
                )
            except Exception:
                cur.execute(
                    "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes) VALUES(%s,%s,%s,%s,%s,%s)",
                    (ts, batch_name, rec_id, word, splits, notes),
                )
        return f"postgres://{self._mask_dsn_for_path()}#{batch_name}"

    def _mask_dsn_for_path(self) -> str:
        dsn = self.dsn
        if "://" in dsn:
            try:
                scheme, rest = dsn.split("://", 1)
                if "@" in rest and ":" in rest.split("@", 1)[0]:
                    user, tail = rest.split("@", 1)
                    u, _pw = user.split(":", 1)
                    return f"{scheme}://{u}:***@{tail}"
                return dsn
            except Exception:
                return dsn
        return dsn.replace("password=", "password=***")
    def has_words(self) -> bool:
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute("SELECT to_regclass('public.words')")
                exists = cur.fetchone()[0] is not None
                if not exists:
                    return False
                cur.execute("SELECT COUNT(*) FROM words")
                row = cur.fetchone()
                ok = (row[0] if row else 0) > 0
                logger.debug("has_words: %s", ok)
                return ok
            except Exception:
                return False
    def ensure_words(self, records: Iterable[Tuple[str,int,int]]) -> None:
        recs = list(records or [])
        if not recs:
            return
        with self._conn() as cx, cx.cursor() as cur:
            logger.info("ensure_words: method=%s", "execute_batch" if execute_batch else "executemany")
            cur.execute("CREATE TABLE IF NOT EXISTS words(word TEXT PRIMARY KEY, freq INTEGER, glen INTEGER)")
            sql = (
                "INSERT INTO words(word,freq,glen) VALUES (%s,%s,%s) "
                "ON CONFLICT(word) DO UPDATE SET freq=EXCLUDED.freq, glen=EXCLUDED.glen"
            )
            if execute_batch:
                execute_batch(cur, sql, recs, page_size=10000)
            else:
                cur.executemany(sql, recs)

    def query_index(self, prefix: str, suffix: str, regex: str,
                    prefix_not: str, suffix_not: str, regex_not: str,
                    min_len: int, max_len, limit: int, curated_ratio: int) -> List[Tuple[str,int,int]]:
        where = ["glen >= %s"]
        params: List[Any] = [int(min_len)]
        if max_len is not None:
            where.append("glen <= %s"); params.append(int(max_len))
        if prefix:
            where.append("word LIKE %s"); params.append(f"{prefix}%")
        if suffix:
            where.append("word LIKE %s"); params.append(f"%{suffix}")
        if regex:
            where.append("word ~ %s"); params.append(regex)
        sql = f"""
            SELECT word, freq, glen
            FROM words
            WHERE {' AND '.join(where)}
            ORDER BY glen DESC, freq DESC, word ASC
            LIMIT %s
        """
        params.append(int(limit) if limit is not None else 1000)
        t0 = time.perf_counter()
        logger.info("query_index: prefix=%r suffix=%r regex=%r min_len=%s max_len=%s limit=%s",
                    prefix, suffix, regex, min_len, max_len, limit)
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute(sql, params)
            rows = [(r[0], int(r[1]), int(r[2])) for r in cur.fetchall()]
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("query_index: returned=%d dur_ms=%d", len(rows), dur_ms)
        return rows

    def get_latest_splits(self) -> Dict[str,str]:
        qry = """
        SELECT l.word, l.left_text, l.right_text
        FROM segmentations l
        JOIN (SELECT word, MAX(created_at) m FROM segmentations GROUP BY word) t
          ON t.word=l.word AND t.m=l.created_at
        """
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute(qry)
            res = {w: f"{lt}-{rt}" for (w, lt, rt) in cur.fetchall()}
            logger.info("get_latest_splits: rows=%d", len(res))
            return res

    def add_segmentation(self, word: str, left_text: str, right_text: str, split_pos: int, notes: str = "") -> None:
        logger.info("add_segmentation: word=%s split_pos=%d profile=%s", word, int(split_pos), self.profile)
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute(
                "INSERT INTO segmentations(word,profile,split_pos,left_text,right_text,notes) VALUES(%s,%s,%s,%s,%s,%s)",
                (word, self.profile, int(split_pos), left_text, right_text, notes)
            )

<<<<<<< HEAD
=======
    def commit_segmentations(self, rows: Iterable[Tuple[str, str, str, int, str]], batch_name: str) -> int:
        """
        Commit multiple segmentation records atomically.
        Each row is a tuple: (word, left_text, right_text, split_pos, notes).
        Uses executemany/execute_batch under one transaction and returns the number of rows committed.
        """
        import time
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        seg_rows = [(word, self.profile, int(split_pos), left_text, right_text, notes)
                    for word, left_text, right_text, split_pos, notes in rows]
        with self._conn() as cx, cx.cursor() as cur:
            if execute_batch:
                execute_batch(cur, "INSERT INTO segmentations(word,profile,split_pos,left_text,right_text,notes) VALUES(%s,%s,%s,%s,%s,%s)", seg_rows, page_size=1000)
            else:
                cur.executemany("INSERT INTO segmentations(word,profile,split_pos,left_text,right_text,notes) VALUES(%s,%s,%s,%s,%s,%s)", seg_rows)
        return len(seg_rows)
>>>>>>> 5062a46 (frontend fixup; segmentations are properly commited to the database)
    def list_segmentations(self, word: str, scope: Optional[str] = None) -> List[Dict[str,Any]]:
        logger.info("list_segmentations: word=%s scope=%s", word, scope or "all")
        rows = []
        with self._conn() as cx, cx.cursor() as cur:
            if scope == "me":
                cur.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=%s AND profile=%s ORDER BY created_at DESC,id DESC", (word, self.profile))
            elif scope and scope.startswith("actor:"):
                who = scope.split(":", 1)[1]
                cur.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=%s AND profile=%s ORDER BY created_at DESC,id DESC", (word, who))
            else:
                cur.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=%s ORDER BY created_at DESC,id DESC", (word,))
            for pr, sp, lt, rt, no, ct in cur.fetchall():
                rows.append({"profile": pr, "split_pos": int(sp), "left_text": lt, "right_text": rt, "notes": no or "", "created_at": str(ct)})
            logger.info("list_segmentations: returned=%d", len(rows))
        return rows

    def summary(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        logger.info("summary: computing from DB")
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM words")
            total_words = int((cur.fetchone() or (0,))[0])
            try:
                cur.execute("SELECT COUNT(DISTINCT word) FROM segmentations")
                curated_distinct = int((cur.fetchone() or (0,))[0])
                cur.execute("SELECT COUNT(*) FROM segmentations")
                curated_entries = int((cur.fetchone() or (0,))[0])
                cur.execute("""
                    SELECT w.glen,
                           SUM(CASE WHEN s.word IS NOT NULL THEN 1 ELSE 0 END) AS curated,
                           SUM(CASE WHEN s.word IS NULL THEN 1 ELSE 0 END)  AS remaining
                    FROM words w
                    LEFT JOIN (SELECT DISTINCT word FROM segmentations) s ON s.word = w.word
                    GROUP BY w.glen
                """)
                rows = cur.fetchall()
            except Exception:
                cur.execute("SELECT COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>''")
                curated_entries = int((cur.fetchone() or (0,))[0])
                cur.execute("SELECT COUNT(DISTINCT word) FROM ledger WHERE COALESCE(splits,'')<>''")
                curated_distinct = int((cur.fetchone() or (0,))[0])
                cur.execute("""
                    WITH cur AS (SELECT DISTINCT word FROM ledger WHERE COALESCE(splits,'')<>'')
                    SELECT w.glen,
                           SUM(CASE WHEN w.word IN (SELECT word FROM cur) THEN 1 ELSE 0 END) AS curated,
                           SUM(CASE WHEN w.word NOT IN (SELECT word FROM cur) THEN 1 ELSE 0 END) AS remaining
                    FROM words w
                    GROUP BY w.glen
                """)
                rows = cur.fetchall()
        curated = {int(gl): int(c) for (gl, c, _r) in ((r[0], r[1], r[2]) for r in rows)}
        remaining = {int(gl): int(r) for (gl, _c, r) in ((r[0], r[1], r[2]) for r in rows)}
        res = {
            "total_words": total_words,
            "curated_distinct": curated_distinct,
            "remaining_distinct": max(0, total_words - curated_distinct),
            "curation_entries": curated_entries,
            "length_distribution": {"curated": curated, "remaining": remaining},
        }
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("summary: total=%d curated_distinct=%d entries=%d dur_ms=%d",
                    total_words, curated_distinct, curated_entries, dur_ms)
        return res
