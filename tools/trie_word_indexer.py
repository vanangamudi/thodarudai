#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trie-backed word indexer using chorkilai's mmap OnDiskTrie.
Builds and queries forward and reverse tries for fast prefix/suffix lookup.
"""

import os
import re
import argparse
from typing import List, Tuple, Dict, Iterable

import arichuvadi as ari
from chorkilai.trie import OnDiskTrie

RankRec = Tuple[str, int, int]  # (word, freq, glen)

def _rank_key(rec: RankRec):
    # Canonical: (-glen, -freq, word)
    return (-rec[2], -rec[1], rec[0])

def _load_word_meta(wordlist_path: str) -> Dict[str, Tuple[int,int]]:
    """Load word -> (freq,glen) from word-index.tsv"""
    meta = {}
    with open(wordlist_path, "r", encoding="utf-8") as f:
        hdr = f.readline().strip().split("\t")
        idx = {h: i for i, h in enumerate(hdr)}
        for ln in f:
            if not ln.strip():
                continue
            c = ln.rstrip("\n").split("\t")
            try:
                w = c[idx["word"]]
                fr = int(c[idx["freq"]])
                gl = int(c[idx["glen"]])
            except Exception:
                continue
            meta[w] = (fr, gl)
    return meta

def _letters(s: str) -> List[str]:
    """Tamil grapheme sequence using arichuvadi coding (list of tokens)."""
    return list(ari.get_letters_coding(s))

def _concat_letters(tokens: Iterable[str]) -> str:
    return "".join(tokens)

class TrieWordIndex:
    def __init__(self, wordlist_path: str, fwd_db_path: str, rev_db_path: str):
        """
        wordlist_path: path to word-index.tsv (for freq/glen metadata)
        fwd_db_path: mmap trie file built from forward letter sequences
        rev_db_path: mmap trie file built from reversed letter sequences
        """
        self.wordlist_path = wordlist_path
        self.meta = _load_word_meta(wordlist_path)
        # Open existing tries (built via --build)
        self.fwd = OnDiskTrie(fwd_db_path, new=False)
        self.rev = OnDiskTrie(rev_db_path, new=False)

    def close(self):
        try:
            self.fwd.close()
        finally:
            self.rev.close()

    def _node_from_prefix(self, trie: OnDiskTrie, prefix_tokens: List[str]):
        # Use internal reader; find_prefix returns node or default=None
        return trie.find_prefix(prefix_tokens, default=None)

    def _collect_suffix_tokens(self, trie: OnDiskTrie, node_dict) -> List[List[str]]:
        """
        Recursively collect suffix token-lists starting at node_dict.
        Avoids string concatenation so we can reverse by tokens when needed.
        """
        if node_dict is None:
            return []
        out = []
        if node_dict.get("is_terminal", 0):
            out.append([])  # empty suffix at terminal
        for rec in node_dict.get("children", []):
            key = rec["key"]
            child_off = rec["child_ptr"]
            child_node = trie._read_node(child_off)
            child_suffs = self._collect_suffix_tokens(trie, child_node)
            for s in child_suffs:
                out.append([key] + s)
        return out

    def _candidates_prefix(self, prefix: str) -> List[str]:
        toks = _letters(prefix)
        node = self._node_from_prefix(self.fwd, toks)
        suffs = self._collect_suffix_tokens(self.fwd, node)
        pre = _concat_letters(toks)
        return [pre + _concat_letters(s) for s in suffs]

    def _candidates_suffix(self, suffix: str) -> List[str]:
        toks = _letters(suffix)
        rev_toks = list(reversed(toks))
        node = self._node_from_prefix(self.rev, rev_toks)
        suffs_rev = self._collect_suffix_tokens(self.rev, node)  # lists of tokens in reversed space
        # reconstruct reversed full tokens and flip back by tokens
        out = []
        for srev in suffs_rev:
            full_rev = rev_toks + srev
            full = list(reversed(full_rev))  # reverse token order
            out.append(_concat_letters(full))
        return out

    def query_words(self, prefix: str = "", suffix: str = "", min_len: int = 1, max_len=None,
                    limit: int = 200, offset: int = 0, exclude_fn=None, regex: str = "") -> List[RankRec]:
        """
        Returns [(word,freq,glen), ...] honoring filters and canonical ordering.
        """
        # Build a candidate pool from tries
        cand_set = None
        if prefix:
            cand_set = set(self._candidates_prefix(prefix))
        if suffix:
            suff_cands = set(self._candidates_suffix(suffix))
            cand_set = suff_cands if cand_set is None else (cand_set & suff_cands)
        if cand_set is None:
            # No prefix/suffix; fall back to all known words in metadata
            cand_iter = self.meta.keys()
        else:
            cand_iter = cand_set

        # Optional regex
        compiled_rx = None
        if regex:
            try:
                compiled_rx = re.compile(regex)
            except re.error:
                compiled_rx = None

        # Stream filter + collect with meta
        out = []
        need = (offset + limit) if limit is not None else None
        for w in cand_iter:
            fr_gl = self.meta.get(w)
            if not fr_gl:
                continue
            fr, gl = fr_gl
            if gl < min_len:
                continue
            if max_len is not None and gl > max_len:
                continue
            if prefix and not w.startswith(prefix):
                continue
            if suffix and not w.endswith(suffix):
                continue
            if compiled_rx and not compiled_rx.search(w):
                continue
            if exclude_fn and exclude_fn(w):
                continue
            out.append((w, fr, gl))
            if need is not None and len(out) >= need:
                # note: we still sort below; early stop reduces memory
                break

        # Canonical order and slice
        out.sort(key=_rank_key)
        if offset:
            out = out[offset:]
        if limit is not None and len(out) > limit:
            out = out[:limit]
        return out

def build_tries(wordlist_path: str, fwd_db_path: str, rev_db_path: str, overwrite: bool = False):
    """
    Build forward and reverse tries from word-index.tsv.
    Forward trie stores letter sequences; reverse trie stores reversed sequences.
    """
    # Create fwd and rev tries
    fwd = OnDiskTrie(fwd_db_path, new=True if overwrite or not os.path.exists(fwd_db_path) else False)
    rev = OnDiskTrie(rev_db_path, new=True if overwrite or not os.path.exists(rev_db_path) else False)

    # If not overwriting but files exist, we still want a clean store:
    if not overwrite and (os.path.exists(fwd_db_path) or os.path.exists(rev_db_path)):
        # Re-create fresh
        fwd = OnDiskTrie(fwd_db_path, new=True)
        rev = OnDiskTrie(rev_db_path, new=True)

    # Populate from word-index
    with open(wordlist_path, "r", encoding="utf-8") as f:
        hdr = f.readline().strip().split("\t")
        idx = {h: i for i, h in enumerate(hdr)}
        for ln in f:
            if not ln.strip():
                continue
            c = ln.rstrip("\n").split("\t")
            try:
                w = c[idx["word"]]
            except Exception:
                continue
            lt = _letters(w)
            if not lt:
                continue
            # forward
            fwd.add(lt)
            # reverse
            rev.add(list(reversed(lt)))
    fwd.close(); rev.close()

def main():
    ap = argparse.ArgumentParser(description="Trie-backed word indexer")
    ap.add_argument("--build", action="store_true", help="Build tries from word-index.tsv")
    ap.add_argument("--wordlist", required=True, help="Path to word-index.tsv")
    ap.add_argument("--fwd", required=True, help="Path to forward trie db file")
    ap.add_argument("--rev", required=True, help="Path to reverse trie db file")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing trie files when building")
    ap.add_argument("--query_prefix", default="", help="Test query: prefix")
    ap.add_argument("--query_suffix", default="", help="Test query: suffix")
    ap.add_argument("--min_len", type=int, default=1)
    ap.add_argument("--max_len", type=int, default=None)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    if args.build:
        build_tries(args.wordlist, args.fwd, args.rev, overwrite=args.overwrite)
        print("Built tries:", args.fwd, args.rev)
        return

    idx = TrieWordIndex(args.wordlist, args.fwd, args.rev)
    try:
        rows = idx.query_words(prefix=args.query_prefix, suffix=args.query_suffix,
                               min_len=args.min_len, max_len=args.max_len, limit=args.limit)
        for w, fr, gl in rows:
            print(f"{w}\t{fr}\t{gl}")
    finally:
        idx.close()

if __name__ == "__main__":
    main()
