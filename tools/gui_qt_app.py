#!/usr/bin/env python3
import sys, socket
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt
from tools.tamil_phonetic import transliterate
from urllib.parse import quote  # for percent encoding parameters

class PhoneticLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.raw_text = ""  # store the raw input
        self.textChanged.connect(self.on_text_changed)

    def keyPressEvent(self, event):
        pos = self.cursorPosition()
        key = event.key()
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            if key == Qt.Key_Backspace and pos > 0:
                self.raw_text = self.raw_text[:pos-1] + self.raw_text[pos:]
                pos -= 1
            elif key == Qt.Key_Delete and pos < len(self.raw_text):
                self.raw_text = self.raw_text[:pos] + self.raw_text[pos+1:]
            self._updateDisplay(pos)
            event.accept()
            return
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                     Qt.Key_Home, Qt.Key_End, Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
            super().keyPressEvent(event)
            return
        ch = event.text()
        if ch:
            self.raw_text = self.raw_text[:pos] + ch + self.raw_text[pos:]
            pos += len(ch)
            self._updateDisplay(pos)
            event.accept()
            return
        else:
            super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        committed = event.commitString()
        if committed:
            # Append the committed string at current cursor position.
            pos = self.cursorPosition()
            self.raw_text = self.raw_text[:pos] + committed + self.raw_text[pos:]
            pos += len(committed)
            self._updateDisplay(pos)
            event.accept()
        else:
            super().inputMethodEvent(event)

    def _updateDisplay(self, new_cursor_pos):
        window = self.window()
        use_phonetic = hasattr(window, 'phonetic_cb') and window.phonetic_cb.isChecked()
        new_text = transliterate(self.raw_text) if use_phonetic else self.raw_text
        self.setText(new_text)
        self.setCursorPosition(len(new_text))

    def on_text_changed(self, new_text):
        # Fallback: if the visible text doesn't match transliteration of our stored raw_text, update raw_text.
        if new_text != transliterate(self.raw_text):
            self.raw_text = new_text

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
        # Get the raw input from the fields.
        raw_prefix = self.prefix_edit.text()
        raw_suffix = self.suffix_edit.text()
        raw_regex = self.regex_edit.text()

        # If the Phonetic Input checkbox is enabled, transliterate the input.
        if self.phonetic_cb.isChecked():
            prefix_text = transliterate(raw_prefix)
            suffix_text = transliterate(raw_suffix)
            regex_text = transliterate(raw_regex) if raw_regex else ""
        else:
            prefix_text = raw_prefix
            suffix_text = raw_suffix
            regex_text = raw_regex

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
            field._updateDisplay(len(field.raw_text))

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
