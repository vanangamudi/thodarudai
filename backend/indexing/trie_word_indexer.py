#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trie Word Indexer Tool

Trie-backed word indexer using chorkilai's mmap OnDiskTrie.
Builds and queries forward and reverse tries for fast prefix/suffix lookup.

This script provides a trie-backed word indexing system using a memory-mapped OnDiskTrie.
It can either build tries (forward and reverse) from a word-index TSV file or query an existing trie-based index for candidate words based on specified prefix and/or suffix criteria. It supports optional parameters such as minimum/maximum grapheme length, progress bars, parallel building, and more. When building, it reads words from the wordlist (optionally applying grapheme length filters) and builds two tries: one for normal (forward) letter sequences and one for reversed sequences, to facilitate fast prefix and suffix lookup.
"""


import os
import re
from backend.core.profile import Profile
import argparse
from typing import List, Tuple, Dict, Iterable

from backend.core.common import sanitize_word, grapheme_length
import arichuvadi as ari
from chorkilai.trie import OnDiskTrie
import logging
import time
logger = logging.getLogger("trie_word_indexer")
from concurrent.futures import ProcessPoolExecutor, as_completed

def build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(description="Trie-backed word indexer using chorkilai's mmap OnDiskTrie. Builds and queries forward and reverse tries for fast prefix/suffix lookup.")
    ap.add_argument("--profile", default="default", help="Profile name")
    ap.add_argument("--base_dir", default=None, help="Optional base directory for profile")
    ap.add_argument("--build", action="store_true", help="Build tries from word-index.tsv")
    ap.add_argument("--wordlist", default=None, help="Path to word-index.tsv (default: profile.wordlist_path)")
    ap.add_argument("--fwd", default=None, help="Path to forward trie db file (default: <profile-dir>/fwd.trie)")
    ap.add_argument("--rev", default=None, help="Path to reverse trie db file (default: <profile-dir>/rev.trie)")
    ap.add_argument("--parallel", action="store_true", help="Build forward and reverse tries in parallel")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing trie files when building")
    ap.add_argument("--query_prefix", default="", help="Test query: prefix")
    ap.add_argument("--query_suffix", default="", help="Test query: suffix")
    ap.add_argument("--min_len", type=int, default=1)
    ap.add_argument("--max_len", type=int, default=None)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--pbar", action="store_true", help="Show progress bar while building")
    ap.add_argument("--min_glen", type=int, default=None, help="Only add words with grapheme length >= this")
    ap.add_argument("--max_glen", type=int, default=None, help="Only add words with grapheme length <= this")
    ap.add_argument("--sort_by_word", action="store_true", help="Pre-sort words lexicographically before building (uses memory)")
    return ap

RankRec = Tuple[str, int, int]  # (word, freq, glen)

def _rank_key(rec: RankRec):
    # Canonical: (-glen, -freq, word)
    return (-rec[2], -rec[1], rec[0])

def _parse_word_index_rows(wordlist_path):
    """Yield (word, freq, glen) rows from a word-index.tsv safely."""
    with open(wordlist_path, "r", encoding="utf-8") as f:
        hdr = f.readline().strip().split("\t")
        idx = {h: i for i, h in enumerate(hdr)}
        for ln in f:
            if not ln.strip():
                continue
            cols = ln.rstrip("\n").split("\t")
            try:
                w = sanitize_word(cols[idx["word"]])
                if not w:
                    continue
                fr = int(cols[idx["freq"]])
                gl = grapheme_length(w)
                yield (w, fr, gl)
            except Exception:
                continue

def _load_word_meta(wordlist_path: str) -> Dict[str, Tuple[int,int]]:
    """Load word -> (freq,glen) from word-index.tsv"""
    meta = {}
    for w, fr, gl in _parse_word_index_rows(wordlist_path):
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
        logger.info("TrieWordIndex: open fwd=%s rev=%s; meta=%d words",
                    fwd_db_path, rev_db_path, len(self.meta))
        # Expose metadata to match WordIndex
        self.words = sorted(((w, fr, gl) for w, (fr, gl) in self.meta.items()), key=lambda rec: (-rec[2], -rec[1], rec[0]))
        self.glen_map = {w: gl for w, (_, gl) in self.meta.items()}
        self.index_words = set(self.glen_map.keys())

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

    def _compile_regex(self, pattern: str):
        if not pattern:
            return None
        try:
            rx = re.compile(pattern)
            logger.debug("TrieWordIndex: compiled regex ok pattern=%r", pattern)
            return rx
        except re.error as e:
            logger.warning("TrieWordIndex: invalid regex pattern=%r err=%s", pattern, e)
            return None

    def _build_candidate_set(self, prefix: str, suffix: str):
        """
        Build candidate set from tries:
          - prefix only: all words under forward trie node
          - suffix only: all words under reverse trie node (reversed tokens)
          - both: intersection of the two sets
          - none: return None (means use all meta keys)
        """
        cand_set = None
        if prefix:
            cand_set = set(self._candidates_prefix(prefix))
        if suffix:
            suff = set(self._candidates_suffix(suffix))
            cand_set = suff if cand_set is None else (cand_set & suff)
        if prefix and suffix and cand_set is not None:
            logger.debug("TrieWordIndex: candidate set built (both) size=%d", len(cand_set))
        elif prefix and cand_set is not None:
            logger.debug("TrieWordIndex: candidate set built (prefix) size=%d", len(cand_set))
        elif suffix and cand_set is not None:
            logger.debug("TrieWordIndex: candidate set built (suffix) size=%d", len(cand_set))
        return cand_set

    def _iter_candidate_words(self, cand_set):
        """Iterator over candidate words (set or all known words)."""
        return cand_set if cand_set is not None else self.meta.keys()

    def _passes_filters(self, w: str, fr: int, gl: int,
                        prefix: str, suffix: str, compiled_rx, min_len, max_len, exclude_fn):
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

    def _collect_ranked(self, cand_iter, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn, need):
        """
        Stream-filter candidates using meta, collect up to 'need' items unsliced, then sort canonically.
        """
        out = []
        for w in cand_iter:
            meta = self.meta.get(w)
            if not meta:
                continue
            fr, gl = meta
            if not self._passes_filters(w, fr, gl, prefix, suffix, compiled_rx, min_len, max_len, exclude_fn):
                continue
            out.append((w, fr, gl))
            if need is not None and len(out) >= need:
                break
        out.sort(key=lambda rec: (-rec[2], -rec[1], rec[0]))
        return out

    def _finalize_slice(self, rows, offset, limit):
        if offset:
            rows = rows[offset:]
        if limit is not None and len(rows) > limit:
            rows = rows[:limit]
        return rows

    def query_words(self,
                    prefix: str = "", suffix: str = "",
                    min_len: int = 1, max_len=None,
                    limit: int = 200, offset: int = 0,
                    exclude_fn=None, regex: str = "") -> List[RankRec]:
        t0 = time.perf_counter()
        logger.info("TrieWordIndex.query prefix=%r suffix=%r regex=%r min_len=%s max_len=%s limit=%s offset=%s",
                    prefix, suffix, (regex or ""), min_len, max_len, limit, offset)
        compiled_rx = self._compile_regex(regex)
        cand_set = self._build_candidate_set(prefix, suffix)
        cand_iter = self._iter_candidate_words(cand_set)
        need = (offset + limit) if limit is not None else None
        out = self._collect_ranked(cand_iter, prefix, suffix,
                                   compiled_rx, min_len, max_len,
                                   exclude_fn, need)
        rows = self._finalize_slice(out, offset, limit)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("TrieWordIndex.query: out=%d dur_ms=%d", len(rows), dur_ms)
        return rows

def _open_or_reset_tries(fwd_db_path, rev_db_path, overwrite: bool):
    logger.info("Opening tries fwd=%s rev=%s overwrite=%s", fwd_db_path, rev_db_path, overwrite)
    """Open new or reset tries according to overwrite flag."""
    import os
    fwd = OnDiskTrie(fwd_db_path, new=(overwrite or not os.path.exists(fwd_db_path)))
    rev = OnDiskTrie(rev_db_path, new=(overwrite or not os.path.exists(rev_db_path)))
    # Speed up build: disable per-write flushes; larger initial capacity for new nodes
    try:
        fwd.store.flush_per_write = False
        rev.store.flush_per_write = False
    except Exception:
        pass
    try:
        fwd.INITIAL_NODE_CAPACITY = max(getattr(fwd, "INITIAL_NODE_CAPACITY", 10), 256)
        rev.INITIAL_NODE_CAPACITY = max(getattr(rev, "INITIAL_NODE_CAPACITY", 10), 256)
    except Exception:
        pass
    return fwd, rev

def _iter_wordlist_words(wordlist_path, min_glen=None, max_glen=None):
    """Yield words (optionally filtered by grapheme length) from word-index.tsv."""
    for w, fr, gl in _parse_word_index_rows(wordlist_path):
        if min_glen is not None and gl < min_glen:
            continue
        if max_glen is not None and gl > max_glen:
            continue
        yield w

def _populate_tries(fwd, rev, wordlist_path, pbar: bool, min_glen=None, max_glen=None, sort_by_word=False):
    count = 0
    it = _iter_wordlist_words(wordlist_path, min_glen=min_glen, max_glen=max_glen)
    # Optional pre-sort to improve prefix locality (uses memory)
    if sort_by_word:
        try:
            it = sorted(it)
        except Exception:
            pass
    if pbar:
        try:
            from tqdm import tqdm
            it = tqdm(it, desc="Building tries", unit="w")
        except Exception:
            pass
    for w in it:
        lt = _letters(w)
        if not lt:
            continue
        fwd.add(lt)
        rev.add(list(reversed(lt)))
        count += 1

def _populate_trie(trie, wordlist_path, pbar: bool, min_glen=None, max_glen=None, sort_by_word=False, reverse=False):
    count = 0
    it = _iter_wordlist_words(wordlist_path, min_glen=min_glen, max_glen=max_glen)
    # Optional pre-sort to improve prefix locality (uses memory)
    if sort_by_word:
        try:
            it = sorted(it)
        except Exception:
            pass
    if pbar:
        try:
            from tqdm import tqdm
            it = tqdm(it, desc=f"Building {'rev' if reverse else 'fwd'} trie", unit="w")
        except Exception:
            pass
    for w in it:
        lt = _letters(w)
        if not lt:
            continue
        if reverse:
            trie.add(list(reversed(lt)))
        else:
            trie.add(lt)
        count += 1

def _build_one_trie(args_tuple):
    """
    Worker to build a single trie file.
    args_tuple: (db_path, overwrite, wordlist_path, pbar, min_glen, max_glen, sort_by_word, reverse)
    """
    (db_path, overwrite, wordlist_path, pbar, min_glen, max_glen, sort_by_word, reverse) = args_tuple
    t0 = time.perf_counter()
    logger.info("Building trie db=%s reverse=%s overwrite=%s", db_path, reverse, overwrite)
    trie = OnDiskTrie(db_path, new=(overwrite or not os.path.exists(db_path)))
    # Speed up build: disable per-write flush
    try:
        trie.store.flush_per_write = False
    except Exception:
        pass
    try:
        trie.INITIAL_NODE_CAPACITY = max(getattr(trie, "INITIAL_NODE_CAPACITY", 10), 256)
    except Exception:
        pass
    try:
        _populate_trie(trie, wordlist_path, pbar=pbar,
                       min_glen=min_glen, max_glen=max_glen,
                       sort_by_word=sort_by_word, reverse=reverse)
    finally:
        trie.close()
    dur_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("Built trie db=%s dur_ms=%d", db_path, dur_ms)
    return db_path

def build_tries(wordlist_path: str, fwd_db_path: str, rev_db_path: str,
                overwrite: bool = False, pbar: bool = False,
                min_glen=None, max_glen=None, sort_by_word=False, parallel: bool = False):
    t0 = time.perf_counter()
    logger.info("build_tries start: fwd=%s rev=%s overwrite=%s parallel=%s",
                fwd_db_path, rev_db_path, overwrite, parallel)
    if parallel:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        tasks = [
            (fwd_db_path, overwrite, wordlist_path, pbar, min_glen, max_glen, sort_by_word, False),
            (rev_db_path, overwrite, wordlist_path, pbar, min_glen, max_glen, sort_by_word, True),
        ]
        with ProcessPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_build_one_trie, t) for t in tasks]
            for fut in as_completed(futs):
                _ = fut.result()  # propagate exceptions
    else:
        fwd, rev = _open_or_reset_tries(fwd_db_path, rev_db_path, overwrite)
        try:
            _populate_tries(fwd, rev, wordlist_path, pbar=pbar,
                            min_glen=min_glen, max_glen=max_glen,
                            sort_by_word=sort_by_word)
        finally:
            fwd.close()
            rev.close()
    dur_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("build_tries done dur_ms=%d", dur_ms)

def main():
    import os
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    # Create and parse arguments from our dedicated parser
    ap = build_arg_parser()
    args = ap.parse_args()

    from backend.core.profile import Profile
    prof = Profile(name=args.profile, base_dir=args.base_dir)
    wl = args.wordlist or prof.wordlist_path
    base_dir = os.path.dirname(wl)
    fwd_path = args.fwd or os.path.join(base_dir, "fwd.trie")
    rev_path = args.rev or os.path.join(base_dir, "rev.trie")

    if args.build:
        t0_build = time.perf_counter()
        os.makedirs(os.path.dirname(fwd_path), exist_ok=True)
        os.makedirs(os.path.dirname(rev_path), exist_ok=True)
        build_tries(
            wl, fwd_path, rev_path,
            overwrite=args.overwrite, pbar=args.pbar,
            min_glen=args.min_glen, max_glen=args.max_glen,
            sort_by_word=args.sort_by_word, parallel=args.parallel
        )
        t_build = int((time.perf_counter() - t0_build) * 1000)
        logger.info("Trie CLI: build done dur_ms=%d", t_build)
        print(f"Built tries: fwd={fwd_path} rev={rev_path} (wordlist={wl})")
        return

    print(f"Using wordlist={wl}")
    print(f"Using fwd_trie={fwd_path}")
    print(f"Using rev_trie={rev_path}")
    idx = TrieWordIndex(wl, fwd_path, rev_path)
    logger.info("Trie CLI: query prefix=%r suffix=%r min_len=%s max_len=%s limit=%s",
                args.query_prefix, args.query_suffix, args.min_len, args.max_len, args.limit)
    t0 = time.perf_counter()
    try:
        rows = idx.query_words(prefix=args.query_prefix, suffix=args.query_suffix,
                               min_len=args.min_len, max_len=args.max_len, limit=args.limit)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("Trie CLI: query returned=%d dur_ms=%d", len(rows), dur_ms)
        for w, fr, gl in rows:
            print(f"{w}\t{fr}\t{gl}")
    finally:
        idx.close()

if __name__ == "__main__":
    main()
