#!/usr/bin/env python3
import os
import sys
import glob
import gzip
import logging
from types import SimpleNamespace
from kkk.kiruvam import run_chorkkal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [kkk_wrapper] %(message)s")
log = logging.getLogger("kkk_wrapper")


class MultiFileLines:
    """Iterate lines across many files; supports .gz and .txt."""
    def __init__(self, paths, lower=False):
        self.paths = list(paths)
        self.lower = lower
        self._i = 0
        self._fh = None

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            if self._fh is None:
                if self._i >= len(self.paths):
                    raise StopIteration
                p = self.paths[self._i]; self._i += 1
                log.info("Reading: %s", p)
                if p.endswith(".gz"):
                    self._fh = gzip.open(p, "rt", encoding="utf-8")
                else:
                    self._fh = open(p, "rt", encoding="utf-8")
            line = self._fh.readline()
            if line:
                return line.lower() if self.lower else line
            # EOF; advance to next file
            self._fh.close()
            self._fh = None
            continue

def build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(description="Aggregate word frequencies across a corpus using kkk.kiruvam")
    ap.add_argument("--input_dir", default=os.path.expanduser("~/tharavu/cholloadai-2021.txt"),
                    help="Directory containing corpus parts (gz or txt)")
    ap.add_argument("--pattern", default="*.gz", help="Glob pattern to select files inside input_dir")
    ap.add_argument("--output", required=True, help="Output TSV path (word<TAB>count)")
    return ap

def main():
    args = build_arg_parser().parse_args()
    files = sorted(glob.glob(os.path.join(args.input_dir, args.pattern)))
    if not files:
        # fallback: include all regular files if pattern missed
        files = sorted([os.path.join(args.input_dir, n) for n in os.listdir(args.input_dir)
                        if os.path.isfile(os.path.join(args.input_dir, n))])
    if not files:
        raise SystemExit(f"No input files found under {args.input_dir} with pattern {args.pattern}")

    reader = MultiFileLines(files)
    ns = SimpleNamespace(
        input=reader,
        output=args.output,
        fields='word,count,glen',
        frequency=True
    )
    log.info("Starting aggregation: files=%d output=%s", len(files), args.output)
    run_chorkkal(ns)
    log.info("Done: wrote %s", args.output)

if __name__ == "__main__":
    main()
