#!/usr/bin/env python3
import logging
import time
import string
import sys
import random
import math
import os
import weakref
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QMessageBox, QAbstractItemView, QMenu, QAction,
    QInputDialog, QStyledItemDelegate, QSplitter, QShortcut as MyShortcut
)


from tools.tamil_phonetic import transliterate, PHONETIC_VOWELS, CONSONANTS
from tools.curation_index import CuratedIndex
from tools.word_indexer import WordIndex

CURATED_INDEX_CACHE = {}
def get_shared_curated_index(batches_dir):
    key = os.path.abspath(batches_dir)
    idx = CURATED_INDEX_CACHE.get(key)
    if idx is None:
        idx = CuratedIndex(batches_dir)
        idx.reload()
        CURATED_INDEX_CACHE[key] = idx
        logging.info("Loaded CuratedIndex once: %s", key)
    else:
        logging.info("Reusing shared CuratedIndex: %s", key)
    return idx

WINDOWS = weakref.WeakSet()

# Shared WordIndex cache keyed by absolute wordlist path
WORD_INDEX_CACHE = {}
def get_shared_word_index(wordlist_path):
    wi = WORD_INDEX_CACHE.get(wordlist_path)
    if wi is None:
        wi = WordIndex(wordlist_path)
        WORD_INDEX_CACHE[wordlist_path] = wi
        logging.info("Loaded WordIndex once: %s (%d words)", wordlist_path, len(wi.words))
    else:
        logging.info("Reusing shared WordIndex: %s (%d words)", wordlist_path, len(wi.words))
    return wi

TOKEN_DELIMITER = " "
BATCHES_DIR = "data/batches"
LEDGER_PATH = "data/splits-ledger.tsv"
WORDLIST_PATH = "data/word-index.tsv"
UI_LOG_PATH = "data/ui-log.tsv"
REMINDERS_PATH = "data/reminders.tsv"
class PhoneticLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Holds the committed text (already converted Tamil characters)
        self.committed = ""
        # Holds the composition in progress as a roman sequence
        self.composition = ""
        self.trailing = ""

    def set_text_tamil(self, s):
        """Set field text to a Tamil string; clear composition/trailing and refresh."""
        self.committed = s or ""
        self.composition = ""
        self.trailing = ""
        self.update_display()

    def setUndoRedoEnabled(self, enabled):
        """
        Delegate to the base QLineEdit's setUndoRedoEnabled if available.
        If not, do nothing.
        """
        try:
            super().setUndoRedoEnabled(enabled)
        except AttributeError:
            pass

    def is_possible_prefix(self, candidate):
        """
        Return True if candidate (a roman string) is either:
          - exactly a token in PHONETIC_VOWELS or CONSONANTS,
          - a prefix of any token in PHONETIC_VOWELS or CONSONANTS,
        OR, if candidate can be split as (consonant + vowel_prefix) where:
          - the consonant part is a valid consonant token, and
          - the vowel_prefix part is a prefix of any vowel token in PHONETIC_VOWELS.
        """
        candidate = candidate.lower()
        tokens = list(PHONETIC_VOWELS.keys()) + list(CONSONANTS.keys())
        # First, check if candidate is exactly a token or is a prefix.
        if any(token == candidate or token.startswith(candidate) for token in tokens):
            return True
        # Next, check for the composite case:
        if len(candidate) >= 2:
            # Try to split candidate into a consonant part and vowel part.
            # We iterate over possible splits; usually the consonant token is one or two letters.
            for i in range(1, len(candidate)):
                cons_part = candidate[:i]
                vowel_part = candidate[i:]
                # Check if cons_part is exactly a valid consonant token.
                if cons_part in CONSONANTS:
                    # Check if the vowel_part is a prefix of some vowel token.
                    if any(vowel.startswith(vowel_part) for vowel in PHONETIC_VOWELS.keys()):
                        return True
        return False

    def commit_composition(self):
        """
        Commit the current composition: convert it to Tamil and append it to committed.
        In our interactive model, if the composition appears incomplete (i.e. ends with a consonant),
        force the addition of a pulli.
        Then clear the composition.
        """
        if self.composition:
            # Log the raw composition before committing.
            logging.debug("Committing composition: '%s'", self.composition)
            result = transliterate(self.composition)
            # Determine if the composition is incomplete.
            # (If the roman composition does not end with any vowel token, assume it is incomplete.)
            incomplete = True
            for vt in PHONETIC_VOWELS.keys():
                if self.composition.lower().endswith(vt):
                    incomplete = False
                    break
            # If incomplete and result does not already end with a pulli, force a pulli.
            if incomplete and not result.endswith("்"):
                result += "்"
                logging.debug("Forced pulli, result becomes: '%s'", result)
            self.committed += result
            logging.debug("Committed text updated: '%s'", self.committed)
            self.composition = ""

    def _render_composition(self):
        current_disp = transliterate(self.composition)
        if self.composition and not any(self.composition.lower().endswith(vt) for vt in PHONETIC_VOWELS.keys()):
            if not current_disp.endswith("்"):
                current_disp += "்"
        return current_disp

    def update_display(self):
        """
        Update the QLineEdit display with the transliteration of (committed + composition).
        """
        current_disp = self._render_composition()
        disp = self.committed + current_disp + self.trailing
        self.setText(disp)
        self.setCursorPosition(len(self.committed + current_disp))
        logging.debug("Display updated: '%s' (committed: '%s', composition: '%s')",
                      disp, self.committed, self.composition)

    def _normalize_state_for_editing(self, current_text, cp):
        if self.hasSelectedText():
            sel_start = self.selectionStart()
            sel_end = sel_start + len(self.selectedText())
            self.committed = current_text[:sel_start]
            self.trailing = current_text[sel_end:]
            self.composition = ""
            return
        expected_cp = len(self.committed + self._render_composition())
        if cp == expected_cp and current_text.startswith(self.committed + self._render_composition()) and current_text.endswith(self.trailing):
            return
        if cp < len(current_text):
            self.committed = current_text[:cp]
            self.trailing = current_text[cp:]
            self.composition = ""
        else:
            if self.trailing:
                self.committed = current_text
                self.trailing = ""
                self.composition = ""

    def _handle_backspace(self):
        if self.composition:
            self.composition = self.composition[:-1]
        else:
            self.committed = self.committed[:-1]
        self.update_display()

    def _handle_delete(self):
        if self.composition:
            self.composition = ""
        elif self.trailing:
            self.trailing = self.trailing[1:]
        self.update_display()

    def _handle_boundary_char(self, ch):
        self.commit_composition()
        self.committed += ch
        self.update_display()

    def _handle_alnum_char(self, ch):
        candidate = self.composition + ch
        if self.is_possible_prefix(candidate):
            self.composition = candidate
        else:
            self.commit_composition()
            if self.is_possible_prefix(ch):
                self.composition = ch
            else:
                self.committed += ch
        self.update_display()

    def keyPressEvent(self, event):
        key = event.key()
        ch = event.text()
        logging.debug("Key press: key=%s, text='%s', current composition='%s', committed='%s'",
                      key, ch, self.composition, self.committed)

        # Normalize buffers for caret/selection position
        current_text = self.text()
        cp = self.cursorPosition()
        self._normalize_state_for_editing(current_text, cp)

        if key == Qt.Key_Backspace:
            self._handle_backspace()
            event.accept()
            return
        elif key == Qt.Key_Delete:
            self._handle_delete()
            event.accept()
            return
        elif ch and (ch in string.whitespace or ch in string.punctuation):
            self._handle_boundary_char(ch)
            event.accept()
            return
        elif ch and ch.isalnum():
            self._handle_alnum_char(ch)
            event.accept()
            return
        else:
            super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        pasted_text = source.text()
        current_text = self.text()
        if self.hasSelectedText():
            sel_start = self.selectionStart()
            sel_end = sel_start + len(self.selectedText())
            self.committed = current_text[:sel_start] + pasted_text
            self.trailing = current_text[sel_end:]
        else:
            cp = self.cursorPosition()
            self.committed = current_text[:cp] + pasted_text
            self.trailing = current_text[cp:]
        self.composition = ""
        self.update_display()

    def contextMenuEvent(self, event):
        # Base QLineEdit menu
        menu = self.createStandardContextMenu()
        # Selected text if any, otherwise full field text
        text = self.selectedText().strip() if self.hasSelectedText() else self.text().strip()
        if text:
            menu.addSeparator()
            win = self.window()
            if hasattr(win, "new_window_from_text"):
                for kind, label in (("prefix", "Prefix"), ("suffix", "Suffix"), ("regex", "Regex")):
                    act = QAction(f"New Window as {label}: {text}", self)
                    act.triggered.connect(lambda _, k=kind, t=text: win.new_window_from_text(k, t))
                    menu.addAction(act)
        menu.exec_(event.globalPos())

