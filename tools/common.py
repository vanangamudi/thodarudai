#!/usr/bin/env python3
import gzip
import arichuvadi as ari
from collections import Counter
import time
import logging
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
