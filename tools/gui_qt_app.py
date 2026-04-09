#!/usr/bin/env python3
import logging
import time
import string
import sys
import random
import math

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QMessageBox, QAbstractItemView, QShortcut as MyShortcut
)


from tools.tamil_phonetic import transliterate, PHONETIC_VOWELS, CONSONANTS
from tools.curation_index import CuratedIndex
from tools.word_indexer import WordIndex

BATCHES_DIR = "data/batches"
LEDGER_PATH = "data/splits-ledger.tsv"
WORDLIST_PATH = "data/word-index.tsv"
UI_LOG_PATH = "data/ui-log.tsv"
class PhoneticLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Holds the committed text (already converted Tamil characters)
        self.committed = ""
        # Holds the composition in progress as a roman sequence
        self.composition = ""

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

    def update_display(self):
        """
        Update the QLineEdit display with the transliteration of (committed + composition).
        In our desired behavior, every consonant is rendered with a pulli by default unless
        a vowel has been typed. So if the current composition is nonempty and does not end with
        any vowel (as defined in PHONETIC_VOWELS), we force-add a pulli ("்") to the displayed text.
        """
        # Get the interactive transliteration of our current (raw) composition.
        current_disp = transliterate(self.composition)
        # Check if the current composition is nonempty and does NOT end with a vowel token.
        incomplete = False
        if self.composition:
            # Look for any vowel token that could appear at the end.
            if not any(self.composition.lower().endswith(vt) for vt in PHONETIC_VOWELS.keys()):
                incomplete = True
        # If incomplete, ensure that current_disp ends with a pulli.
        if incomplete and self.composition:
            if not current_disp.endswith("்"):
                current_disp += "்"
        # The final display is the concatenation of committed (already fixed) plus
        # the current composition (which may have been adjusted to show pulli).
        disp = self.committed + current_disp
        self.setText(disp)
        self.setCursorPosition(len(disp))
        logging.debug("Display updated: '%s' (committed: '%s', composition: '%s')",
                      disp, self.committed, self.composition)

    def keyPressEvent(self, event):
        key = event.key()
        ch = event.text()
        logging.debug("Key press: key=%s, text='%s', current composition='%s', committed='%s'",
                      key, ch, self.composition, self.committed)

        # Check if the cursor is not at the end or if there is any selected text.
        if (self.hasSelectedText() or self.cursorPosition() < len(self.text())):
            super().keyPressEvent(event)
            new_text = self.text()
            self.committed = new_text
            self.composition = ""
            logging.debug("Default behavior used. New text: '%s'", new_text)
            return

        if key == Qt.Key_Backspace:
            if self.composition:
                self.composition = self.composition[:-1]
                logging.debug("Backspace: New composition='%s'", self.composition)
            else:
                self.committed = self.committed[:-1]
                logging.debug("Backspace: Removed last char from committed, new committed='%s'", self.committed)
            self.update_display()
            event.accept()
            return
        elif key == Qt.Key_Delete:
            if self.composition:
                self.composition = ""
                logging.debug("Delete: Cleared composition")
            else:
                self.committed = self.committed[:-1]
                logging.debug("Delete: Removed last char from committed, new committed='%s'", self.committed)
            self.update_display()
            event.accept()
            return
        elif ch and (ch in string.whitespace or ch in string.punctuation):
            logging.debug("Boundary key pressed: '%s'", ch)
            self.commit_composition()
            self.committed += ch
            self.update_display()
            event.accept()
            return
        elif ch and ch.isalnum():
            candidate = self.composition + ch
            if self.is_possible_prefix(candidate):
                self.composition = candidate
                logging.debug("Accepted key, new composition='%s'", self.composition)
            else:
                logging.debug("Candidate '%s' not possible, committing current composition", candidate)
                self.commit_composition()
                if self.is_possible_prefix(ch):
                    self.composition = ch
                    logging.debug("Starting new composition with '%s'", ch)
                else:
                    self.committed += ch
                    logging.debug("Appending '%s' to committed", ch)
            self.update_display()
            event.accept()
            return
        else:
            super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """
        Handle paste events so that the pasted text replaces the selected text
        and the internal state is updated accordingly.
        """
        pasted_text = source.text()
        if self.hasSelectedText():
            cursor_pos = self.cursorPosition()
            current_text = self.text()
            sel_start = self.selectionStart()
            sel_end = sel_start + len(self.selectedText())
            new_text = current_text[:sel_start] + pasted_text + current_text[sel_end:]
        else:
            new_text = self.text()[:self.cursorPosition()] + pasted_text + self.text()[self.cursorPosition():]
        self.committed = new_text
        self.composition = ""
        self.setText(new_text)
        self.setCursorPosition(sel_start + len(pasted_text) if self.hasSelectedText() else len(new_text))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        import os
        import os
        self.batch_dir = os.path.abspath(BATCHES_DIR)
        logging.info("Batches directory: %s", self.batch_dir)
        os.makedirs(self.batch_dir, exist_ok=True)
        self.wordlist_path = WORDLIST_PATH
        self.word_index = WordIndex(self.wordlist_path)
        self.curated = CuratedIndex(self.batch_dir)
        self.curated.reload()
        logging.info("Curated index (from batches) loaded: %d word(s)", self.curated.curated_count)
        self.setWindowTitle("Tamil Splits - Qt Client")
        central = QWidget()
        self.setCentralWidget(central)
        # Main vertical layout
        main_layout = QVBoxLayout(central)

        # Build and add individual panels:
        main_layout.addLayout(self.build_prefix_suffix_regex_panel())
        main_layout.addLayout(self.build_query_parameters_panel())
        main_layout.addLayout(self.build_sort_panel())
        main_layout.addWidget(self.build_table_panel())
        self.original_splits = {}
        self.edited_ids = set()
        self.suppress_item_changed = False
        self.table.itemChanged.connect(self.on_cell_changed)
        main_layout.addLayout(self.build_find_replace_panel())

        # (Query button connected earlier in the params panel.)
        from PyQt5.QtGui import QKeySequence
        commit_shortcut = MyShortcut(QKeySequence("Ctrl+S"), self, activated=self.commit_edits)
        # Focus Shortcuts
        MyShortcut(QKeySequence("Alt+P"), self, activated=lambda: self.prefix_edit.setFocus())
        MyShortcut(QKeySequence("Alt+S"), self, activated=lambda: self.suffix_edit.setFocus())
        MyShortcut(QKeySequence("Alt+R"), self, activated=lambda: self.regex_edit.setFocus())
        MyShortcut(QKeySequence("Alt+F"), self, activated=lambda: self.find_edit.setFocus())
        MyShortcut(QKeySequence("Alt+G"), self, activated=lambda: self.replace_edit.setFocus())
        MyShortcut(QKeySequence("Alt+L"), self, activated=lambda: self.length_edit.setFocus())
        MyShortcut(QKeySequence("Alt+I"), self, activated=lambda: self.limit_spin.setFocus())
        MyShortcut(QKeySequence("Alt+Q"), self, activated=lambda: self.query_btn.setFocus())

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

    def query_words(self):
        self.curated.maybe_reload_on_change()
        # Get values from UI fields.
        prefix = self.prefix_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        regex = self.regex_edit.text().strip()
        length_spec = self.length_edit.text().strip()  # new length specification field
        limit = self.limit_spin.value()

        min_len, max_len = self.parse_length_spec(length_spec)

        self.log_ui_event("QUERY", {"prefix": prefix, "suffix": suffix, "regex": regex, "length_spec": length_spec, "limit": limit})

        # Probe more than limit to have headroom for filtering curated words
        probe_limit = min(limit * 5, max(limit + 500, 5000))
        raw = self.word_index.query_words(
            prefix=prefix,
            suffix=suffix,
            min_len=min_len,
            max_len=max_len,
            limit=probe_limit,
            offset=0,
            regex=regex
        )
        # Partition results into new (uncurated) and curated
        new_rows = []
        old_rows = []
        for w, fr, gl in raw:
            (new_rows if not self.curated.is_curated(w) else old_rows).append((w, fr, gl))

        # Always include ~20% curated, at least 1 if any curated exist
        curated_ratio = 0.20
        curated_quota = int(math.floor(limit * curated_ratio))
        if old_rows and curated_quota < 1:
            curated_quota = 1

        # Randomly pick curated rows for this query
        curated_pick = []
        if old_rows and curated_quota > 0:
            curated_pick = random.sample(old_rows, k=min(curated_quota, len(old_rows)))

        # Fill remaining with new (front-load new)
        remaining_slots = max(0, limit - len(curated_pick))
        new_pick = new_rows[:remaining_slots]

        # If still short, backfill with additional curated (excluding those already picked)
        leftover = max(0, limit - (len(curated_pick) + len(new_pick)))
        if leftover > 0:
            remaining_old = [r for r in old_rows if r not in curated_pick]
            if remaining_old:
                curated_pick += random.sample(remaining_old, k=min(leftover, len(remaining_old)))

        # Final order: new first, then curated
        combined = (new_pick + curated_pick)[:limit]

        shown_new = len(new_pick)
        shown_curated = len(curated_pick)
        self.log_ui_event("FILTER_CURATED", {
            "queried": len(raw),
            "new": len(new_rows),
            "curated": len(old_rows),
            "shown_new": shown_new,
            "shown_curated": shown_curated,
            "curated_ratio": curated_ratio
        })
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

    def commit_edits(self):
        # Collect only rows whose 'splits' were edited
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
        if not edited_rows:
            QMessageBox.information(self, "Commit", "No edits to save.")
            return
        default_batch_name = self.generate_batch_name()
        batch_name = default_batch_name
        tsv_lines = ["\t".join(["id","word","splits","freq","glen","notes"])]
        tsv_lines.extend("\t".join(r) for r in edited_rows)
        import os
        filepath = os.path.abspath(os.path.join(self.batch_dir, batch_name))
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(tsv_lines) + "\n")
            self.update_ledger(tsv_lines, batch_name)
            self.curated.update_from_batch(tsv_lines)
            self.log_ui_event("COMMIT", {"batch": batch_name, "saved_rows": len(edited_rows)})
            logging.info("Saved batch file to %s", filepath)
            QMessageBox.information(self, "Commit", f"Saved {len(edited_rows)} edited row(s) to {filepath}")
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


    def populate_table_from_results(self, results):
        # Suppress change tracking while loading
        self.suppress_item_changed = True
        self.original_splits = {}
        self.edited_ids = set()
        self.table.setColumnCount(6)
        self.table.setRowCount(0)
        for rec in results:
            # Normalize inputs: extract word, freq, glen, optional splits
            if len(rec) == 3:
                word, freq, glen = rec
                splits = word  # default splits to word
            elif len(rec) >= 5:
                # Assume 7-col order from prior formats: id, word, splits, freq, glen, ...
                word = rec[1]
                splits = rec[2] if rec[2] else rec[1]
                freq = rec[3]
                glen = rec[4]
            elif len(rec) == 4:
                # Assume order: id, word, freq, glen
                word = rec[1]
                freq = rec[2]
                glen = rec[3]
                splits = word
            else:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            rec_id = str(row + 1)  # numeric (stringified) sequential id

            # 6-column order: id, word, splits, freq, glen, notes
            self.table.setItem(row, 0, QTableWidgetItem(rec_id))
            self.table.setItem(row, 1, QTableWidgetItem(word))
            self.table.setItem(row, 2, QTableWidgetItem(splits))
            self.table.setItem(row, 3, QTableWidgetItem(str(freq)))
            self.table.setItem(row, 4, QTableWidgetItem(str(glen)))
            self.table.setItem(row, 5, QTableWidgetItem(""))  # notes

            # Record original splits for edit tracking
            self.original_splits[rec_id] = splits

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
    def refresh_phonetic_fields(self):
        for field in (self.prefix_edit, self.suffix_edit, self.regex_edit):
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






    def apply_replace_to_cell(self):
        """
        Applies a find and replace operation on the currently selected cell(s)
        in the splits column (column index 2). If no cells are selected, the replacement is applied to all cells in that column.
        """
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if not find_text:
            QMessageBox.warning(self, "Find/Replace", "Please enter text to find.")
            return

        indexes = self.table.selectedIndexes()
        # Filter for cells in column 2 (the splits column)
        target_indexes = [ix for ix in indexes if ix.column() == 2]

        if not target_indexes:
            # No cells are selected. Replace in all cells in the splits column.
            target_indexes = []
            for row in range(self.table.rowCount()):
                # Obtain the model index for column 2
                target_indexes.append(self.table.model().index(row, 2))

        if not target_indexes:
            QMessageBox.warning(self, "Find/Replace", "No cells available in the splits column.")
            return

        count_replaced = 0
        for ix in target_indexes:
            row = ix.row()
            item = self.table.item(row, 2)
            if item:
                original_text = item.text()
                new_text = original_text.replace(find_text, replace_text)
                if new_text != original_text:
                    count_replaced += 1
                item.setText(new_text)

        if count_replaced > 0:
            self.log_ui_event("REPLACE", {
                "find": find_text,
                "replace": replace_text,
                "cells_modified": count_replaced
            })
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

    def build_prefix_suffix_regex_panel(self):
        """
        Returns a QVBoxLayout containing three rows:
           - one for Prefix,
           - one for Suffix,
           - one for Regex.
        """
        panel = QVBoxLayout()
        # Row for Prefix:
        prefix_row = QHBoxLayout()
        self.prefix_edit = PhoneticLineEdit(self)
        self.prefix_edit.setUndoRedoEnabled(True)
        prefix_row.addWidget(QLabel("Prefix:"))
        prefix_row.addWidget(self.prefix_edit)
        panel.addLayout(prefix_row)
        # Row for Suffix:
        suffix_row = QHBoxLayout()
        self.suffix_edit = PhoneticLineEdit(self)
        self.suffix_edit.setUndoRedoEnabled(True)
        suffix_row.addWidget(QLabel("Suffix:"))
        suffix_row.addWidget(self.suffix_edit)
        panel.addLayout(suffix_row)
        # Row for Regex:
        regex_row = QHBoxLayout()
        self.regex_edit = PhoneticLineEdit(self)
        self.regex_edit.setPlaceholderText("Regex (optional)")
        self.regex_edit.setUndoRedoEnabled(True)
        regex_row.addWidget(QLabel("Regex:"))
        regex_row.addWidget(self.regex_edit)
        panel.addLayout(regex_row)
        return panel

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
        self.limit_spin.setMaximum(10000)
        self.limit_spin.setValue(500)
        self.phonetic_cb = QCheckBox("Phonetic Input")
        self.phonetic_cb.setChecked(True)
        self.phonetic_cb.toggled.connect(self.refresh_phonetic_fields)
        self.query_btn = QPushButton("Query")
        self.query_btn.clicked.connect(self.query_words)
        params_row.addWidget(QLabel("Length:"))
        params_row.addWidget(self.length_edit)
        params_row.addWidget(QLabel("Limit:"))
        params_row.addWidget(self.limit_spin)
        params_row.addWidget(self.phonetic_cb)
        params_row.addWidget(self.query_btn)
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
        self.table.setColumnHidden(0, False)  # ensure 'id' is visible
        self.table.setColumnWidth(0, 120)
        self.table.cellClicked.connect(self.prefill_find_field)
        return self.table

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
        else:
            if rec_id in self.edited_ids:
                self.edited_ids.remove(rec_id)
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(Qt.white)

if __name__ == "__main__":
    import argparse, os
    from tools.profile import default_profile, Profile
    parser = argparse.ArgumentParser(description="Tamil Splits GUI Client")
    parser.add_argument("--profile", default="default", help="Profile name")
    parser.add_argument("--base_dir", default=None, help="Optional base directory")
    args = parser.parse_args()
    profile = Profile(name=args.profile, base_dir=args.base_dir)
    import os
    LEDGER_PATH = os.path.abspath(profile.ledger_path)
    WORDLIST_PATH = os.path.abspath(profile.wordlist_path)
    BATCHES_DIR = os.path.abspath(profile.batches_dir)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1024, 600)
    window.show()
    sys.exit(app.exec_())
