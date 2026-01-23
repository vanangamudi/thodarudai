#!/usr/bin/env python3
import sys, collections, unicodedata
try:
    import regex as re
except ImportError:
    sys.stderr.write("Please install the 'regex' package: pip install regex\n")
    sys.exit(1)

TAMIL = re.compile(r"\p{Tamil}+")
def norm(s): return unicodedata.normalize("NFC", s)
def glen(s): return len(re.findall(r"\X", s))  # grapheme clusters

def main(paths):
    cnt = collections.Counter()
    for p in paths:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                for m in TAMIL.finditer(line):
                    cnt[norm(m.group(0))] += 1
    out = sys.stdout
    print("word\tfreq\tglen", file=out)
    for w, n in cnt.items():
        print(f"{w}\t{n}\t{glen(w)}", file=out)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tools.build_wordlist <files...>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1:])
