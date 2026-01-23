#!/usr/bin/env python3
import sys
import gzip
from collections import Counter
import arichuvadi as ari

def openfile(filepath, mode='rt', *args, **kwargs):
    if filepath.endswith('.gz'):
        return gzip.open(filepath, mode, *args, **kwargs)
    else:
        return open(filepath, mode, *args, **kwargs)

def main(paths):
    cnt = Counter()
    for p in paths:
        with openfile(p) as f:
            for i, line in enumerate(f):
                # Skip header line if present
                if i == 0 and line.startswith("word"):
                    continue
                cols = line.strip().split("\t")
                if len(cols) < 2:
                    continue
                word = cols[0]
                try:
                    fr = int(cols[1])
                except ValueError:
                    continue
                cnt[word] += fr
    out = sys.stdout
    print("word\tfreq\tglen", file=out)
    for w, n in cnt.items():
        print(f"{w}\t{n}\t{ari.length(w)}", file=out)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tools.build_wordlist <files...>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1:])
