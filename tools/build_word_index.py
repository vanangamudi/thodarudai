#!/usr/bin/env python3
"""Build Word Index Tool

This script builds a searchable word index TSV file from one or more input word files.  If no input files are provided, it uses the default profile's word list based on the specified profile name and base directory. Each input file is expected to be a TSV with at least the columns: word, freq, glen The script reads each file (supporting plain text or gzipped files), updates a frequency count for each word, and outputs a new TSV with the header

word  freq  glen

Grapheme length (glen) is computed via the 'arichuvadi.length()' function provided by the arichuvadi package.

"""
import sys
import gzip
from collections import Counter
import arichuvadi as ari
from tools.profile import Profile, default_profile

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

def openfile(filepath, mode='rt', *args, **kwargs):
    if filepath.endswith('.gz'):
        return gzip.open(filepath, mode, *args, **kwargs)
    else:
        return open(filepath, mode, *args, **kwargs)

def main():
    from collections import Counter
    import sys
    import arichuvadi as ari
    from tools.profile import Profile, default_profile
    ap = build_arg_parser()
    args = ap.parse_args()
    # Create a profile with given profile name and base_dir.
    prof = Profile(name=args.profile, base_dir=args.base_dir)
    files = args.files if args.files else [prof.wordlist_path]
    cnt = Counter()
    for p in files:
        with openfile(p) as f:
            for i, line in enumerate(f):
                # Skip header if the first line starts with "word"
                if i == 0 and line.startswith("word"):
                    continue
                cols = line.strip().split("\t")
                word = cols[0]
                try:
                    fr = int(cols[1])
                except Exception:
                    fr = 1
                cnt[word] += fr

    out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    print("word\tfreq\tglen", file=out_stream)
    for w, n in cnt.items():
        # Use the arichuvadi function to get grapheme length
        print(f"{w}\t{n}\t{ari.length(w)}", file=out_stream)
    if args.out:
        out_stream.close()

if __name__ == "__main__":
    main()
