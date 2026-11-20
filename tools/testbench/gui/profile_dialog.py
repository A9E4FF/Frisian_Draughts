import json
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                              QFileDialog, QPushButton, QCheckBox, QMessageBox)
from tools.testbench.profiles import entrant


class ProfileDialog(QDialog):
    def __init__(self, existing=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Hub engine profile'); form = QFormLayout(self)
        self.fields = {}
        values = {'Name': existing.name if existing else '',
            'Executable': existing.profile.executable if existing else '',
            'Arguments (JSON list)': json.dumps(existing.profile.arguments) if existing else '["hub"]',
            'Working directory': existing.profile.cwd or '' if existing else '',
            'Parameters (JSON object)': json.dumps(existing.parameters) if existing else '{}',
            'Source revision (optional)': existing.revision or '' if existing else ''}
        for label, value in values.items():
            edit = QLineEdit(value); self.fields[label] = edit; form.addRow(label, edit)
        browse = QPushButton('Browse executable'); browse.clicked.connect(self.browse); form.addRow(browse)
        self.scan = QCheckBox('This build supports ScanGraphic diagnostics')
        self.scan.setChecked(bool(existing and 'scan-diagnostics-v1' in existing.capabilities)); form.addRow(self.scan)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Hub executable')
        if path: self.fields['Executable'].setText(path)

    def accept(self):
        try:
            self.value = entrant(*(edit.text() for edit in self.fields.values()),
                capabilities=['scan-diagnostics-v1'] if self.scan.isChecked() else [])
            super().accept()
        except ValueError as exc: QMessageBox.warning(self, 'Invalid profile', str(exc))
