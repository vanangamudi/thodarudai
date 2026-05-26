#!/usr/bin/env python3
# tamil_editor_demo.py
import sys
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit, QShortcut
from PyQt5.QtGui import QKeySequence

# Import our transliteration function from the separate library.
from tamilphonetic import transliterate

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

class PhoneticTextEdit(QTextEdit):
    """
    A simple QTextEdit that transliterates text as you type using our transliterate function.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Remove the auto-translation on textChanged.
        # self.textChanged.connect(self.on_text_changed)
        self.setPlaceholderText("Type in romanized text and see Tamil transliteration...")
        # Buffers to track state:
        self.committed = ""
        self.composition = ""
        self.trailing = ""

    def _normalize_state_for_editing(self, current_text, cp):
        # If there is a selection, use that to split the text.
        if self.textCursor().hasSelection():
            sel_start = self.textCursor().selectionStart()
            sel_end = self.textCursor().selectionEnd()
            self.committed = current_text[:sel_start]
            self.trailing = current_text[sel_end:]
            self.composition = ""
            return
        # Otherwise, check if the caret is at the expected position.
        expected_cp = len(self.committed + self.composition)
        if cp == expected_cp and current_text.startswith(self.committed + self.composition):
            return
        # If caret is not at the end, split the text at the caret.
        if cp < len(current_text):
            self.committed = current_text[:cp]
            self.trailing = current_text[cp:]
            self.composition = ""
        else:
            self.committed = current_text
            self.trailing = ""
            
    def _handle_backspace(self):
        if self.composition:
            self.composition = self.composition[:-1]
        else:
            # Remove one character from the committed text.
            self.committed = self.committed[:-1]
        self.update_display()
        
    def _handle_delete(self):
        if self.composition:
            self.composition = ""
        elif self.trailing:
            # Remove the first character from trailing.
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

    def commit_composition(self):
        """
        Commit the current composition by converting it to Tamil
        using transliterate(), forcing a pulli if needed.
        """
        if self.composition:
            result = transliterate(self.composition)
            from backend.core.tamil_phonetic import PHONETIC_VOWELS, PULLI
            if not any(self.composition.lower().endswith(vt) for vt in PHONETIC_VOWELS.keys()):
                if not result.endswith(PULLI):
                    result += PULLI
            self.committed += result
            self.composition = ""

    def update_display(self):
        # Compute transliteration for current pending composition.
        current_disp = transliterate(self.composition)
        from backend.core.tamil_phonetic import PHONETIC_VOWELS, PULLI
        if self.composition and not any(self.composition.lower().endswith(vt) for vt in PHONETIC_VOWELS.keys()):
            if not current_disp.endswith(PULLI):
                current_disp += PULLI
        final = self.committed + current_disp + self.trailing
        self.blockSignals(True)
        self.setPlainText(final)
        # Set the cursor at the end of the committed+composition part.
        cursor = self.textCursor()
        cursor.setPosition(len(self.committed + current_disp))
        self.setTextCursor(cursor)
        self.blockSignals(False)

    def is_possible_prefix(self, candidate):
        """
        Return True if candidate (a roman string) is either:
          - exactly a token in PHONETIC_VOWELS or CONSONANTS,
          - a prefix of any token,
        OR, if candidate can be split as (consonant + vowel_prefix) where:
          - the consonant part is a valid consonant token, and
          - the vowel_prefix part is a prefix of some vowel token.
        """
        candidate = candidate.lower()
        from backend.core.tamil_phonetic import PHONETIC_VOWELS, CONSONANTS
        tokens = list(PHONETIC_VOWELS.keys()) + list(CONSONANTS.keys())
        if any(token == candidate or token.startswith(candidate) for token in tokens):
            return True
        if len(candidate) >= 2:
            for i in range(1, len(candidate)):
                cons_part = candidate[:i]
                vowel_part = candidate[i:]
                if cons_part in CONSONANTS and any(vowel.startswith(vowel_part) for vowel in PHONETIC_VOWELS.keys()):
                    return True
        return False

    def keyPressEvent(self, event):
        """
        Override keyPressEvent so that keys are processed for transliteration,
        appending to the pending composition and updating the display.
        """
        import string
        from PyQt5.QtCore import Qt
        key = event.key()
        ch = event.text()
        current_text = self.toPlainText()
        cp = self.textCursor().position()
        # Normalize buffers for caret/selection position
        self._normalize_state_for_editing(current_text, cp)

        if key == Qt.Key_Backspace:
            self._handle_backspace()
            event.accept(); return
        elif key == Qt.Key_Delete:
            self._handle_delete()
            event.accept(); return
        elif ch and (ch in string.whitespace or ch in string.punctuation):
            self._handle_boundary_char(ch)
            event.accept(); return
        elif ch and ch.isalnum():
            self._handle_alnum_char(ch)
            event.accept(); return
        else:
            super().keyPressEvent(event)


class MainEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tamil Phonetic Text Editor Demo")
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Type your text (romanized):"))
        self.editor = PhoneticTextEdit(self)
        layout.addWidget(self.editor)
        self.tamil_display = QLabel("")
        self.tamil_display.setWordWrap(True)
        self.tamil_display.setStyleSheet("font-size: 16px;")
        layout.addWidget(QLabel("Tamil Transliteration Preview:"))
        layout.addWidget(self.tamil_display)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.clear_text)

    def update_tamil_display(self, text):
        print("DEBUG: Updating Tamil display with:", text)
        self.tamil_display.setText(text)

    def clear_text(self):
        self.editor.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainEditorWindow()
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec_())