class TableCellLineEdit(QLineEdit):
    def contextMenuEvent(self, event):
        # Start with the standard menu (cut/copy/paste/select all)
        menu = self.createStandardContextMenu()
        # Determine selected text or full cell text
        text = self.selectedText().strip() if self.hasSelectedText() else self.text().strip()
        if text:
            menu.addSeparator()
            win = self.window()
            if hasattr(win, "new_window_from_text"):
                for kind, label in (("prefix", "Prefix"), ("suffix", "Suffix"), ("regex", "Regex")):
                    act = QAction(f"New Window as {label}: {text}", self)
                    act.triggered.connect(lambda _, k=kind, t=text: win.new_window_from_text(k, t))
                    menu.addAction(act)
                menu.addSeparator()
                if hasattr(win, "new_window_from_text"):
                    for kind, label in (("not_prefix", "Exclude Prefix"),
                                        ("not_suffix", "Exclude Suffix"),
                                        ("not_regex", "Exclude Regex")):
                        act = QAction(f"New Window as {label}: {text}", self)
                        act.triggered.connect(lambda _, k=kind, t=text: win.new_window_from_text(k, t))
                        menu.addAction(act)
        menu.exec_(event.globalPos())

class TableEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = TableCellLineEdit(parent)
        ed.setFrame(False)
        return ed

