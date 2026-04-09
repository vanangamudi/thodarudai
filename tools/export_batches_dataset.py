#!/usr/bin/env python3
import argparse, os, time, sys
from tools.profile import Profile

REQ_COLS = {"word","splits"}

def scan_batches(batches_dir):
    items = []  # list of (mtime, path)
    try:
        for name in os.listdir(batches_dir):
            if name.lower().endswith(".tsv"):
                p = os.path.join(batches_dir, name)
                try:
                    st = os.stat(p)
                    items.append((st.st_mtime, p))
                except OSError:
                    continue
    except FileNotFoundError:
        pass
    # sort by mtime ascending so last occurrence wins during overwrite
    return [p for _, p in sorted(items, key=lambda x: x[0])]

def build_dataset(batches_dir):
    data = {}  # word -> splits (last occurrence wins)
    for path in scan_batches(batches_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                hdr = f.readline().strip().split("\t")
                idx = {h: i for i, h in enumerate(hdr)}
                if not REQ_COLS.issubset(idx):
                    continue
                for ln in f:
                    if not ln.strip():
                        continue
                    cols = ln.rstrip("\n").split("\t")
                    w = cols[idx["word"]]
                    s = cols[idx["splits"]]
                    if w and s:
                        data[w] = s
        except (OSError, UnicodeDecodeError):
            continue
    return data

def export_dataset(profile: Profile, out_path=None):
    data = build_dataset(profile.batches_dir)
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    out_dir = profile.datasets_dir
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_path or os.path.join(out_dir, f"tokenizer-{ts}.tsv")
    with open(out_path, "w", encoding="utf-8") as o:
        print("src\ttgt", file=o)
        for w, s in sorted(data.items()):
            print(f"{w}\t{s}", file=o)
    print(f"Wrote dataset with {len(data)} pairs to {out_path}")
    return out_path

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--base_dir", default=None)
    ap.add_argument("--out", default=None, help="Optional explicit output path")
    args = ap.parse_args()
    p = Profile(name=args.profile, base_dir=args.base_dir)
    export_dataset(p, args.out)
