from __future__ import annotations
from typing import List, Tuple, Dict, Iterable, Optional, Set, Any

try:
    import psycopg2  # optional; used by PostgresStorage
    from psycopg2.extras import execute_batch
except Exception:
    psycopg2 = None
    execute_batch = None

Row = List[str]

class StorageBase:
    def write_batch(self, edited_rows: List[Row], batch_name: str) -> str:
        raise NotImplementedError
    def append_ledger(self, tsv_lines: List[str], batch_name: str) -> str:
        raise NotImplementedError
    def load_reminders(self) -> Set[str]:
        raise NotImplementedError
    def write_reminders(self, words: Set[str]) -> None:
        raise NotImplementedError
    def get_curated_sets(self) -> Tuple[Set[str], Dict[str,int]]:
        raise NotImplementedError
    def append_summary(self, batch_name: str, summary: Dict[str, Any]) -> str:
        raise NotImplementedError
    def has_words(self) -> bool:
        raise NotImplementedError
    def ensure_words(self, records: Iterable[Tuple[str, int, int]]) -> None:
        raise NotImplementedError
    def query_index(self, prefix: str, suffix: str, regex: str,
                    prefix_not: str, suffix_not: str, regex_not: str,
                    min_len: int, max_len, limit: int, curated_ratio: int) -> List[Tuple[str, int, int]]:
        raise NotImplementedError
    def get_latest_splits(self) -> Dict[str, str]:
        raise NotImplementedError
    def add_segmentation(self, word: str, left_text: str, right_text: str, split_pos: int, notes: str = "") -> None:
        raise NotImplementedError
    def list_segmentations(self, word: str, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError
