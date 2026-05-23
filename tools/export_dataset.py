#!/usr/bin/env python3
import argparse
from tools.profile import Profile
from tools.export_batches_dataset import export_dataset as _export

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--base_dir", default=None)
    ap.add_argument("--out", default=None, help="Optional explicit output path")
    args = ap.parse_args()
    p = Profile(name=args.profile, base_dir=args.base_dir)
    _export(p, args.out)

if __name__ == "__main__":
    main()
