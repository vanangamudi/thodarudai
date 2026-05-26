#!/usr/bin/env python3
import gzip
import arichuvadi as ari
from collections import Counter
import time
import logging
from typing import Tuple, Dict, Iterable
import unicodedata as _ud
logger = logging.getLogger("common")
_GLEN_FALLBACK_WARNED = False

def grapheme_length(s):
    global _GLEN_FALLBACK_WARNED
    try:
        # Prefer ari.length if present
        return ari.length(s)  # may not exist in some builds
    except Exception:
        try:
            # Fallback: count grapheme tokens
            if not _GLEN_FALLBACK_WARNED:
                logger.warning("grapheme_length: ari.length() unavailable; using get_letters_coding() fallback")
                _GLEN_FALLBACK_WARNED = True
            return len(list(ari.get_letters_coding(s)))
        except Exception:
            # Last resort: codepoint length
            logger.debug("grapheme_length: falling back to codepoint length for %r", s)
            return len(s)

def sanitize_word(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\x00", "").replace("\r", "").replace("\n", "")
    out = []
    for ch in s:
        cat = _ud.category(ch)
        # Keep format chars (Cf: e.g. ZWJ/ZWNJ); drop other control/surrogate/private/unassigned
        if cat.startswith("C") and cat != "Cf":
            continue
        if ch == "\u200B":  # zero width space: drop
            continue
        out.append(ch)
    s = "".join(out)
    s = s.replace("\u00A0", " ").strip()
    return s


def openfile(filepath, mode='rt', *args, **kwargs):
    if filepath.endswith('.gz'):
        logger.debug("openfile: gz %s", filepath)
        return gzip.open(filepath, mode, *args, **kwargs)
    logger.debug("openfile: plain %s", filepath)
    return open(filepath, mode, *args, **kwargs)

def count_words(filepaths):
    t0 = time.perf_counter()
    logger.info("count_words: start files=%d", len(filepaths))
    logger.debug("count_words: inputs=%s", filepaths)
    cnt = Counter()
    for fp in filepaths:
        logger.info("count_words: reading %s", fp)
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
    records = [(w, n, grapheme_length(w)) for w, n in cnt.items()]
    records.sort(key=lambda x: (-x[2], -x[1], x[0]))
    dur_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("count_words: aggregated=%d dur_ms=%d", len(records), dur_ms)
    return records

def iter_word_freq_glen_from_tsv(path: str):
    with openfile(path, "rt", encoding="utf-8") as f:
        hdr = ["word", "freq", "glen"]
        idx = {h: i for i, h in enumerate(hdr)}
        for ln in f:
            if not ln.strip():
                continue
            c = ln.rstrip("\n").split("\t")
            w = sanitize_word(c[idx["word"]] if len(c) > idx["word"] else "")
            if not w:
                continue
            try:
                fr = int(c[idx["freq"]])
            except Exception:
                continue
            gl = grapheme_length(w)
            yield w, fr, gl

def aggregate_precomputed(files: Iterable[str]):
    acc: Dict[str, Tuple[int, int]] = {}
    for p in files:
        logger.info("aggregate: reading %s", p)
        for w, fr, gl in iter_word_freq_glen_from_tsv(p):
            if w in acc:
                old_fr, old_gl = acc[w]
                if old_gl != gl:
                    logger.debug("aggregate: glen mismatch for %r: have=%d got=%d; keeping existing", w, old_gl, gl)
                acc[w] = (old_fr + fr, old_gl)
            else:
                acc[w] = (fr, gl)
    out = [(w, fr, gl) for w, (fr, gl) in acc.items()]
    out.sort(key=lambda x: (x[2], -x[1], x[0]))
    return out
