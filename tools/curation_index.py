"""
Bloom filter and curated-word index built from the ledger.
"""
import os, math, hashlib, time
import logging
logger = logging.getLogger("curation_index")

class BloomFilter:
    def __init__(self, capacity, error_rate=0.01):
        self.capacity = max(1, int(capacity))
        self.error_rate = max(min(error_rate, 0.5), 1e-9)
        m = -self.capacity * math.log(self.error_rate) / (math.log(2) ** 2)
        self.m = int(max(8, math.ceil(m)))
        k = (self.m / self.capacity) * math.log(2)
        self.k = int(max(1, round(k)))
        self.bits = bytearray((self.m + 7) // 8)
        self.count = 0

    def _hashes(self, item):
        data = item.encode("utf-8")
        h1 = int.from_bytes(hashlib.md5(data).digest()[:8], "big")
        h2 = int.from_bytes(hashlib.sha1(data).digest()[:8], "big")
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def add(self, item):
        for idx in self._hashes(item):
            byte_i = idx >> 3
            bit_i = idx & 7
            self.bits[byte_i] |= (1 << bit_i)
        self.count += 1

    def __contains__(self, item):
        for idx in self._hashes(item):
            byte_i = idx >> 3
            bit_i = idx & 7
            if (self.bits[byte_i] & (1 << bit_i)) == 0:
                return False
        return True

class CuratedIndex:
    def __init__(self, batches_dir, error_rate=0.01):
        self.batches_dir = batches_dir
        self.error_rate = error_rate
        self.bloom = BloomFilter(1, error_rate=self.error_rate)
        self.curated_count = 0
        self._last_mtime = 0.0
        self.curated_words = set()
        self.curation_counts = {}
        self.total_curation_entries = 0
        logger.info("CuratedIndex(fs): dir=%s err=%.3g", self.batches_dir, self.error_rate)




    def maybe_reload_on_change(self):
        try:
            logger.debug("CuratedIndex.fs: maybe_reload_on_change scan dir=%s", self.batches_dir)
            latest = 0.0
            if not os.path.isdir(self.batches_dir):
                logger.debug("CuratedIndex.fs: batches dir does not exist: %s", self.batches_dir)
                return
            for name in os.listdir(self.batches_dir):
                if not name.lower().endswith(".tsv"):
                    continue
                p = os.path.join(self.batches_dir, name)
                try:
                    st = os.stat(p)
                    if st.st_mtime > latest:
                        latest = st.st_mtime
                except OSError:
                    continue
            if latest > self._last_mtime:
                logger.info("CuratedIndex.fs: change detected mtime_old=%.0f mtime_new=%.0f -> reload",
                            self._last_mtime, latest)
                self.reload()
            else:
                logger.debug("CuratedIndex.fs: no change (latest<=last_mtime)")
        except Exception as e:
            logger.warning("CuratedIndex.fs: maybe_reload_on_change failed: %s", e)

    def update_from_batch(self, tsv_lines):
        logger.debug("CuratedIndex.fs: update_from_batch start")
        header = tsv_lines[0].strip().split("\t")
        idx = {h: i for i, h in enumerate(header)}
        if not {"word", "splits"}.issubset(idx):
            return
        added = 0
        for ln in tsv_lines[1:]:
            if not ln.strip():
                continue
            cols = ln.rstrip("\n").split("\t")
            w = cols[idx["word"]]
            s = cols[idx["splits"]]
            if s:
                self.bloom.add(w)
                added += 1
                self.curated_words.add(w)
                self.curation_counts[w] = self.curation_counts.get(w, 0) + 1
        self.curated_count += added
        self._last_mtime = time.time()
        self.total_curation_entries += added
        if added > 0:
            logger.info("CuratedIndex.fs: update_from_batch added=%d curated_distinct=%d total_entries=%d",
                        added, len(self.curated_words), self.total_curation_entries)
        else:
            logger.info("CuratedIndex.fs: update_from_batch added=0 (no-op)")

class CuratedIndexDB(CuratedIndex):
    def __init__(self, storage, error_rate=0.01):
        super().__init__(batches_dir="", error_rate=error_rate)
        self.storage = storage
        logger.info("CuratedIndexDB: storage=%s err=%.3g", type(self.storage).__name__, self.error_rate)

    def reload(self):
        logger.info("CuratedIndexDB.reload: fetching curated sets")
        try:
            words, counts = self.storage.get_curated_sets()
            cap = max(1000, int(len(words) * 1.3) or 1)
            self.bloom = BloomFilter(capacity=cap, error_rate=self.error_rate)
            for w in words:
                self.bloom.add(w)
            self.curated_count = len(words)
            self._last_mtime = time.time()
            self.curated_words = set(words)
            self.curation_counts = dict(counts)
            self.total_curation_entries = sum(counts.values())
            logger.info("CuratedIndexDB.reload: curated_distinct=%d total_entries=%d bloom_bits=%d k=%d",
                        len(words), sum(counts.values()), self.bloom.m, self.bloom.k)
            return
        except Exception as e:
            logger.warning("CuratedIndexDB.reload failed: %s", e)
            self.bloom = BloomFilter(1, error_rate=self.error_rate)
            self.curated_count = 0
            self._last_mtime = 0.0
            self.curated_words = set()
            self.curation_counts = {}
            self.total_curation_entries = 0






    def is_curated(self, word):
        return word in self.bloom


    def update_from_batch(self, tsv_lines):
        # Fast-path update after commit without full reload
        header = tsv_lines[0].strip().split("\t")
        idx = {h: i for i, h in enumerate(header)}
        if not {"word", "splits"}.issubset(idx):
            return
        added = 0
        for ln in tsv_lines[1:]:
            if not ln.strip():
                continue
            cols = ln.rstrip("\n").split("\t")
            w = cols[idx["word"]]
            s = cols[idx["splits"]]
            if s:
                self.bloom.add(w)
                added += 1
                self.curated_words.add(w)
                self.curation_counts[w] = self.curation_counts.get(w, 0) + 1
        self.curated_count += added
        self._last_mtime = time.time()
        self.total_curation_entries += added
