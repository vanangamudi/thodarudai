#!/usr/bin/env python3
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
import sys, socket
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt
from tools.tamil_phonetic import transliterate
from urllib.parse import quote  # for percent encoding parameters

import string
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtCore import Qt
from tools.tamil_phonetic import transliterate, PHONETIC_VOWELS, CONSONANTS

class PhoneticLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Holds the committed text (already converted Tamil characters)
        self.committed = ""
        # Holds the composition in progress as a roman sequence
        self.composition = ""

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

class MainWindow(QMainWindow):
    def __init__(self, socket_path="run/tamil-words.sock"):
        super().__init__()
        self.socket_path = socket_path
        self.setWindowTitle("Tamil Splits - Qt Client")
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Parameter input area.
        param_layout = QHBoxLayout()
        self.prefix_edit = PhoneticLineEdit(self)
        self.suffix_edit = PhoneticLineEdit(self)
        self.regex_edit = PhoneticLineEdit(self)
        self.min_len_spin = QSpinBox()
        self.min_len_spin.setMinimum(1)
        self.min_len_spin.setValue(10)
        self.limit_spin = QSpinBox()
        self.limit_spin.setMinimum(1)
        self.limit_spin.setValue(200)
        self.exclude_cb = QCheckBox("Exclude accepted")
        # NEW: add a checkbox for phonetic input mode.
        self.phonetic_cb = QCheckBox("Phonetic Input")
        self.phonetic_cb.setChecked(True)
        # Connect textEdited signals for realtime transliteration when phonetic mode is on.

        # Also, when the phonetic checkbox is toggled, update the fields immediately.
        self.phonetic_cb.toggled.connect(self.refresh_phonetic_fields)
        query_btn = QPushButton("Query")

        param_layout.addWidget(QLabel("Prefix:"))
        param_layout.addWidget(self.prefix_edit)
        param_layout.addWidget(QLabel("Suffix:"))
        param_layout.addWidget(self.suffix_edit)
        param_layout.addWidget(QLabel("Regex:"))
        param_layout.addWidget(self.regex_edit)
        param_layout.addWidget(QLabel("Min length:"))
        param_layout.addWidget(self.min_len_spin)
        param_layout.addWidget(QLabel("Limit:"))
        param_layout.addWidget(self.limit_spin)
        param_layout.addWidget(self.exclude_cb)
        param_layout.addWidget(self.phonetic_cb)   # <-- Add this line
        param_layout.addWidget(query_btn)
        layout.addLayout(param_layout)

        # Spreadsheet/table display.
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["word", "freq", "glen", "splits", "status", "notes"])
        # Allow cells to be editable.
        self.table.setEditTriggers(self.table.DoubleClicked | self.table.SelectedClicked | self.table.EditKeyPressed)
        layout.addWidget(self.table)

        # Connect the Query button action.
        query_btn.clicked.connect(self.query_server)

    def query_server(self):
        # Get the current text; note that our PhoneticLineEdit already displays transliterated text.
        # So, if phonetic mode is enabled, we use the text as shown, otherwise, we may transliterate.
        raw_prefix = self.prefix_edit.text()
        raw_suffix = self.suffix_edit.text()
        raw_regex = self.regex_edit.text()

        if self.phonetic_cb.isChecked():
            # Phonetic mode enabled: the fields already show Tamil.
            prefix_text = raw_prefix
            suffix_text = raw_suffix
            regex_text = raw_regex
        else:
            # Otherwise, assume user entered roman text and perform transliteration.
            prefix_text = transliterate(raw_prefix)
            suffix_text = transliterate(raw_suffix)
            regex_text = transliterate(raw_regex) if raw_regex else ""

        # Percent-encode the (possibly) transliterated text.
        prefix = quote(prefix_text)
        suffix = quote(suffix_text)
        regex = quote(regex_text) if regex_text else ""
        min_len = self.min_len_spin.value()
        limit = self.limit_spin.value()
        exclude = "1" if self.exclude_cb.isChecked() else "0"

        # Assemble the query command.
        cmd_parts = [
            f"QUERY prefix={prefix}",
            f"suffix={suffix}",
            f"min_len={min_len}",
            f"limit={limit}",
            f"offset=0",
            f"exclude_accepted={exclude}"
        ]
        if regex:
            cmd_parts.append(f"regex={regex}")
        cmd = " ".join(cmd_parts)
        try:
            response = self.send_command(cmd)
        except Exception as e:
            QMessageBox.critical(self, "Socket Error", str(e))
            return

        # Parse the result.
        # The protocol returns a header line first (OK ...), then TSV header row and results.
        lines = response.splitlines()
        if not lines:
            QMessageBox.critical(self, "Server Error", "No response from server.")
            return
        if not lines[0].startswith("OK"):
            QMessageBox.critical(self, "Server Error", lines[0])
            return

        # Remove TSV header row from results.
        if len(lines) < 2:
            QMessageBox.information(self, "No Results", "Query returned 0 rows.")
            return

        # The first line is status, second is TSV header.
        data_lines = lines[2:]
        self.populate_table(data_lines)



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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow("run/tamil-words.sock")
    window.resize(1024, 600)
    window.show()
    sys.exit(app.exec_())
