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

import sys, os, gzip, sqlite3, time
from collections import Counter
import argparse
import arichuvadi as ari
from tools.profile import Profile, default_profile

# Reuse the openfile helper from build_word_index.py:
def openfile(filepath, mode='rt', *args, **kwargs):
    if filepath.endswith('.gz'):
        return gzip.open(filepath, mode, *args, **kwargs)
    else:
        return open(filepath, mode, *args, **kwargs)

def count_words(filepaths):
    """Pure function that returns a list of tuples (word, freq, glen) from the given files."""
    cnt = Counter()
    # If no files are provided, use the default profile wordlist.
    if not filepaths:
        prof = default_profile
        filepaths = [prof.wordlist_path]
    for fp in filepaths:
        with openfile(fp) as f:
            for i, line in enumerate(f):
                if i == 0 and line.lower().startswith("word"):
                    continue
                cols = line.strip().split("\t")
                if not cols:
                    continue
                word = cols[0]
                try:
                    fr = int(cols[1])
                except Exception:
                    fr = 1
                cnt[word] += fr
    # Build list of records (word, frequency, grapheme length)
    records = [(w, freq, ari.length(w)) for w, freq in cnt.items()]
    # Optionally sort by criteria (e.g. descending glen, descending freq, ascending word)
    records.sort(key=lambda x: (-x[2], -x[1], x[0]))
    return records

# For file-backed output
def save_words_to_file(records, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        out.write("word\tfreq\tglen\n")
        for rec in records:
            word, freq, glen = rec
            out.write(f"{word}\t{freq}\t{glen}\n")
    return os.path.abspath(out_path)

# For SQLite-backed output; we create a table "words" if it does not exist.
def save_words_to_sqlite(records, db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    cx = sqlite3.connect(db_path)
    try:
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA synchronous=NORMAL")
        cx.execute("""
            CREATE TABLE IF NOT EXISTS words (
                word TEXT PRIMARY KEY,
                freq INTEGER,
                glen INTEGER
            )
        """)
        # Insert or update records (update frequency if word already exists)
        for word, freq, glen in records:
            cx.execute(
                "INSERT INTO words(word, freq, glen) VALUES (?,?,?) "
                "ON CONFLICT(word) DO UPDATE SET freq=excluded.freq, glen=excluded.glen",
                (word, freq, glen)
            )
        cx.commit()
    finally:
        cx.close()
    return os.path.abspath(db_path)

def build_arg_parser():
    ap = argparse.ArgumentParser(description="Load word index into a persistent store")
    ap.add_argument("mode", choices=["file", "sqlite"], help="Output mode: file (TSV) or sqlite (database)")
    ap.add_argument("--files", nargs="*", help="Input word file(s); supports .gz. Default: profile.wordlist_path if none provided")
    ap.add_argument("--out", help="Output TSV file (only used in file mode)")
    ap.add_argument("--db_path", help="SQLite db path (only used in sqlite mode)")
    ap.add_argument("--profile", default="default", help="Profile name")
    ap.add_argument("--base_dir", default=None, help="Base directory for profile (optional)")
    return ap

def main():
    ap = build_arg_parser()
    args = ap.parse_args()
    # Use profile for defaults if no files provided
    prof = Profile(name=args.profile, base_dir=args.base_dir)
    file_list = args.files if args.files else [prof.wordlist_path]
    records = count_words(file_list)
    if args.mode == "file":
        out_file = args.out if args.out else os.path.join(os.path.dirname(prof.wordlist_path), "word-index-generated.tsv")
        path = save_words_to_file(records, out_file)
        print(f"Saved {len(records)} words to file: {path}")
    else:
        db_path = args.db_path if args.db_path else os.path.join(os.path.dirname(prof.wordlist_path), "words.db")
        path = save_words_to_sqlite(records, db_path)
        print(f"Loaded {len(records)} words into SQLite db: {path}")

if __name__ == "__main__":
    main()
