#!/usr/bin/env python3
import logging
import time
import string
import sys, socket

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QMenu, QAction, QMessageBox, QAbstractItemView, QInputDialog, QShortcut as MyShortcut
)

from urllib.parse import quote  # for percent encoding parameters

from tools.tamil_phonetic import transliterate, PHONETIC_VOWELS, CONSONANTS
from tools.word_indexer import WordIndex

BATCHES_DIR = "data/batches"
LEDGER_PATH = "data/splits-ledger.tsv"
WORDLIST_PATH = "data/word-index.tsv"
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
    def __init__(self, socket_path="run/tamil-words.sock", mode="server"):
        super().__init__()
        self.socket_path = socket_path
        self.mode = mode  # mode: either "server" or "local"
        if self.mode == "local":
            self.batch_dir = BATCHES_DIR
            import os
            os.makedirs(self.batch_dir, exist_ok=True)
        self.wordlist_path = WORDLIST_PATH
        self.word_index = WordIndex(self.wordlist_path)
        self.setWindowTitle("Tamil Splits - Qt Client")
        central = QWidget()
        self.setCentralWidget(central)
        # Main vertical layout
        main_layout = QVBoxLayout(central)


        ###############################
        # New Panel: Prefix, Suffix, and Regex panels (in separate rows)
        ###############################
        prefix_suffix_panel = QVBoxLayout()

        # Row for prefix:
        prefix_row = QHBoxLayout()
        self.prefix_edit = PhoneticLineEdit(self)
        self.prefix_edit.setUndoRedoEnabled(True)
        prefix_row.addWidget(QLabel("Prefix:"))
        prefix_row.addWidget(self.prefix_edit)
        prefix_suffix_panel.addLayout(prefix_row)

        # Row for suffix:
        suffix_row = QHBoxLayout()
        self.suffix_edit = PhoneticLineEdit(self)
        self.suffix_edit.setUndoRedoEnabled(True)
        suffix_row.addWidget(QLabel("Suffix:"))
        suffix_row.addWidget(self.suffix_edit)
        prefix_suffix_panel.addLayout(suffix_row)

        # Row for regex:
        regex_row = QHBoxLayout()
        self.regex_edit = PhoneticLineEdit(self)
        self.regex_edit.setPlaceholderText("Regex (optional)")
        self.regex_edit.setUndoRedoEnabled(True)
        regex_row.addWidget(QLabel("Regex:"))
        regex_row.addWidget(self.regex_edit)
        prefix_suffix_panel.addLayout(regex_row)

        main_layout.addLayout(prefix_suffix_panel)


        ###############################
        # New Panel: Other query parameters
        ###############################
        params_row = QHBoxLayout()
        self.length_edit = QLineEdit()
        self.length_edit.setPlaceholderText("e.g., 4-9, 4-, or 7")
        self.length_edit.setText("8-")  # Default value, adjust as desired.
        self.limit_spin = QSpinBox()
        self.limit_spin.setMinimum(1)
        self.limit_spin.setMaximum(10000)
        self.limit_spin.setValue(500)
        self.exclude_cb = QCheckBox("Exclude accepted")
        self.phonetic_cb = QCheckBox("Phonetic Input")
        self.phonetic_cb.setChecked(True)
        self.phonetic_cb.toggled.connect(self.refresh_phonetic_fields)
        self.query_btn = QPushButton("Query")
        self.query_btn.clicked.connect(self.query_words)
        params_row.addWidget(QLabel("Min length:"))
        params_row.addWidget(self.length_edit)
        params_row.addWidget(QLabel("Limit:"))
        params_row.addWidget(self.limit_spin)
        params_row.addWidget(self.exclude_cb)
        params_row.addWidget(self.phonetic_cb)
        params_row.addWidget(self.query_btn)
        main_layout.addLayout(params_row)

        ###############################
        # Find/Replace Panel (moved to the very top)
        ###############################
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
        main_layout.addLayout(find_layout)

        ###############################
        # Sort Panel: Sort by Prefix and Sort by Suffix
        ###############################
        sort_layout = QHBoxLayout()
        sort_prefix_btn = QPushButton("Sort by Prefix")
        sort_prefix_btn.clicked.connect(self.sort_table_by_prefix)
        sort_suffix_btn = QPushButton("Sort by Suffix")
        sort_suffix_btn.clicked.connect(self.sort_table_by_suffix)
        sort_layout.addWidget(sort_prefix_btn)
        sort_layout.addWidget(sort_suffix_btn)
        main_layout.addLayout(sort_layout)
        from PyQt5.QtGui import QKeySequence
        MyShortcut(QKeySequence("Alt+P"), self, activated=self.sort_table_by_prefix)
        MyShortcut(QKeySequence("Alt+S"), self, activated=self.sort_table_by_suffix)

        ###############################
        # Table display (below the top panels)
        ###############################
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["id", "split", "freq", "glen", "status", "notes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(self.table.DoubleClicked | self.table.SelectedClicked | self.table.EditKeyPressed)
        from PyQt5.QtWidgets import QHeaderView
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        main_layout.addWidget(self.table)

        # Allow custom context menu on the table.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        self.table.cellClicked.connect(self.prefill_find_field)
        # Add shortcut to toggle ignore status for selected rows.
        ignore_action = QAction("Toggle Ignore", self)
        ignore_action.setShortcut("I")
        ignore_action.triggered.connect(self.toggle_ignore_for_selected)
        self.addAction(ignore_action)

        # (Query button connected earlier in the params panel.)
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtWidgets import QInputDialog
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
        # Get values from UI fields.
        prefix = self.prefix_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        regex = self.regex_edit.text().strip()
        length_spec = self.length_edit.text().strip()  # new length specification field
        limit = self.limit_spin.value()
        exclude = self.exclude_cb.isChecked()  # boolean

        min_len, max_len = self.parse_length_spec(length_spec)

        def exclude_fn(word):
            return exclude and (word in self.accepted_words())

        results = self.word_index.query_words(
            prefix=prefix,
            suffix=suffix,
            min_len=min_len,
            max_len=max_len,
            limit=limit,
            offset=0,
            exclude_fn=exclude_fn,
            regex=regex
        )
        self.populate_table_from_results(results)

    def build_tsv_lines(self):
        """
        Builds a list of strings representing TSV lines from the current table data.
        The first line is the header: "id\tsplit\tfreq\tglen\tstatus\tnotes"
        """
        lines = []
        header = "\t".join(["id", "split", "freq", "glen", "status", "notes"])
        lines.append(header)
        row_count = self.table.rowCount()
        col_count = self.table.columnCount()  # expected 6 columns
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
        Each ledger line includes the timestamp, batch name, id, split, status, and notes.
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
                    # Write ledger header: timestamp, batch, id, split, status, notes
                    lf.write("\t".join(["timestamp", "batch", "id", "split", "status", "notes"]) + "\n")
                for ln in tsv_lines[1:]:
                    if not ln.strip():
                        continue
                    cols = ln.split("\t")
                    rec_id = cols[0].strip()
                    split_text = cols[1].strip()
                    status = cols[4].strip() or "todo"
                    notes = cols[5].strip() if len(cols) > 5 else ""
                    lf.write(f"{ts}\t{batch_name}\t{rec_id or split_text}\t{split_text}\t{status}\t{notes}\n")
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


    def generate_batch_name(self):
       # Compute a default batch name in the format:
       # {timestamp}-{prefix}{min_len}{suffix}.tsv
       timestamp = time.strftime("%Y%m%dT%H%M%S", time.localtime())
       prefix = self.prefix_edit.text().strip()
       suffix = self.suffix_edit.text().strip()
       length_spec = self.length_edit.text().strip()
       # Remove any characters that might interfere with filenames.
       safe_prefix = "".join(c for c in prefix if c.isalnum())
       safe_suffix = "".join(c for c in suffix if c.isalnum())
       return f"{timestamp}-{safe_prefix}-{length_spec}-{safe_suffix}.tsv"

    def commit_edits(self):
        default_batch_name = self.generate_batch_name()

        if self.mode == "local":
            batch_name = default_batch_name
        else:
            batch_name, ok = QInputDialog.getText(
                self, "Batch Name", "Enter batch name:", text=default_batch_name)
            if not ok or not batch_name.strip():
                return
            batch_name = batch_name.strip()

        tsv_lines = self.build_tsv_lines()

        if self.mode == "local":
            filepath = f"{self.batch_dir}/{batch_name}"
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("\n".join(tsv_lines) + "\n")
                QMessageBox.information(self, "Commit",
                                        f"Edits committed locally to {filepath}")
                self.update_ledger(tsv_lines, batch_name)
            except Exception as e:
                QMessageBox.critical(self, "Commit Error", str(e))
        else:
            cmd = f"COMMIT batch={quote(batch_name)} rows={len(tsv_lines)}"
            try:
                response = self.send_command(cmd, tsv_lines)
                QMessageBox.information(self, "Commit", response)
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
        self.table.setRowCount(0)
        for row_data in data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(row_data):
                new_item = QTableWidgetItem(text)
                new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
                self.table.setItem(row, col, new_item)
        self.table.resizeColumnsToContents()

    def populate_table_from_results(self, results):
        self.table.setRowCount(0)
        for rec in results:
            # For local word index, we assume rec has 3 elements; default id is the word.
            if len(rec) == 3:
                split_text, freq, glen = rec
                rec_id = split_text
            elif len(rec) >= 4:
                rec_id, split_text, freq, glen = rec[:4]
            else:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rec_id))
            self.table.setItem(row, 1, QTableWidgetItem(split_text))
            self.table.setItem(row, 2, QTableWidgetItem(str(freq)))
            self.table.setItem(row, 3, QTableWidgetItem(str(glen)))
            self.table.setItem(row, 4, QTableWidgetItem("todo"))  # status
            self.table.setItem(row, 5, QTableWidgetItem(""))       # notes
        self.table.resizeColumnsToContents()

    def populate_table_from_results(self, results):
        self.table.setRowCount(0)
        for rec in results:
            # For local word index, we assume rec has 3 elements; default id is the word.
            if len(rec) == 3:
                split_text, freq, glen = rec
                rec_id = split_text
            elif len(rec) >= 4:
                rec_id, split_text, freq, glen = rec[:4]
            else:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rec_id))
            self.table.setItem(row, 1, QTableWidgetItem(split_text))
            self.table.setItem(row, 2, QTableWidgetItem(str(freq)))
            self.table.setItem(row, 3, QTableWidgetItem(str(glen)))
            self.table.setItem(row, 4, QTableWidgetItem("todo"))  # status
            self.table.setItem(row, 5, QTableWidgetItem(""))       # notes

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

    def send_command(self, command, body=None):
        """Connect to the Unix domain socket and send a command, reading the full response."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(self.socket_path)
        except Exception as e:
            raise Exception(f"Could not connect to socket {self.socket_path}: {e}")

        full_cmd = command + "\n"
        if body:
            full_cmd += "\n".join(body) + "\n"
        client.sendall(full_cmd.encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        response = b""
        while True:
            data = client.recv(4096)
            if not data:
                break
            response += data
        client.close()
        return response.decode("utf-8")

    def show_table_context_menu(self, pos):
        # Map viewport position to global.
        global_pos = self.table.viewport().mapToGlobal(pos)
        # Determine the row that was right-clicked.
        item = self.table.itemAt(pos)
        if not item:
            return
        clicked_row = item.row()
        # If the clicked row is not already selected, select it.
        if not self.table.selectionModel().isRowSelected(clicked_row, self.table.rootIndex()):
            self.table.clearSelection()
            self.table.selectRow(clicked_row)
        # Get the set of selected rows.
        selected_rows = self.table.selectionModel().selectedRows()
        # Determine the appropriate action text.
        # For simplicity, if all selected rows have status "ignored",
        # then the action becomes "Unmark as Ignored".
        # Otherwise, use "Mark as Ignored".
        all_ignored = True
        for index in selected_rows:
            row = index.row()
            status_item = self.table.item(row, 5)
            status_text = status_item.text().strip().lower() if status_item else ""
            if status_text != "ignored":
                all_ignored = False
                break
        action_text = "Unmark as Ignored" if all_ignored else "Mark as Ignored"
        # Create a QMenu with the toggle action.
        menu = QMenu()
        toggle_action = menu.addAction(action_text)
        chosen = menu.exec_(global_pos)
        if chosen == toggle_action:
            self.toggle_ignore_for_selected()

    def toggle_ignore_status(self, row):
        # Column 5 holds the status.
        status_item = self.table.item(row, 5)
        if not status_item:
            status_item = QTableWidgetItem("")
            self.table.setItem(row, 5, status_item)
        current_status = status_item.text().strip().lower()
        if current_status == "ignored":
            new_status = "todo"
        else:
            new_status = "ignored"
        status_item.setText(new_status)
        # Optionally, visually mark the row.
        color = Qt.lightGray if new_status == "ignored" else Qt.white
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)

    def toggle_ignore_for_selected(self):
        # Use the selection model to get a list of selected rows.
        selected_indexes = self.table.selectionModel().selectedRows()
        for index in selected_indexes:
            row = index.row()
            self.toggle_ignore_status(row)

    def apply_replace_to_cell(self):
        """
        Applies a find and replace operation on the currently selected cell
        in the split column (column index 1). It replaces all occurrences of
        the text in self.find_edit with the text in self.replace_edit.
        """
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if not find_text:
            QMessageBox.warning(self, "Find/Replace", "Please enter text to find.")
            return
        indexes = self.table.selectedIndexes()
        # Filter for cells in column 1 (split column)
        target_indexes = [ix for ix in indexes if ix.column() == 1]
        if not target_indexes:
            QMessageBox.warning(self, "Find/Replace", "Please select a cell in the split column.")
            return
        # For each selected cell in column 1, perform find/replace.
        for ix in target_indexes:
            row = ix.row()
            item = self.table.item(row, 1)
            if item:
                original_text = item.text()
                new_text = original_text.replace(find_text, replace_text)
                item.setText(new_text)
        QMessageBox.information(self, "Find/Replace", "Replacement applied.")

    def sort_table_by_prefix(self):
        """Sorts the table rows by the 'id' cell (column 0) in lexicographical order."""
        data = self.get_table_data()
        sorted_data = sorted(data, key=lambda row: row[0].lower())
        self.set_table_data(sorted_data)

    def sort_table_by_suffix(self):
        """Sorts the table rows by the 'id' cell (column 0) in suffix order (based on reversed text)."""
        data = self.get_table_data()
        sorted_data = sorted(data, key=lambda row: row[0][::-1].lower() if row[0] else "")
        self.set_table_data(sorted_data)

    def prefill_find_field(self, row, col):
        # Only act if the clicked column is the split column (index 1).
        if col == 1:
            item = self.table.item(row, col)
            if item:
                self.find_edit.setText(item.text())

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tamil Splits GUI Client")
    parser.add_argument("--socket", default="run/tamil-words.sock", help="Path to Unix domain socket")
    parser.add_argument("--mode", default="server", choices=["server", "local"],
                        help="Operation mode: 'server' (commit via socket) or 'local' (write to file)")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = MainWindow(socket_path=args.socket, mode=args.mode)
    window.resize(1024, 600)
    window.show()
    sys.exit(app.exec_())
