#!/usr/bin/env python3
import argparse
import os, time
from backend.core.profile import Profile
from backend.storage import FileStorage, SqliteStorage, PostgresStorage

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--base_dir", default=None, help="Base directory for profile")
    ap.add_argument("--out", default=None, help="Optional explicit output path")
    ap.add_argument("--storage", choices=["fs","sqlite","postgres"], default=os.environ.get("STORAGE_BACKEND","fs"))
    ap.add_argument("--sqlite_path", default=os.environ.get("SQLITE_PATH", None))
    ap.add_argument("--pg_dsn", default=os.environ.get("POSTGRES_DSN", ""))
    args = ap.parse_args()
    p = Profile(name=args.profile, base_dir=args.base_dir)
    if args.storage == "sqlite":
        dbp = args.sqlite_path or os.path.join(os.path.dirname(os.path.abspath(p.wordlist_path)), "curation.db")
        storage = SqliteStorage(dbp, profile=p.name)
    elif args.storage == "postgres":
        if not args.pg_dsn:
            raise SystemExit("POSTGRES_DSN or --pg_dsn is required for postgres storage")
        storage = PostgresStorage(args.pg_dsn, profile=p.name)
    else:
        storage = FileStorage(p.batches_dir, p.ledger_path, p.reminders_path)
    pairs = storage.get_latest_splits()
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    out_dir = p.datasets_dir
    os.makedirs(out_dir, exist_ok=True)
    out_path = args.out or os.path.join(out_dir, f"tokenizer-{ts}.tsv")
    with open(out_path, "w", encoding="utf-8") as o:
        print("src\ttgt", file=o)
        for w in sorted(pairs.keys()):
            print(f"{w}\t{pairs[w]}", file=o)
    print(f"Wrote dataset with {len(pairs)} pairs to {out_path}")
    return out_path

if __name__ == "__main__":
    main()
