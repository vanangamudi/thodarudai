#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: word_indexer
Provides common functions to load a word list and query it.
"""

import os
import re

class WordIndex:
    def __init__(self, wordlist_path):
        self.wordlist_path = wordlist_path
        self.words = []          # list of tuples: (word, freq, glen)
        self._load_wordlist()

    def _load_wordlist(self):
        words = []
        print('loading word list...')
        with open(self.wordlist_path, "r", encoding="utf-8") as f:
            # Read the header line which we assume is "word\tfreq\tglen"
            header = f.readline().strip().split("\t")
            idx = {h: i for i, h in enumerate(header)}
            for line in f:
                if not line.strip():
                    continue
                cols = line.rstrip("\n").split("\t")
                try:
                    word = cols[idx["word"]]
                    freq = int(cols[idx["freq"]])
                    glen = int(cols[idx["glen"]])
                    words.append((word, freq, glen))
                except Exception:
                    continue
        self.words = words
        # Sort in descending order by glen, then freq, then ascending word.
        self.words.sort(key=lambda x: (-x[2], -x[1], x[0]))
        print('loading word list... DONE')

    def query_words(self, prefix="", suffix="", min_len=1, max_len=None, limit=200, offset=0, exclude_fn=None, regex=""):
        """
        Returns a list of (word, freq, glen) tuples matching the query parameters.
        - prefix: required starting substring.
        - suffix: required ending substring.
        - min_len: minimum grapheme length.
        - max_len: if provided, maximum grapheme length (inclusive).
        - limit: maximum number of results.
        - offset: skip the first offset matches.
        - exclude_fn: a function accepting a word and returning True if it should be skipped.
        - regex: if provided, a regex pattern that the word must match.
        """
        results = []
        seen = 0
        compiled_rx = None
        if regex:
            try:
                compiled_rx = re.compile(regex)
            except re.error:
                compiled_rx = None
        for word, freq, glen in self.words:
            # Filter by length.
            if glen < min_len:
                continue
            if max_len is not None and glen > max_len:
                continue
            if prefix and not word.startswith(prefix):
                continue
            if suffix and not word.endswith(suffix):
                continue
            if compiled_rx and not compiled_rx.search(word):
                continue
            if exclude_fn and exclude_fn(word):
                continue
            if seen >= offset:
                results.append((word, freq, glen))
                if len(results) >= limit:
                    break
            seen += 1
        return results
