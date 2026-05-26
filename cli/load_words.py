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
from backend.core.profile import Profile
from backend.core.common import aggregate_precomputed
import logging
logger = logging.getLogger("load_words")

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
            from backend.storage.postgres import PostgresStorage
            dsn = args.pg_dsn or os.environ.get("POSTGRES_DSN", "")
            storage = PostgresStorage(dsn, profile=args.profile)
            CHUNK = max(1, int(args.db_chunk))
            for i in range(0, len(records), CHUNK):
                storage.ensure_words(records[i:i+CHUNK])
            print(f"Loaded {len(records)} words into Postgres")
        elif args.mode == "sqlite":
            from backend.storage.sqlite import SqliteStorage
            db_path = args.db_path if args.db_path else os.path.join(os.path.dirname(prof.wordlist_path), "words.db")
            storage = SqliteStorage(db_path, profile=args.profile)
            CHUNK = max(1, int(args.db_chunk))
            for i in range(0, len(records), CHUNK):
                storage.ensure_words(records[i:i+CHUNK])
            print(f"Loaded {len(records)} words into SQLite db: {os.path.abspath(db_path)}")
    except Exception:
        logger.exception("load_words failed")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
