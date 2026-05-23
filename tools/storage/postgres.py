class PostgresStorage(StorageBase):
    def __init__(self, dsn: str, profile: str = "default"):
        if psycopg2 is None:
            raise ImportError("psycopg2 is required for PostgresStorage. Install with: pip install psycopg2-binary")
        self.dsn = dsn
        self.profile = profile
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

    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rows = [(ts, batch_name, r[0], r[1], r[2], (r[5] if len(r) > 5 else ""), self.profile) for r in edited_rows]
        with self._conn() as cx, cx.cursor() as cur:
            if execute_batch:
                execute_batch(cur, "INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows, page_size=1000)
            else:
                cur.executemany("INSERT INTO ledger(ts,batch,rec_id,word,splits,notes,profile) VALUES(%s,%s,%s,%s,%s,%s,%s)", rows)
        return f"postgres://{self._mask_dsn_for_path()}#{batch_name}"

    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
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
            return {row[0] for row in cur.fetchall()}

    def write_reminders(self, words: Set[str]) -> None:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with self._conn() as cx, cx.cursor() as cur:
            cur.execute("DELETE FROM reminders")
            if words:
                data = [(w, "", ts) for w in sorted(words)]
                if execute_batch:
                    execute_batch(cur, "INSERT INTO reminders(word,notes,updated_at) VALUES(%s,%s,%s) ON CONFLICT (word) DO UPDATE SET notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at", data, page_size=1000)
                else:
                    cur.executemany("INSERT INTO reminders(word,notes,updated_at) VALUES(%s,%s,%s) ON CONFLICT (word) DO UPDATE SET notes=EXCLUDED.notes, updated_at=EXCLUDED.updated_at", data)

    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        with self._conn() as cx, cx.cursor() as cur:
            try:
                cur.execute("SELECT word, COUNT(*) FROM segmentations GROUP BY word")
            except Exception:
                cur.execute("SELECT word, COUNT(*) FROM ledger WHERE COALESCE(splits,'')<>'' GROUP BY word")
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
        with self._conn() as cx:
            try:
                cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='words'")
                if not cur.fetchone():
                    return False
                return (cx.execute("SELECT COUNT(*) FROM words").fetchone() or (0,))[0] > 0
            except Exception:
                return False
    def ensure_words(self, records: Iterable[Tuple[str,int,int]]) -> None:
        recs = list(records or [])
        if not recs:
            return
        with self._conn() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS words(word TEXT PRIMARY KEY,freq INTEGER,glen INTEGER)")
            cx.executemany(
                "INSERT INTO words(word,freq,glen) VALUES (?,?,?) ON CONFLICT(word) DO UPDATE SET freq=excluded.freq, glen=excluded.glen",
                recs
            )
    
    def query_index(self, prefix: str, suffix: str, regex: str,
                    prefix_not: str, suffix_not: str, regex_not: str,
                    min_len: int, max_len, limit: int, curated_ratio: int) -> List[Tuple[str,int,int]]:
        where = ["glen >= ?"]
        params: List[Any] = [int(min_len)]
        if max_len is not None:
            where.append("glen <= ?"); params.append(int(max_len))
        if prefix:
            where.append("word LIKE ?"); params.append(f"{prefix}%")
        if suffix:
            where.append("word LIKE ?"); params.append(f"%{suffix}")
        if regex:
            where.append("word REGEXP ?"); params.append(regex)
        # Note: negative filters and curated mixing are applied in GUI for now.
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
    def get_latest_splits(self) -> Dict[str,str]:
        qry = """
        SELECT l.word, l.left_text, l.right_text
        FROM segmentations l
        JOIN (SELECT word, MAX(created_at) m FROM segmentations GROUP BY word) t
          ON t.word=l.word AND t.m=l.created_at
        """
        with self._conn() as cx:
            return {w: f"{lt}-{rt}" for (w, lt, rt) in cx.execute(qry).fetchall()}
    def add_segmentation(self, word: str, left_text: str, right_text: str, split_pos: int, notes: str = "") -> None:
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO segmentations(word,profile,split_pos,left_text,right_text,notes) VALUES(?,?,?,?,?,?)",
                (word, self.profile, int(split_pos), left_text, right_text, notes)
            )
    def list_segmentations(self, word: str, scope: Optional[str] = None) -> List[Dict[str,Any]]:
        rows = []
        with self._conn() as cx:
            if scope == "me":
                cur = cx.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=? AND profile=? ORDER BY created_at DESC,id DESC", (word, self.profile))
            elif scope and scope.startswith("actor:"):
                who = scope.split(":", 1)[1]
                cur = cx.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=? AND profile=? ORDER BY created_at DESC,id DESC", (word, who))
            else:
                cur = cx.execute("SELECT profile,split_pos,left_text,right_text,notes,created_at FROM segmentations WHERE word=? ORDER BY created_at DESC,id DESC", (word,))
            for pr, sp, lt, rt, no, ct in cur.fetchall():
                rows.append({"profile": pr, "split_pos": int(sp), "left_text": lt, "right_text": rt, "notes": no or "", "created_at": str(ct)})
        return rows