class MainWindow(QMainWindow):
    def _apply_global_styles(self):
        btn_h = int(28 * self.ui_scale)
        le_h = int(26 * self.ui_scale)
        pad_y = int(6 * self.ui_scale)
        pad_x = int(12 * self.ui_scale)
        self.setStyleSheet(
            f"""
            QWidget {{ font-size: {self.font_size}pt; }}
            QPushButton {{ font-size: {self.font_size}pt; min-height: {btn_h}px; padding: {pad_y}px {pad_x}px; }}
            QLineEdit {{ font-size: {self.font_size}pt; min-height: {le_h}px; }}
            QHeaderView::section {{ font-size: {self.font_size}pt; padding: {max(4, pad_y-2)}px {max(6, pad_x-6)}px; }}
            """
        )

    def _build_main_splitter(self):
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.addLayout(self.build_prefix_suffix_regex_panel())
        left_layout.addLayout(self.build_query_parameters_panel())
        left_layout.addLayout(self.build_sort_panel())
        left_layout.addWidget(self.build_table_panel())
        left_layout.addLayout(self.build_find_replace_panel())
        self.summary_widget = self.build_summary_panel()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_container)
        splitter.addWidget(self.summary_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _init_paths_and_indexes(self):
        self.batch_dir = os.path.abspath(BATCHES_DIR)
        logging.info("Batches directory: %s", self.batch_dir)
        os.makedirs(self.batch_dir, exist_ok=True)
        self.wordlist_path = WORDLIST_PATH
        self.word_index = get_shared_word_index(self.wordlist_path)
        self.curated = get_shared_curated_index(self.batch_dir)
        logging.info("Curated index (from batches) loaded: %d word(s)", self.curated.curated_count)

    def _init_shortcuts(self):
        from PyQt5.QtGui import QKeySequence
        MyShortcut(QKeySequence("Ctrl+S"), self, activated=self.commit_edits)
        MyShortcut(QKeySequence("Alt+P"), self, activated=lambda: self.prefix_edit.setFocus())
        MyShortcut(QKeySequence("Alt+S"), self, activated=lambda: self.suffix_edit.setFocus())
        MyShortcut(QKeySequence("Alt+R"), self, activated=lambda: self.regex_edit.setFocus())
        MyShortcut(QKeySequence("Alt+F"), self, activated=lambda: self.find_edit.setFocus())
        MyShortcut(QKeySequence("Alt+G"), self, activated=lambda: self.replace_edit.setFocus())
        MyShortcut(QKeySequence("Alt+L"), self, activated=lambda: self.length_edit.setFocus())
        MyShortcut(QKeySequence("Alt+I"), self, activated=lambda: self.limit_spin.setFocus())
        MyShortcut(QKeySequence("Alt+Q"), self, activated=lambda: self.query_btn.setFocus())
        MyShortcut(QKeySequence("Alt+M"), self, activated=self.toggle_reminder_for_selected)
        MyShortcut(QKeySequence("Alt+B"), self, activated=self.show_reminder_bag)
        MyShortcut(QKeySequence("Ctrl+N"), self, activated=self.open_new_window_with_current_query)
        MyShortcut(QKeySequence("Ctrl+Shift+N"), self, activated=self.open_new_window_from_selection)
        self.child_windows = []

    def __init__(self, ui_scale=1.5, font_size=None):
        super().__init__()
        self.ui_scale = float(ui_scale) if ui_scale else 1.0
        self.font_size = int(font_size) if font_size else max(14, int(round(15 * self.ui_scale)))
        self._apply_global_styles()
        self._init_paths_and_indexes()
        self.setWindowTitle("Tamil Splits - Qt Client")
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = self._build_main_splitter()
        main_layout.addWidget(splitter)
        WINDOWS.add(self)
        self.reminders = set()
        self.load_reminders()
        logging.info("Loaded %d reminder word(s)", len(self.reminders))
        self.bulk_editing = False

        # (Query button connected earlier in the params panel.)
        self._init_shortcuts()

        # New window shortcuts
        from PyQt5.QtGui import QKeySequence
        MyShortcut(QKeySequence("Ctrl+N"), self, activated=self.open_new_window_with_current_query)
        MyShortcut(QKeySequence("Ctrl+Shift+N"), self, activated=self.open_new_window_from_selection)

    def parse_length_spec(self, length_spec):
        # Parse the length specification.
        # Default values:
        min_len = 1
        max_len = None

        if "-" in length_spec:
            parts = length_spec.split("-", 1)
            try:
                if parts[0]:
                    min_len = int(parts[0])
                else:
                    min_len = 1
            except ValueError:
                min_len = 1
            try:
                if parts[1]:
                    max_len = int(parts[1])
                else:
                    max_len = None
            except ValueError:
                max_len = None
        else:
            try:
                m = int(length_spec)
                min_len = m
                max_len = m
            except ValueError:
                min_len = 1
                max_len = None

        return min_len, max_len

    def _read_query_fields(self):
        """Read and normalize current query fields, including negative filters and curated ratio."""
        prefix = self.prefix_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        regex = self.regex_edit.text().strip()
        length_spec = self.length_edit.text().strip()
        limit = int(self.limit_spin.value())
        curated_ratio = float(self.curated_ratio_spin.value()) / 100.0
        prefix_not = self.prefix_not_edit.text().strip() if hasattr(self, "prefix_not_edit") else ""
        suffix_not = self.suffix_not_edit.text().strip() if hasattr(self, "suffix_not_edit") else ""
        regex_not = self.regex_not_edit.text().strip() if hasattr(self, "regex_not_edit") else ""
        neg_rx = None
        if regex_not:
            try:
                import re
                neg_rx = re.compile(regex_not)
            except re.error:
                neg_rx = None
        return {
            "prefix": prefix, "suffix": suffix, "regex": regex,
            "length_spec": length_spec, "limit": limit, "curated_ratio": curated_ratio,
            "prefix_not": prefix_not, "suffix_not": suffix_not, "regex_not": regex_not, "neg_rx": neg_rx
        }

    def _probe_raw_results(self, q):
        """Fetch raw rows (word,freq,glen) with a larger probe limit to allow filtering."""
        min_len, max_len = self.parse_length_spec(q["length_spec"])
        probe_limit = min(q["limit"] * 5, max(q["limit"] + 500, 5000))
        return self.word_index.query_words(
            prefix=q["prefix"], suffix=q["suffix"],
            min_len=min_len, max_len=max_len,
            limit=probe_limit, offset=0, regex=q["regex"]
        )

    def _apply_negative_filters(self, rows, q):
        """Filter out rows matching any negative conditions."""
        out = []
        for w, fr, gl in rows:
            if (q["prefix_not"] and w.startswith(q["prefix_not"])) or \
               (q["suffix_not"] and w.endswith(q["suffix_not"])) or \
               (q["neg_rx"] and q["neg_rx"].search(w)):
                continue
            out.append((w, fr, gl))
        return out

    def _partition_new_old(self, rows):
        """Split into new (uncurated) and old (curated) lists."""
        new_rows, old_rows = [], []
        for w, fr, gl in rows:
            (new_rows if not self.curated.is_curated(w) else old_rows).append((w, fr, gl))
        return new_rows, old_rows

    def _pick_curated_and_new(self, new_rows, old_rows, limit, curated_ratio):
        """Select rows honoring curated ratio; with 0.0 never include curated backfill."""
        if curated_ratio <= 0.0:
            combined = new_rows[:limit]
            return combined, len(combined), 0
        curated_quota = int(math.floor(limit * curated_ratio))
        curated_pick = []
        if old_rows and curated_quota > 0:
            curated_pick = random.sample(old_rows, k=min(curated_quota, len(old_rows)))
        remaining_slots = max(0, limit - len(curated_pick))
        new_pick = new_rows[:remaining_slots]
        leftover = max(0, limit - (len(curated_pick) + len(new_pick)))
        if leftover > 0:
            remaining_old = [r for r in old_rows if r not in curated_pick]
            if remaining_old:
                curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old)))
        combined = (new_pick + curated_pick)[:limit]
        return combined, len(new_pick), len(curated_pick)

    def _log_query_event(self, q):
        self.log_ui_event("QUERY", {
            "prefix": q["prefix"], "suffix": q["suffix"], "regex": q["regex"],
            "prefix_not": q["prefix_not"], "suffix_not": q["suffix_not"], "regex_not": q["regex_not"],
            "length_spec": q["length_spec"], "limit": q["limit"]
        })

    def _log_filter_stats(self, raw, new_rows, old_rows, shown_new, shown_curated, curated_ratio):
        self.log_ui_event("FILTER_CURATED", {
            "queried": len(raw),
            "new": len(new_rows),
            "curated": len(old_rows),
            "shown_new": shown_new,
            "shown_curated": shown_curated,
            "curated_ratio": curated_ratio
        })

    def query_words(self):
        self.curated.maybe_reload_on_change()
        q = self._read_query_fields()
        self._log_query_event(q)
        raw = self._probe_raw_results(q)
        eligible = self._apply_negative_filters(raw, q)
        new_rows, old_rows = self._partition_new_old(eligible)
        combined, shown_new, shown_curated = self._pick_curated_and_new(new_rows, old_rows, q["limit"], q["curated_ratio"])
        self._log_filter_stats(raw, new_rows, old_rows, shown_new, shown_curated, q["curated_ratio"])
        self.populate_table_from_results(combined)

    def build_tsv_lines(self):
        """
        Builds a list of strings representing TSV lines from the current table data.
        The first line is the header: "id\tword\tsplits\tfreq\tglen\tnotes"
        """
        lines = []
        header = "\t".join(["id", "word", "splits", "freq", "glen", "notes"])
        lines.append(header)
        row_count = self.table.rowCount()
        col_count = self.table.columnCount()
        for row in range(row_count):
            row_data = []
            for col in range(col_count):
                item = self.table.item(row, col)
                row_data.append(item.text() if item is not None else "")
            lines.append("\t".join(row_data))
        return lines

    def update_ledger(self, tsv_lines, batch_name):
        """
        Given TSV lines (list of strings) built from the table and a batch name,
        this function appends ledger entries to the ledger file.
        Each ledger line includes the timestamp, batch name, id, word, splits, and notes.
        """
        import os, fcntl, time
        ledger_path = LEDGER_PATH
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        write_header = not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(ledger_path, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
                    lf.write("\t".join(["timestamp", "batch", "id", "word", "splits", "notes"]) + "\n")
                for ln in tsv_lines[1:]:
                    if not ln.strip():
                        continue
                    cols = ln.split("\t")
                    rec_id = cols[0].strip()
                    word = cols[1].strip()
                    splits = cols[2].strip()
                    notes = cols[5].strip() if len(cols) > 5 else ""
                    lf.write(f"{ts}\t{batch_name}\t{rec_id or word}\t{word}\t{splits}\t{notes}\n")
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _compute_summary_snapshot(self):
        glen_map = {}
        index_words = set()
        for w, fr, gl in self.word_index.words:
            index_words.add(w)
            glen_map[w] = gl
        total_words = len(index_words)
        curated_set = getattr(self.curated, "curated_words", set())
        curated_in_index = {w for w in curated_set if w in index_words}
        remaining_set = index_words - curated_in_index
        total_curations = getattr(self.curated, "total_curation_entries", 0)
        curated_len = Counter(glen_map[w] for w in curated_in_index if w in glen_map)
        remaining_len = Counter(glen_map[w] for w in remaining_set if w in glen_map)
        return {
            "total_words": total_words,
            "curated_distinct": len(curated_in_index),
            "remaining_distinct": len(remaining_set),
            "curation_entries": total_curations,
            "length_distribution": {
                "curated": dict(curated_len),
                "remaining": dict(remaining_len)
            }
        }

    def append_summary_ledger(self, batch_name):
        import os, fcntl, time, json
        summary = self._compute_summary_snapshot()
        ledger_path = LEDGER_PATH
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
        write_header = not os.path.exists(ledger_path) or os.path.getsize(ledger_path) == 0
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(ledger_path, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
                    lf.write("\t".join(["timestamp", "batch", "id", "word", "splits", "notes"]) + "\n")
                rec_id = "__SUMMARY__"
                word = str(summary["total_words"])
                splits = ""
                notes = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
                lf.write(f"{ts}\t{batch_name}\t{rec_id}\t{word}\t{splits}\t{notes}\n")
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


    def sanitize_component(self, s):
        import re
        # Replace path separators, Windows-reserved chars, and whitespace with underscores, trim length
        return re.sub(r'[\\/:*?"<>|\s]+', '_', s).strip('_')[:64]

    def generate_batch_name(self):
       # Compute a default batch name in the format:
       # {timestamp}-{prefix}{min_len}{suffix}.tsv
       timestamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
       prefix = self.prefix_edit.text().strip()
       suffix = self.suffix_edit.text().strip()
       length_spec = self.length_edit.text().strip()
       # Remove any characters that might interfere with filenames.
       # safe_prefix = "".join(c for c in prefix if c.isalnum())
       # safe_suffix = "".join(c for c in suffix if c.isalnum())
       safe_prefix = self.sanitize_component(prefix)
       safe_suffix = self.sanitize_component(suffix)
       safe_len = self.sanitize_component(length_spec)
       return f"{timestamp}-{safe_prefix}-{safe_len}-{safe_suffix}.tsv"

    def _collect_edited_rows(self):
        """Return list of [id, word, splits, freq, glen, notes] for rows whose splits changed."""
        edited_rows = []
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            sp_item = self.table.item(row, 2)
            if not id_item or not sp_item:
                continue
            rec_id = id_item.text()
            curr_splits = sp_item.text()
            orig = self.original_splits.get(rec_id, "")
            if curr_splits != orig:
                word = (self.table.item(row, 1).text() if self.table.item(row, 1) else "")
                freq = (self.table.item(row, 3).text() if self.table.item(row, 3) else "")
                glen = (self.table.item(row, 4).text() if self.table.item(row, 4) else "")
                notes = (self.table.item(row, 5).text() if self.table.item(row, 5) else "")
                edited_rows.append([rec_id, word, curr_splits, freq, glen, notes])
        return edited_rows

    def _write_batch_file(self, batch_name, edited_rows):
        """Write batch TSV file and return (filepath, tsv_lines)."""
        tsv_lines = ["\t".join(["id","word","splits","freq","glen","notes"])]
        tsv_lines.extend("\t".join(r) for r in edited_rows)
        filepath = os.path.abspath(os.path.join(self.batch_dir, batch_name))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(tsv_lines) + "\n")
        return filepath, tsv_lines

    def _refresh_curated_and_broadcast(self, tsv_lines):
        """Update curated index from batch (incremental). No auto-refresh; use Summary Refresh."""
        self.curated.update_from_batch(tsv_lines)

    def _update_baseline_after_save(self, edited_rows):
        """Update original_splits baseline and clear edited markers/backgrounds for saved rows."""
        edited_ids_set = set()
        for rec_id, word, new_splits, freq, glen, notes in edited_rows:
            self.original_splits[rec_id] = new_splits
            edited_ids_set.add(rec_id)
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            if not id_item:
                continue
            rid = id_item.text()
            if rid in edited_ids_set:
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.white)
                if rid in self.edited_ids:
                    self.edited_ids.remove(rid)
        self.dirty = bool(self.edited_ids)

    def commit_edits(self):
        if not getattr(self, "dirty", False):
            QMessageBox.information(self, "Commit", "No edits since last save.")
            return
        edited_rows = self._collect_edited_rows()
        if not edited_rows:
            QMessageBox.information(self, "Commit", "No edits to save.")
            return
        batch_name = self.generate_batch_name()
        try:
            filepath, tsv_lines = self._write_batch_file(batch_name, edited_rows)
            self.update_ledger(tsv_lines, batch_name)
            self._refresh_curated_and_broadcast(tsv_lines)
            self.append_summary_ledger(batch_name)
            self.log_ui_event("COMMIT", {"batch": batch_name, "saved_rows": len(edited_rows)})
            logging.info("Saved batch file to %s", filepath)
            QMessageBox.information(self, "Commit", f"Saved {len(edited_rows)} edited row(s) to {filepath}")
            self._update_baseline_after_save(edited_rows)
        except Exception as e:
            QMessageBox.critical(self, "Commit Error", str(e))

    def get_table_data(self):
        """Returns the table data as a list of rows (each row is a list of cell strings)."""
        data = []
        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data.append(item.text() if item is not None else "")
            data.append(row_data)
        return data

    def set_table_data(self, data):
        """Clears and repopulates the table with data (list of rows)."""
        self.suppress_item_changed = True
        self.table.setColumnCount(6)
        self.table.setRowCount(0)
        for row_data in data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(row_data):
                new_item = QTableWidgetItem(text)
                new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
                self.table.setItem(row, col, new_item)
        self.table.resizeColumnsToContents()
        self.suppress_item_changed = False
        self.dirty = False


    def _normalize_result_tuple(self, rec):
        """Return (word, freq, glen, splits) from a heterogeneous rec tuple."""
        if len(rec) == 3:
            word, freq, glen = rec
            splits = word
        elif len(rec) >= 5:
            word = rec[1]; splits = rec[2] if rec[2] else rec[1]; freq = rec[3]; glen = rec[4]
        elif len(rec) == 4:
            word = rec[1]; freq = rec[2]; glen = rec[3]; splits = word
        else:
            return None
        return word, freq, glen, splits

    def _insert_result_row(self, row, rec_id, word, splits, freq, glen):
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(rec_id))
        self.table.setItem(row, 1, QTableWidgetItem(word))
        self.table.setItem(row, 2, QTableWidgetItem(splits))
        self.table.setItem(row, 3, QTableWidgetItem(str(freq)))
        self.table.setItem(row, 4, QTableWidgetItem(str(glen)))
        self.table.setItem(row, 5, QTableWidgetItem(""))
        self.original_splits[rec_id] = splits

    def populate_table_from_results(self, results):
        self.suppress_item_changed = True
        self.original_splits = {}
        self.edited_ids = set()
        self.table.setColumnCount(6)
        self.table.setRowCount(0)
        for rec in results:
            norm = self._normalize_result_tuple(rec)
            if not norm:
                continue
            word, freq, glen, splits = norm
            row = self.table.rowCount()
            rec_id = str(row + 1)
            self._insert_result_row(row, rec_id, word, splits, freq, glen)
        self.table.resizeColumnsToContents()
        self.suppress_item_changed = False

    def log_ui_event(self, event_type, parameters):
        """
        Append a UI event to the ledger log.
        parameters should be a dictionary with key=value pairs.
        The ledger file is a TSV file with header:
          timestamp	event_type	parameters
        """
        import os, fcntl, time
        log_path = UI_LOG_PATH  # e.g. "data/ui-log.tsv"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        write_header = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        params_str = "; ".join(f"{k}={v}" for k, v in parameters.items())
        line = f"{ts}\t{event_type}\t{params_str}\n"
        with open(log_path, "a", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if write_header:
                    lf.write("timestamp\tevent_type\tparameters\n")
                lf.write(line)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def load_reminders(self):
        """Load reminder words from REMINDERS_PATH into self.reminders."""
        self.reminders = set()
        try:
            with open(REMINDERS_PATH, "r", encoding="utf-8") as f:
                header = f.readline().strip().split("\t")
                idx = {h: i for i, h in enumerate(header)}
                if "word" not in idx:
                    return
                for ln in f:
                    if not ln.strip():
                        continue
                    cols = ln.rstrip("\n").split("\t")
                    w = cols[idx["word"]]
                    if w:
                        self.reminders.add(w)
        except FileNotFoundError:
            pass

    def _write_reminders_file(self):
        """Rewrite reminders file from self.reminders."""
        import os, fcntl, time
        os.makedirs(os.path.dirname(REMINDERS_PATH), exist_ok=True)
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with open(REMINDERS_PATH, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write("timestamp\tword\tnotes\n")
                for w in sorted(self.reminders):
                    f.write(f"{ts}\t{w}\t\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def add_to_reminders(self, words):
        """Add given words to reminders, persist, and log."""
        new_words = [w for w in words if w and w not in self.reminders]
        if not new_words:
            return
        for w in new_words:
            self.reminders.add(w)
        self._write_reminders_file()
        logging.info("REMINDER_ADD: %d word(s): %s", len(new_words), ", ".join(new_words[:5]))
        self.log_ui_event("REMINDER_ADD", {"count": len(new_words), "sample": ", ".join(new_words[:5])})

    def remove_from_reminders(self, words):
        """Remove given words from reminders, persist, and log."""
        removed = [w for w in words if w in self.reminders]
        if not removed:
            return
        for w in removed:
            self.reminders.discard(w)
        self._write_reminders_file()
        logging.info("REMINDER_REMOVE: %d word(s): %s", len(removed), ", ".join(removed[:5]))
        self.log_ui_event("REMINDER_REMOVE", {"count": len(removed), "sample": ", ".join(removed[:5])})

    def toggle_reminder_for_selected(self):
        """Toggle reminder status for selected rows; logs to console and UI log."""
        # Collect unique words from selected rows
        rows = {ix.row() for ix in self.table.selectedIndexes()}
        words = []
        for r in rows:
            it = self.table.item(r, 1)  # word column
            if it:
                words.append(it.text())
        if not words:
            logging.info("REMINDER_TOGGLE: no selection")
            return

        to_add = [w for w in words if w not in self.reminders]
        to_remove = [w for w in words if w in self.reminders]
        if to_add:
            self.add_to_reminders(to_add)
        if to_remove:
            self.remove_from_reminders(to_remove)
        logging.info("REMINDER_TOGGLE: added=%d removed=%d", len(to_add), len(to_remove))

    def show_reminder_bag(self):
        """Populate the table with all reminder words found in the index; logs to console and UI log."""
        if not self.reminders:
            logging.info("REMINDER_SHOW: empty")
            self.log_ui_event("REMINDER_SHOW", {"count": 0})
            return
        # Build results as (word, freq, glen) for all reminders present in the index
        index_map = {w: (w, fr, gl) for (w, fr, gl) in self.word_index.words}
        results = []
        for w in sorted(self.reminders):
            if w in index_map:
                results.append(index_map[w])
        logging.info("REMINDER_SHOW: %d word(s)", len(results))
        self.log_ui_event("REMINDER_SHOW", {"count": len(results)})
        self.populate_table_from_results(results)
    def refresh_phonetic_fields(self):
        for field in (self.prefix_edit, self.suffix_edit, self.regex_edit,
                      getattr(self, "prefix_not_edit", None),
                      getattr(self, "suffix_not_edit", None),
                      getattr(self, "regex_not_edit", None)):
            if field:
                field.update_display()

    def populate_table(self, data_lines):
        self.table.setRowCount(0)
        for line in data_lines:
            if not line.strip():  # skip empty lines
                continue
            cols = line.split("\t")
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(cols):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.table.setItem(row, col, item)






    def _selected_split_indexes(self):
        indexes = [ix for ix in self.table.selectedIndexes() if ix.column() == 2]
        if indexes:
            return indexes
        # If no cells are selected, target the entire splits column.
        return [self.table.model().index(row, 2) for row in range(self.table.rowCount())]

    def _replace_in_indexes(self, indexes, find_text, replace_text):
        changed_rows = set()
        for ix in indexes:
            row = ix.row()
            item = self.table.item(row, 2)
            if not item:
                continue
            original = item.text()
            new_text = original.replace(find_text, replace_text)
            if new_text != original:
                item.setText(new_text)
                changed_rows.add(row)
        return changed_rows

    def _mark_bulk_edits(self, rows):
        """Given an iterable of row indices, compare current splits vs baseline and highlight."""
        for row in set(rows):
            id_item = self.table.item(row, 0)
            sp_item = self.table.item(row, 2)
            if not id_item or not sp_item:
                continue
            rec_id = id_item.text()
            curr = sp_item.text()
            orig = self.original_splits.get(rec_id, "")
            if curr != orig:
                if rec_id not in self.edited_ids:
                    self.edited_ids.add(rec_id)
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.yellow)
                self.dirty = True
            else:
                if rec_id in self.edited_ids:
                    self.edited_ids.remove(rec_id)
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.white)
        if not self.edited_ids:
            self.dirty = False

    def apply_replace_to_cell(self):
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        normalized_replace = replace_text.replace(" ", TOKEN_DELIMITER)
        if not find_text:
            QMessageBox.warning(self, "Find/Replace", "Please enter text to find.")
            return
        indexes = self._selected_split_indexes()
        if not indexes:
            QMessageBox.warning(self, "Find/Replace", "No cells available in the splits column.")
            return
        # Bulk edit: block itemChanged signals and avoid per-row logging/painting
        self.bulk_editing = True
        self.table.blockSignals(True)
        try:
            changed_rows = self._replace_in_indexes(indexes, find_text, normalized_replace)
        finally:
            self.table.blockSignals(False)
            self.bulk_editing = False
        # Now, mark edits and backgrounds in one pass
        self._mark_bulk_edits(changed_rows)
        count_replaced = len(changed_rows)
        if count_replaced > 0:
            self.log_ui_event("REPLACE", {"find": find_text, "replace": normalized_replace, "cells_modified": count_replaced})
            QMessageBox.information(self, "Find/Replace", f"Replacement applied to {count_replaced} cell(s).")
        else:
            QMessageBox.information(self, "Find/Replace", "No replacements were made (find text not found).")

    def sort_table_by_prefix(self):
        """Sorts the table rows by the numeric 'id' (column 0) ascending."""
        data = self.get_table_data()
        def id_key(row):
            try:
                return int(row[0])
            except Exception:
                return float('inf')
        sorted_data = sorted(data, key=id_key)
        self.set_table_data(sorted_data)
        self.log_ui_event("SORT", {"type": "prefix"})

    def sort_table_by_suffix(self):
        """Sorts the table rows by the 'id' cell (column 0) in suffix order (based on reversed text)."""
        data = self.get_table_data()
        sorted_data = sorted(data, key=lambda row: row[0][::-1].lower() if row[0] else "")
        self.set_table_data(sorted_data)
        self.log_ui_event("SORT", {"type": "suffix"})

    def sort_table_custom(self, key_func, event_desc="custom"):
        """
        Generic function that sorts the table by a supplied key function.
        key_func should be a function that accepts a row (list of cell strings) and returns a sorting key.
        event_desc is a label for logging.
        """
        data = self.get_table_data()
        sorted_data = sorted(data, key=key_func)
        self.set_table_data(sorted_data)
        self.log_ui_event("SORT", {"type": event_desc})

    def apply_custom_sort(self):
        """
        Evaluates the text from the custom sort field as a lambda function,
        and sorts the table using that lambda as key.
        """
        lambda_str = self.sort_lambda_edit.text().strip()
        if not lambda_str:
            QMessageBox.warning(self, "Custom Sort", "Please enter a lambda function.")
            return
        try:
            # For safety, restrict the available built-ins (optional)
            allowed_builtins = {"int": int, "float": float, "str": str, "len": len}
            key_func = eval(f'lambda {lambda_str}', {"__builtins__": allowed_builtins})
            if not callable(key_func):
                raise ValueError("Lambda does not evaluate to a callable function.")
        except Exception as e:
            QMessageBox.critical(self, "Custom Sort", f"Error evaluating lambda:\n{e}")
            return
        try:
            # Use our generic sort function.
            self.sort_table_custom(key_func, event_desc=f"custom: `{lambda_str}`")
        except Exception as ex:
            QMessageBox.critical(self, "Custom Sort", f"Sorting error:\n{ex}")

    def sort_table_by_length_and_suffix(self):
        """
        Sorts the table rows by grapheme length (descending) then by suffix order (by reversed word text).
        """
        self.sort_table_custom(
            key_func=lambda row: (-int(row[4]), row[1][::-1].lower() if row[1] else ""),
            event_desc="length_and_suffix"
        )

    def build_find_replace_panel(self):
        """
        Returns a QHBoxLayout containing the Find/Replace widgets.
        """
        find_layout = QHBoxLayout()
        self.find_edit = PhoneticLineEdit(self)
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setUndoRedoEnabled(True)
        self.replace_edit = PhoneticLineEdit(self)
        self.replace_edit.setPlaceholderText("Replace")
        self.replace_edit.setUndoRedoEnabled(True)
        self.apply_replace_btn = QPushButton("Apply Replace")
        self.apply_replace_btn.clicked.connect(self.apply_replace_to_cell)
        find_layout.addWidget(QLabel("Find:"))
        find_layout.addWidget(self.find_edit)
        find_layout.addWidget(QLabel("Replace:"))
        find_layout.addWidget(self.replace_edit)
        find_layout.addWidget(self.apply_replace_btn)
        return find_layout

    def _build_prefix_row(self):
        row = QHBoxLayout()
        self.prefix_edit = PhoneticLineEdit(self)
        self.prefix_edit.setUndoRedoEnabled(True)
        row.addWidget(QLabel("Prefix:"))
        row.addWidget(self.prefix_edit)
        row.addWidget(QLabel("Exclude:"))
        self.prefix_not_edit = PhoneticLineEdit(self)
        self.prefix_not_edit.setUndoRedoEnabled(True)
        row.addWidget(self.prefix_not_edit)
        return row

    def _build_suffix_row(self):
        row = QHBoxLayout()
        self.suffix_edit = PhoneticLineEdit(self)
        self.suffix_edit.setUndoRedoEnabled(True)
        row.addWidget(QLabel("Suffix:"))
        row.addWidget(self.suffix_edit)
        row.addWidget(QLabel("Exclude:"))
        self.suffix_not_edit = PhoneticLineEdit(self)
        self.suffix_not_edit.setUndoRedoEnabled(True)
        row.addWidget(self.suffix_not_edit)
        return row

    def _build_regex_row(self):
        row = QHBoxLayout()
        self.regex_edit = PhoneticLineEdit(self)
        self.regex_edit.setPlaceholderText("Regex (optional)")
        self.regex_edit.setUndoRedoEnabled(True)
        row.addWidget(QLabel("Regex:"))
        row.addWidget(self.regex_edit)
        row.addWidget(QLabel("Exclude:"))
        self.regex_not_edit = PhoneticLineEdit(self)
        self.regex_not_edit.setPlaceholderText("Regex exclude")
        self.regex_not_edit.setUndoRedoEnabled(True)
        row.addWidget(self.regex_not_edit)
        return row

    def build_prefix_suffix_regex_panel(self):
        panel = QVBoxLayout()
        panel.addLayout(self._build_prefix_row())
        panel.addLayout(self._build_suffix_row())
        panel.addLayout(self._build_regex_row())
        return panel

    def _add_new_window_buttons(self, row_layout):
        new_win_btn = QPushButton("New Window")
        new_win_btn.setToolTip("Open a new window with current query")
        new_win_btn.setFocusPolicy(Qt.NoFocus)
        new_win_btn.clicked.connect(self.open_new_window_with_current_query)
        new_win_sel_btn = QPushButton("New Window from Selection")
        new_win_sel_btn.setToolTip("Use selected text as prefix/suffix/regex in a new window")
        new_win_sel_btn.setFocusPolicy(Qt.NoFocus)
        new_win_sel_btn.clicked.connect(self.open_new_window_from_selection)
        row_layout.addWidget(new_win_btn)
        row_layout.addWidget(new_win_sel_btn)

    def build_query_parameters_panel(self):
        """
        Returns a QHBoxLayout for query parameters:
           - Length specification,
           - Limit spinner,
           - Exclude accepted checkbox,
           - Phonetic Input checkbox,
           - Query button.
        """
        params_row = QHBoxLayout()
        self.length_edit = QLineEdit()
        self.length_edit.setPlaceholderText("e.g., 4-9, 4-, or 7")
        self.length_edit.setText("8-")
        self.limit_spin = QSpinBox()
        self.limit_spin.setMinimum(1)
        self.limit_spin.setMaximum(1000000000)
        self.limit_spin.setValue(1000)
        self.phonetic_cb = QCheckBox("Phonetic Input")
        self.phonetic_cb.setChecked(True)
        self.phonetic_cb.toggled.connect(self.refresh_phonetic_fields)
        self.curated_ratio_spin = QSpinBox()
        self.curated_ratio_spin.setMinimum(0)
        self.curated_ratio_spin.setMaximum(100)
        self.curated_ratio_spin.setValue(20)  # default 20%
        self.query_btn = QPushButton("Query")
        self.query_btn.clicked.connect(self.query_words)
        params_row.addWidget(QLabel("Length:"))
        params_row.addWidget(self.length_edit)
        params_row.addWidget(QLabel("Limit:"))
        params_row.addWidget(self.limit_spin)
        params_row.addWidget(self.phonetic_cb)
        params_row.addWidget(QLabel("Curated %:"))
        params_row.addWidget(self.curated_ratio_spin)
        params_row.addWidget(self.query_btn)
    
        self._add_new_window_buttons(params_row)
        return params_row

    def build_sort_panel(self):
        """
        Returns a QHBoxLayout containing buttons for sorting the table,
        as well as an editable field for a custom sort lambda.
        """
        sort_layout = QHBoxLayout()

        sort_prefix_btn = QPushButton("Sort by Prefix")
        sort_prefix_btn.clicked.connect(self.sort_table_by_prefix)

        sort_suffix_btn = QPushButton("Sort by Suffix")
        sort_suffix_btn.clicked.connect(self.sort_table_by_suffix)

        sort_standard_btn = QPushButton("Sort: Length & Suffix")
        sort_standard_btn.clicked.connect(self.sort_table_by_length_and_suffix)

        custom_sort_label = QLabel("Custom Sort:")
        self.sort_lambda_edit = QLineEdit()
        self.sort_lambda_edit.setPlaceholderText("Enter lambda row: ...")

        custom_sort_apply_btn = QPushButton("Apply Custom Sort")
        custom_sort_apply_btn.clicked.connect(self.apply_custom_sort)

        sort_layout.addWidget(sort_prefix_btn)
        sort_layout.addWidget(sort_suffix_btn)
        sort_layout.addWidget(sort_standard_btn)
        sort_layout.addWidget(custom_sort_label)
        sort_layout.addWidget(self.sort_lambda_edit)
        sort_layout.addWidget(custom_sort_apply_btn)

        return sort_layout

    def build_table_panel(self):
        """
        Creates and returns a QTableWidget configured for displaying the results.
        """
        self.table = QTableWidget(0, 6)
        self.table.setColumnCount(6)  # ensure fixed column count
        self.table.setHorizontalHeaderLabels(["id", "word", "splits", "freq", "glen", "notes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(self.table.DoubleClicked | self.table.SelectedClicked | self.table.EditKeyPressed)
        from PyQt5.QtWidgets import QHeaderView
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(int(28 * self.ui_scale))
        self.table.horizontalHeader().setMinimumHeight(int(30 * self.ui_scale))
        self.table.setItemDelegate(TableEditDelegate(self.table))
        self.table.setColumnHidden(0, False)  # ensure 'id' is visible
        self.table.setColumnWidth(0, 120)
        self.table.cellClicked.connect(self.prefill_find_field)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.table.itemChanged.connect(self.on_cell_changed)  # ADD: track edits
        return self.table

    def build_summary_panel(self):
        panel = QWidget()
        v = QVBoxLayout(panel)

        # Headline
        title = QLabel("Summary")
        title.setStyleSheet("font-weight: bold;")
        v.addWidget(title)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Recompute summary")
        refresh_btn.clicked.connect(self.update_summary)
        v.addWidget(refresh_btn)

        # Stats labels
        self.sum_total_words = QLabel("Total words: 0")
        self.sum_curated_words = QLabel("Curated (distinct): 0")
        self.sum_remaining_words = QLabel("Remaining (distinct): 0")
        self.sum_total_curations = QLabel("Curation entries: 0")

        v.addWidget(self.sum_total_words)
        v.addWidget(self.sum_curated_words)
        v.addWidget(self.sum_remaining_words)
        v.addWidget(self.sum_total_curations)

        # Length distribution table: glen | curated | remaining
        self.len_table = QTableWidget(0, 3)
        self.len_table.setHorizontalHeaderLabels(["glen", "curated", "remaining"])
        from PyQt5.QtWidgets import QHeaderView
        self.len_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.len_table.verticalHeader().setVisible(False)
        v.addWidget(QLabel("Length distribution"))
        v.addWidget(self.len_table)

        v.addStretch()
        return panel

    def prefill_find_field(self, row, col):
        # Only act if the clicked column is the splits column (index 2).
        if col == 2:
            item = self.table.item(row, col)
            if item:
                self.find_edit.setText(item.text())

    def on_cell_changed(self, item):
        if self.suppress_item_changed:
            return
        # Track only changes in the 'splits' column (2)
        if item.column() != 2:
            return
        if getattr(self, "bulk_editing", False):
            # Lightweight tracking only; skip per-row log and painting during bulk ops
            row = item.row()
            id_item = self.table.item(row, 0)
            if id_item:
                rid = id_item.text()
                orig = self.original_splits.get(rid, "")
                if item.text() != orig:
                    self.edited_ids.add(rid)
                    self.dirty = True
            return
        row = item.row()
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        rec_id = id_item.text()
        curr = item.text()
        orig = self.original_splits.get(rec_id, "")
        if curr != orig:
            if rec_id not in self.edited_ids:
                self.edited_ids.add(rec_id)
                self.log_ui_event("EDIT", {"id": rec_id})
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.yellow)
                self.dirty = True
        else:
            if rec_id in self.edited_ids:
                self.edited_ids.remove(rec_id)
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.white)
                self.dirty = bool(self.edited_ids)

    def _collect_query_params(self):
        return {
            "prefix": self.prefix_edit.text().strip(),
            "suffix": self.suffix_edit.text().strip(),
            "regex": self.regex_edit.text().strip(),
            "prefix_not": self.prefix_not_edit.text().strip() if hasattr(self, "prefix_not_edit") else "",
            "suffix_not": self.suffix_not_edit.text().strip() if hasattr(self, "suffix_not_edit") else "",
            "regex_not": self.regex_not_edit.text().strip() if hasattr(self, "regex_not_edit") else "",
            "length_spec": self.length_edit.text().strip(),
            "limit": int(self.limit_spin.value()),
            "curated_ratio": int(self.curated_ratio_spin.value()),
        }

    def _apply_query_params(self, p):
        self.prefix_edit.set_text_tamil(p.get("prefix", ""))
        self.suffix_edit.set_text_tamil(p.get("suffix", ""))
        self.regex_edit.set_text_tamil(p.get("regex", ""))
        if hasattr(self, "prefix_not_edit"):
            self.prefix_not_edit.set_text_tamil(p.get("prefix_not", ""))
        if hasattr(self, "suffix_not_edit"):
            self.suffix_not_edit.set_text_tamil(p.get("suffix_not", ""))
        if hasattr(self, "regex_not_edit"):
            self.regex_not_edit.set_text_tamil(p.get("regex_not", ""))
        self.length_edit.setText(p.get("length_spec", ""))
        self.limit_spin.setValue(int(p.get("limit", self.limit_spin.value())))
        self.curated_ratio_spin.setValue(int(p.get("curated_ratio", self.curated_ratio_spin.value())))

    def open_new_window_with_current_query(self):
        """Spawn a new window, clone current query params, run, and show."""
        params = self._collect_query_params()
        win = MainWindow(ui_scale=self.ui_scale, font_size=self.font_size)
        win._apply_query_params(params)
        win.query_words()
        self.child_windows.append(win)
        win.show()
        self.log_ui_event("NEW_WINDOW", params)

    def _collect_selected_text_from_fields(self):
        for field in (self.prefix_edit, self.suffix_edit, self.regex_edit, self.find_edit, self.replace_edit):
            if isinstance(field, PhoneticLineEdit) and field.hasSelectedText():
                sel = field.selectedText().strip()
                if sel:
                    return sel
        w = QApplication.focusWidget()
        if isinstance(w, PhoneticLineEdit):
            t = (w.selectedText() if w.hasSelectedText() else w.text()).strip()
            if t:
                return t
        return ""

    def _apply_choice_to_params(self, choice, text, base_params):
        p = dict(base_params)
        if choice == "prefix":
            p["prefix"] = text; p["suffix"] = ""; p["regex"] = ""
        elif choice == "suffix":
            p["suffix"] = text; p["prefix"] = ""; p["regex"] = ""
        elif choice == "regex":
            p["regex"] = text; p["prefix"] = ""; p["suffix"] = ""
        elif choice == "not prefix":
            p["prefix_not"] = text
        elif choice == "not suffix":
            p["suffix_not"] = text
        elif choice == "not regex":
            p["regex_not"] = text
        return p

    def open_new_window_from_selection(self):
        text = self._collect_selected_text_from_fields()
        if not text:
            QMessageBox.information(self, "New Window", "No text selected or present in the active field.")
            return
        choice, ok = QInputDialog.getItem(
            self, "New Window", "Use text as:",
            ["prefix", "suffix", "regex", "not prefix", "not suffix", "not regex"],
            0, False
        )
        if not ok:
            return
        params = self._apply_choice_to_params(choice, text, self._collect_query_params())
        win = MainWindow(ui_scale=self.ui_scale, font_size=self.font_size)
        win._apply_query_params(params)
        win.query_words()
        self.child_windows.append(win)
        win.show()
        self.log_ui_event("NEW_WINDOW_SELECTION", {"choice": choice, "text": text, **params})

    def new_window_from_text(self, kind, text):
        """Spawn a new window using 'text' as prefix/suffix/regex or their negatives."""
        params = self._collect_query_params()
        if kind == "prefix":
            params["prefix"] = text; params["suffix"] = ""; params["regex"] = ""
        elif kind == "suffix":
            params["suffix"] = text; params["prefix"] = ""; params["regex"] = ""
        elif kind == "regex":
            params["regex"] = text; params["prefix"] = ""; params["suffix"] = ""
        elif kind == "not prefix":
            params["prefix_not"] = text
        elif kind == "not suffix":
            params["suffix_not"] = text
        elif kind == "not regex":
            params["regex_not"] = text
        win = MainWindow(ui_scale=self.ui_scale, font_size=self.font_size)
        win._apply_query_params(params)
        win.query_words()
        self.child_windows.append(win)
        win.show()
        self.log_ui_event("NEW_WINDOW_CONTEXT", {"kind": kind, "text": text, **params})

    def on_table_context_menu(self, pos):
        """Right-click on table: open menu to launch a new window using the clicked cell text as prefix/suffix/regex."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row, col = index.row(), index.column()
        editor = self.table.focusWidget()
        if isinstance(editor, QLineEdit) and editor.hasSelectedText():
            text = editor.selectedText().strip()
        else:
            item = self.table.item(row, col)
            text = item.text().strip() if item else ""
            if not text:
                wi = self.table.item(row, 1)
                text = wi.text().strip() if wi else ""
        if not text:
            return
        menu = QMenu(self)
        for kind, label in (("prefix", "Prefix"), ("suffix", "Suffix"), ("regex", "Regex")):
            act = QAction(f"New Window as {label}: {text}", self)
            act.triggered.connect(lambda _, k=kind: self.new_window_from_text(k, text))
            menu.addAction(act)
        menu.addSeparator()
        for kind, label in (("not_prefix", "Exclude Prefix"), ("not_suffix", "Exclude Suffix"), ("not_regex", "Exclude Regex")):
            act = QAction(f"New Window as {label}: {text}", self)
            act.triggered.connect(lambda _, k=kind: self.new_window_from_text(k, text))
            menu.addAction(act)
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _compute_summary_sets(self):
        glen_map = self.word_index.glen_map
        index_words = self.word_index.index_words
        curated_set = getattr(self.curated, "curated_words", set())
        curated_in_index = {w for w in curated_set if w in index_words}
        remaining_set = index_words - curated_in_index
        return glen_map, index_words, curated_in_index, remaining_set

    def _update_summary_labels(self, total_words, curated_distinct, remaining_distinct, total_curations):
        self.sum_total_words.setText(f"Total words: {total_words}")
        self.sum_curated_words.setText(f"Curated (distinct): {curated_distinct}")
        self.sum_remaining_words.setText(f"Remaining (distinct): {remaining_distinct}")
        self.sum_total_curations.setText(f"Curation entries: {total_curations}")

    def _populate_length_table(self, glen_map, curated_in_index, remaining_set):
        curated_len = Counter()
        for w in curated_in_index:
            gl = glen_map.get(w)
            if gl is not None:
                curated_len[gl] += 1
        remaining_len = Counter()
        for w in remaining_set:
            gl = glen_map.get(w)
            if gl is not None:
                remaining_len[gl] += 1
        lengths = sorted(set(curated_len.keys()) | set(remaining_len.keys()))
        self.len_table.setRowCount(0)
        for gl in lengths:
            row = self.len_table.rowCount()
            self.len_table.insertRow(row)
            self.len_table.setItem(row, 0, QTableWidgetItem(str(gl)))
            self.len_table.setItem(row, 1, QTableWidgetItem(str(curated_len.get(gl, 0))))
            self.len_table.setItem(row, 2, QTableWidgetItem(str(remaining_len.get(gl, 0))))

    def update_summary(self):
        glen_map, index_words, curated_in_index, remaining_set = self._compute_summary_sets()
        total_words = len(index_words)
        curated_distinct = len(curated_in_index)
        remaining_distinct = len(remaining_set)
        total_curations = getattr(self.curated, "total_curation_entries", 0)
        self._update_summary_labels(total_words, curated_distinct, remaining_distinct, total_curations)
        self._populate_length_table(glen_map, curated_in_index, remaining_set)

if __name__ == "__main__":
    import argparse, os
    from tools.profile import default_profile, Profile
    parser = argparse.ArgumentParser(description="Tamil Splits GUI Client")
    parser.add_argument("--profile", default="default", help="Profile name")
    parser.add_argument("--base_dir", default=None, help="Optional base directory")
    parser.add_argument("--ui_scale", type=float, default=1.0, help="UI scale multiplier for fonts and sizes (e.g., 1.25)")
    parser.add_argument("--font_size", type=int, default=None, help="Base font size in points (overrides ui_scale-derived size)")
    args = parser.parse_args()
    profile = Profile(name=args.profile, base_dir=args.base_dir)
    import os
    LEDGER_PATH = os.path.abspath(profile.ledger_path)
    WORDLIST_PATH = os.path.abspath(profile.wordlist_path)
    BATCHES_DIR = os.path.abspath(profile.batches_dir)
    UI_LOG_PATH = os.path.abspath(profile.ui_log_path)
    REMINDERS_PATH = os.path.abspath(profile.reminders_path)

    app = QApplication(sys.argv)
    from PyQt5.QtGui import QFont
    if args.font_size:
        f = app.font()
        f.setPointSize(int(args.font_size))
        app.setFont(f)
    window = MainWindow(ui_scale=args.ui_scale, font_size=args.font_size)
    window.resize(1024, 600)
    window.show()
    sys.exit(app.exec_())
