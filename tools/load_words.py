#!/usr/bin/env python3
"""
Load Words Script

This script is similar to build_word_index.py but instead of always printing
a TSV to stdout it loads the word records into a persistent store. The store
may be a file (TSV) or a SQLite database.

Usage examples:
  # For file-backed: write out a TSV file.
  $ python tools/load_words.py file --files input1.tsv input2.tsv --out output.tsv

  # For SQLite-backed: load records into the "words" table.
  $ python tools/load_words.py sqlite --files input1.tsv --db_path data/words.db
"""

import sys, os, sqlite3, time
import argparse
from tools.profile import Profile
from tools.common import aggregate_precomputed
import logging
logger = logging.getLogger("load_words")
from tools.storage.postgres import save_words_to_postgres

# Reuse the openfile helper from build_word_index.py:

# For file-backed output
def save_words_to_file(records, out_path):
    t0 = time.perf_counter()
    logger.info("save_words_to_file: out=%s records=%d", out_path, len(records))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("word\tfreq\tglen\n")
        for rec in records:
            word, freq, glen = rec
            out.write(f"{word}\t{freq}\t{glen}\n")
    dur_ms = int((time.perf_counter() - t0) * 1000)
    abs_path = os.path.abspath(out_path)
    logger.info("save_words_to_file: wrote=%d dur_ms=%d path=%s", len(records), dur_ms, abs_path)
    return abs_path

def save_words_to_sqlite(records, db_path, chunk=10000, journal="AUTO"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    cx = sqlite3.connect(db_path, timeout=60)
    try:
        try:
            # Helper to attempt setting journal mode without aborting the rest
            jm = ""
            def _set_journal(mode: str):
                nonlocal jm
                try:
                    v = (cx.execute(f"PRAGMA journal_mode={mode}").fetchone() or [""])[0]
                except Exception:
                    v = ""
                if v:
                    jm = v

            # Pragmas and journal mode selection
            cx.execute("PRAGMA busy_timeout=60000")

            want = (journal or "AUTO").upper()
            if want in ("WAL", "AUTO"):
                _set_journal("WAL")
            if want in ("TRUNCATE", "AUTO") and str(jm).lower() not in ("wal",):
                _set_journal("TRUNCATE")
            if want in ("DELETE", "AUTO") and str(jm).lower() not in ("wal", "truncate"):
                _set_journal("DELETE")
            if want == "OFF" and not jm:
                _set_journal("OFF")

            for stmt in ("PRAGMA synchronous=NORMAL",
                         "PRAGMA cache_size=-200000",
                         "PRAGMA temp_store=MEMORY"):
                try:
                    cx.execute(stmt)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("save_words_to_sqlite: PRAGMA setup non-fatal error: %s", e)

        logger.info("save_words_to_sqlite: journal_mode=%s chunk=%d", str(jm).lower(), int(chunk))

        cx.execute("""
            CREATE TABLE IF NOT EXISTS words (
                word TEXT PRIMARY KEY,
                freq INTEGER,
                glen INTEGER
            )
        """)
        sql = (
            "INSERT INTO words(word, freq, glen) VALUES (?,?,?) "
            "ON CONFLICT(word) DO UPDATE SET freq=excluded.freq, glen=excluded.glen"
        )
        CHUNK = int(chunk) if chunk and int(chunk) > 0 else 10000
        cur = cx.cursor()
        for i in range(0, len(records), CHUNK):
            batch = records[i:i+CHUNK]
            cur.executemany(sql, batch)
            # Commit per chunk to avoid giant -wal/journal files that can trigger disk I/O errors
            cx.commit()
    finally:
        cx.close()
    return os.path.abspath(db_path)

def build_arg_parser():
    ap = argparse.ArgumentParser(description="Load word index into a persistent store")
    ap.add_argument("mode", choices=["file", "sqlite", "postgres"], help="Output mode: file (TSV), sqlite, or postgres (database)")
    ap.add_argument("--pg_dsn", default=None, help="Postgres DSN (or use POSTGRES_DSN env var)")
    ap.add_argument("--pg_copy_threshold", type=int, default=50000, help="Rows threshold to use COPY")
    ap.add_argument("--files", nargs="*", help="Input word file(s); supports .gz. Default: profile.wordlist_path if none provided")
    ap.add_argument("--out", help="Output TSV file (only used in file mode)")
    ap.add_argument("--db_path", help="SQLite db path (only used in sqlite mode)")
    ap.add_argument("--db-chunk", type=int, default=10000, help="SQLite insert chunk size (default: 10000)")
    ap.add_argument("--db-journal", choices=["AUTO", "WAL", "TRUNCATE", "DELETE", "OFF"], default="AUTO",
                    help="SQLite journal mode (default: AUTO with fallback)")
    ap.add_argument("--profile", default="default", help="Profile name")
    ap.add_argument("--base-dir", default=None, help="Base directory for profile (optional)")
    return ap

def main():
    ap = build_arg_parser()
    args = ap.parse_args()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    try:
        prof = Profile(name=args.profile, base_dir=args.base_dir)
        file_list = args.files if args.files else [prof.wordlist_path]
        logger.info("load_words start: mode=%s profile=%s base_dir=%s files=%d",
                    args.mode, args.profile, args.base_dir, len(file_list))
        logger.debug("input files: %s", file_list)
        t0 = time.perf_counter()
        records = aggregate_precomputed(file_list)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("aggregated %d unique words (precomputed merge) in %d ms", len(records), dur_ms)
        if args.mode == "file":
            out_file = args.out if args.out else os.path.join(os.path.dirname(prof.wordlist_path), "word-index-generated.tsv")
            path = save_words_to_file(records, out_file)
            print(f"Saved {len(records)} words to file: {path}")
        elif args.mode == "postgres":
            dsn = args.pg_dsn or os.environ.get("POSTGRES_DSN", "")
            save_words_to_postgres(records, dsn, copy_threshold=args.pg_copy_threshold)
            print(f"Loaded {len(records)} words into Postgres")
        elif args.mode == "sqlite":
            db_path = args.db_path if args.db_path else os.path.join(os.path.dirname(prof.wordlist_path), "words.db")
            path = save_words_to_sqlite(records, db_path, chunk=args.db_chunk, journal=args.db_journal)
            print(f"Loaded {len(records)} words into SQLite db: {path}")
    except Exception:
        logger.exception("load_words failed")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
