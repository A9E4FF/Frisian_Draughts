"""Editable, ordered collection of match start positions."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QDialog, QFormLayout, QLineEdit, QPlainTextEdit,
    QDialogButtonBox, QFileDialog, QPushButton, QLabel)
from tools.testbench import start_positions as model


class StartPositions(QWidget):
    changed = Signal()
    preview = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.positions = [model.position()]
        layout = QVBoxLayout(self); layout.addWidget(QLabel('Start positions — checked entries run in list order'))
        self.list = QListWidget(); self.list.setMaximumHeight(130); layout.addWidget(self.list)
        self.list.itemChanged.connect(self.checked)
        row = QHBoxLayout(); layout.addLayout(row)
        for text, callback in [('Add', self.add), ('Edit', self.edit), ('Delete', self.delete),
            ('↑', lambda: self.move(-1)), ('↓', lambda: self.move(1)), ('Preview', self.show_preview)]: self.button(row, text, callback)
        row = QHBoxLayout(); layout.addLayout(row)
        for text, callback in [('Import TXT / FEN', self.import_file), ('Paste list', self.paste),
            ('Load collection', self.load), ('Save collection', self.save)]: self.button(row, text, callback)
        self.refresh()

    @staticmethod
    def button(layout, text, callback):
        button = QPushButton(text); layout.addWidget(button); button.clicked.connect(callback)

    def refresh(self, selected=0):
        self.list.blockSignals(True); self.list.clear()
        for p in self.positions:
            item = QListWidgetItem(f"{p['name']}   {p['fen']}"); item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p['enabled'] else Qt.Unchecked); self.list.addItem(item)
        self.list.setCurrentRow(min(selected, len(self.positions)-1)); self.list.blockSignals(False); self.changed.emit()

    def checked(self, item):
        self.positions[self.list.row(item)]['enabled'] = item.checkState() == Qt.Checked; self.changed.emit()

    def editor(self, current=None):
        value = dict(current or model.position('New position')); dialog = QDialog(self); form = QFormLayout(dialog)
        dialog.setWindowTitle('Match start — setup or replay from a root')
        fields = {}
        for key, label in [('name', 'Name'), ('fen', 'Root FEN'), ('moves', 'Replay moves (Hub)'), ('restrictions', 'Initial restrictions (JSON)')]:
            raw = ' '.join(value[key]) if key == 'moves' else json.dumps(value[key]) if key == 'restrictions' else value[key]
            fields[key] = QLineEdit(raw); form.addRow(label, fields[key])
        form.addRow(QLabel('FEN alone starts with cleared history. Replay moves preserve history.'))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); form.addRow(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if not dialog.exec(): return None
        try:
            value.update(name=fields['name'].text(), fen=fields['fen'].text(), moves=fields['moves'].text().split(), restrictions=json.loads(fields['restrictions'].text()))
            return model.check(value)
        except Exception as exc: self.error.emit(str(exc))

    def add(self):
        value = self.editor()
        if value: self.positions.append(value); self.refresh(len(self.positions)-1)

    def edit(self):
        index = self.list.currentRow()
        if index < 0: return
        value = self.editor(self.positions[index])
        if value: self.positions[index] = value; self.refresh(index)

    def delete(self):
        index = self.list.currentRow()
        if index >= 0: self.positions.pop(index); self.refresh(index)

    def move(self, delta):
        index = self.list.currentRow(); other = index + delta
        if 0 <= index < len(self.positions) and 0 <= other < len(self.positions):
            self.positions[index], self.positions[other] = self.positions[other], self.positions[index]; self.refresh(other)

    def show_preview(self):
        index = self.list.currentRow()
        if index >= 0: self.preview.emit(self.positions[index])

    def import_text(self, text):
        items = model.parse_text(text)  # Parse atomically: a bad line retains the current list.
        self.positions.extend(items); self.refresh(len(self.positions)-len(items))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Old match tool positions', '', 'Position lists (*.txt *.fen);;All files (*)')
        if path:
            try: self.import_text(Path(path).read_text(encoding='utf-8-sig'))
            except Exception as exc: self.error.emit(str(exc))

    def paste(self):
        dialog = QDialog(self); layout = QVBoxLayout(dialog); edit = QPlainTextEdit(); edit.setPlaceholderText('One FEN per line'); layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec():
            try: self.import_text(edit.toPlainText())
            except Exception as exc: self.error.emit(str(exc))

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load start collection', '', 'JSON (*.json)')
        if path:
            try: self.positions = model.load(path); self.refresh()
            except Exception as exc: self.error.emit(str(exc))

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save start collection', '', 'JSON (*.json)')
        if path:
            try: model.save(path, self.positions)
            except Exception as exc: self.error.emit(str(exc))
