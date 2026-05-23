#!/usr/bin/env python3
import gzip
import arichuvadi as ari
from collections import Counter

def openfile(filepath, mode='rt', *args, **kwargs):
    if filepath.endswith('.gz'):
        return gzip.open(filepath, mode, *args, **kwargs)
    return open(filepath, mode, *args, **kwargs)

def count_words(filepaths):
    cnt = Counter()
    for fp in filepaths:
        with openfile(fp) as f:
            for i, line in enumerate(f):
                if i == 0 and line.lower().startswith('word'):
                    continue
                cols = line.strip().split('\t')
                if not cols:
                    continue
                word = cols[0]
                try:
                    fr = int(cols[1])
                except Exception:
                    fr = 1
                cnt[word] += fr
    records = [(w, n, ari.length(w)) for w, n in cnt.items()]
    records.sort(key=lambda x: (-x[2], -x[1], x[0]))
    return records
