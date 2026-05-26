#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: word_indexer
Provides common functions to load a word list and query it.
"""

import os
import re
from bisect import bisect_left, bisect_right
import heapq
import logging
import time
from tools.common import sanitize_word, grapheme_length
logger = logging.getLogger("word_indexer")

class WordIndex:
    def __init__(self, wordlist_path):
        self.wordlist_path = wordlist_path
        logger.info("WordIndex: init path=%s", self.wordlist_path)
        self.words = []          # list of tuples: (word, freq, glen)
        self._load_wordlist()
        self._build_indices()
        self._regex_cache = {}

    def _compile_regex(self, pattern):
        if not pattern:
            return None
        try:
            rx = re.compile(pattern)
            logger.debug("WordIndex: compiled regex ok pattern=%r", pattern)
            return rx
        except re.error as e:
            logger.warning("WordIndex: invalid regex pattern=%r err=%s", pattern, e)
            return None

    def _select_candidates(self, prefix, suffix, min_len, max_len):
        if prefix:
            return self._candidates_from_prefix(prefix, min_len, max_len)
        if suffix:
            return self._candidates_from_suffix(suffix, min_len, max_len)
        total = len(self.words)
        if max_len is not None or min_len > 1:
            est = sum(self.len_counts.get(gl, 0) for gl in self.len_counts
                      if gl >= min_len and (max_len is None or gl <= max_len))
            if est and est < total:
                return self._candidates_from_lengths(min_len, max_len)
        return self.words

    def _passes_filters(self, rec, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn):
        w, fr, gl = rec
        if gl < min_len:
            return False
        if max_len is not None and gl > max_len:
            return False
        if prefix and not w.startswith(prefix):
            return False
        if suffix and not w.endswith(suffix):
            return False
        if compiled_rx and not compiled_rx.search(w):
            return False
        if exclude_fn and exclude_fn(w):
            return False
        return True

    def _filter_candidates(self, candidates, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn):
        """Apply remaining filters on candidate records."""
        return [
            rec for rec in candidates
            if self._passes_filters(rec, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn)
        ]

    def _finalize_results(self, filtered, offset, limit):
        """Sort canonically, then apply offset/limit and return."""
        filtered.sort(key=self._rank_key)
        if offset:
            filtered = filtered[offset:]
        if limit is not None and len(filtered) > limit:
            filtered = filtered[:limit]
        return filtered

    def _load_wordlist(self):
        t0 = time.perf_counter()
        words = []
        logger.info("WordIndex: loading word list from %s", self.wordlist_path)
        with open(self.wordlist_path, "r", encoding="utf-8") as f:
            # Read the header line which we assume is "word\tfreq\tglen"
            header = f.readline().strip().split("\t")
            idx = {h: i for i, h in enumerate(header)}
            for line in f:
                if not line.strip():
                    continue
                cols = line.rstrip("\n").split("\t")
                try:
                    word = sanitize_word(cols[idx["word"]])
                    if not word:
                        continue
                    freq = int(cols[idx["freq"]])
                    glen = grapheme_length(word)
                    words.append((word, freq, glen))
                except Exception:
                    continue
        self.words = words
        # Sort in descending order by glen, then freq, then ascending word.
        self.words.sort(key=lambda x: (-x[2], -x[1], x[0]))
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("WordIndex: loaded %d words in %d ms", len(self.words), dur_ms)

    def _build_indices(self):
        t0 = time.perf_counter()
        # Alphabetical index for fast prefix range scans
        self.by_word = sorted(self.words, key=lambda x: x[0])
        self._words_only = [w for (w, _, _) in self.by_word]
        # Reversed-word index for fast suffix range scans
        self.by_rev = sorted([(w[::-1], w, fr, gl) for (w, fr, gl) in self.words], key=lambda x: x[0])
        self._revs_only = [rev for (rev, _, _, _) in self.by_rev]
        # Length ranges over self.words (sorted by -glen, -freq, word)
        self.len_ranges = {}  # glen -> (start_idx, end_exclusive)
        self.len_counts = {}
        start = 0
        n = len(self.words)
        while start < n:
            gl = self.words[start][2]
            end = start + 1
            while end < n and self.words[end][2] == gl:
                end += 1
            self.len_ranges[gl] = (start, end)
            self.len_counts[gl] = end - start
            start = end
        self.order_index = {w: i for i, (w, _, _) in enumerate(self.words)}
        # Precompute word -> glen and the set of words for O(1) access in summaries
        self.glen_map = {w: gl for (w, _, gl) in self.words}
        self.index_words = set(self.glen_map.keys())
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("WordIndex: indices built in %d ms (by_word=%d, by_rev=%d, len_counts=%d distinct)",
                    dur_ms, len(self.by_word), len(self.by_rev), len(self.len_counts))
    
    def _prefix_bounds(self, prefix):
        lo = bisect_left(self._words_only, prefix)
        hi = bisect_right(self._words_only, prefix + "\uffff")
        return lo, hi

    def _suffix_bounds(self, suffix):
        needle = suffix[::-1]
        lo = bisect_left(self._revs_only, needle)
        hi = bisect_right(self._revs_only, needle + "\uffff")
        return lo, hi

    def _rank_key(self, rec):
        # Keep canonical ordering consistent with original: (-glen, -freq, word)
        return (-rec[2], -rec[1], rec[0])

    def _candidates_from_prefix(self, prefix, min_len, max_len):
        lo, hi = self._prefix_bounds(prefix)
        out = []
        for w, fr, gl in self.by_word[lo:hi]:
            if gl < min_len: continue
            if max_len is not None and gl > max_len: continue
            out.append((w, fr, gl))
        return out

    def _candidates_from_suffix(self, suffix, min_len, max_len):
        lo, hi = self._suffix_bounds(suffix)
        out = []
        for rev, w, fr, gl in self.by_rev[lo:hi]:
            if gl < min_len: continue
            if max_len is not None and gl > max_len: continue
            out.append((w, fr, gl))
        return out

    def _candidates_from_lengths(self, min_len, max_len):
        out = []
        # Iterate by descending glen to match canonical ordering
        for gl in sorted(self.len_ranges.keys(), reverse=True):
            if gl < min_len:
                continue
            if max_len is not None and gl > max_len:
                continue
            start, end = self.len_ranges[gl]
            out.extend(self.words[start:end])
        return out

    def query_words(self, prefix="", suffix="", min_len=1, max_len=None, limit=200, offset=0, exclude_fn=None, regex=""):
        compiled_rx = self._compile_regex(regex)
        t0 = time.perf_counter()
        candidates = self._select_candidates(prefix, suffix, min_len, max_len)
        cand_n = len(candidates) if isinstance(candidates, list) else len(self.words)
        filtered = self._filter_candidates(candidates, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn)
        rows = self._finalize_results(filtered, offset, limit)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "WordIndex.query prefix=%r suffix=%r regex=%r min_len=%s max_len=%s limit=%s cand=%d out=%d dur_ms=%d",
            prefix, suffix, (regex or ""), min_len, max_len, limit, cand_n, len(rows), dur_ms
        )
        return rows
