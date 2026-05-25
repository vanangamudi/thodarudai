#!/usr/bin/env python3
"""Build Word Index Tool

This script builds a word index TSV by merging precomputed TSVs with columns: word, freq, glen.
No raw text counting is performed.

"""
import sys
import logging
import time
logger = logging.getLogger("build_word_index")

from tools.profile import Profile
from tools.common import aggregate_precomputed

def build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(
        description="Build a word index TSV from input word files. If no files are provided, uses the default profile wordlist."
    )
    ap.add_argument("files", nargs="*", help="Input word file(s). Supports .gz")
    ap.add_argument("--out", help="Output file (default: stdout)")
    ap.add_argument("--profile", default="default", help="Profile name (default: 'default')")
    ap.add_argument("--base_dir", default=None, help="Base directory for the profile (optional)")
    return ap


def main():
    ap = build_arg_parser()
    args = ap.parse_args()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    try:
        # Create a profile with given profile name and base_dir.
        prof = Profile(name=args.profile, base_dir=args.base_dir)
        files = args.files if args.files else [prof.wordlist_path]
        logger.info("build_word_index start: profile=%s base_dir=%s out=%s files=%d",
                    args.profile, args.base_dir, (args.out or "(stdout)"), len(files))
        logger.debug("input files: %s", files)
        t0 = time.perf_counter()
        records = aggregate_precomputed(files)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("aggregated %d unique words in %d ms", len(records), dur_ms)

        out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
        logger.info("writing output to %s", (args.out or "stdout"))
        print("word\tfreq\tglen", file=out_stream)
        for w, n, g in records:
            print(f"{w}\t{n}\t{g}", file=out_stream)
        logger.info("wrote %d rows to %s", len(records), (args.out or "stdout"))
        if args.out:
            out_stream.close()

    except Exception as e:
        logger.exception("build_word_index failed")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
