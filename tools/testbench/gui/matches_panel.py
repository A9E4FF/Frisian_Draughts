"""Embeddable match controls over the shared Hub runner and Rust referee."""
from datetime import datetime
from pathlib import Path
import threading

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QLabel,
    QListWidget, QPlainTextEdit, QFileDialog, QMessageBox)

from tools.testbench.matches import MatchLimits, run_tournament, load_config
from tools.testbench.profiles import preflight, save_profiles
from tools.testbench.referee import Referee
from tools.testbench import pdn
from .task import Task
from .board import BoardWidget
from .profile_dialog import ProfileDialog


class MatchesPanel(QWidget):
    open_game = Signal(object)
    idle = Signal()

    def __init__(self, engines, referee, parent=None):
        super().__init__(parent)
        self.engines = list(engines)
        self.worker = None
        self.games = []
        self.cancel_event = threading.Event()
        self.last_error = None
        root = QHBoxLayout(self)
        self.settings = QWidget(); form = QFormLayout(self.settings); root.addWidget(self.settings, 1)
        self.a = QComboBox(); self.b = QComboBox()
        self.profile_row = QHBoxLayout(); form.addRow(self.profile_row)
        for text, callback in [('Add engine', self.add_engine), ('Edit engine', self.edit_engine),
                               ('Load profiles', self.load_profiles), ('Save profiles', self.save_profiles)]:
            self.button(self.profile_row, text, callback)
        self.referee = QLineEdit(str(referee))
        self.control = QComboBox(); self.control.addItems(['Depth', 'Move time', 'Fischer clock'])
        self.depth = QSpinBox(); self.depth.setRange(1, 64); self.depth.setValue(12)
        self.budget = QDoubleSpinBox(); self.budget.setRange(.01, 86400); self.budget.setValue(1)
        self.increment = QDoubleSpinBox(); self.increment.setRange(0, 3600)
        self.rounds = QSpinBox(); self.rounds.setRange(1, 10000)
        self.parallel = QSpinBox(); self.parallel.setRange(1, 32)
        self.ply_cap = QSpinBox(); self.ply_cap.setRange(1, 10000); self.ply_cap.setValue(200)
        self.watchdog = QDoubleSpinBox(); self.watchdog.setRange(1, 86400); self.watchdog.setValue(300)
        self.output = QLineEdit(str(Path.home()/'FrisianDraughtsResults'/datetime.now().strftime('%Y%m%d-%H%M%S')))
        for name, field in [('Opponent A', self.a), ('Opponent B (colors swapped)', self.b),
            ('Rules executable', self.referee), ('Control', self.control), ('Depth', self.depth),
            ('Seconds / initial clock', self.budget), ('Increment', self.increment), ('Paired rounds', self.rounds),
            ('Simultaneous games', self.parallel), ('Maximum plies', self.ply_cap),
            ('Response watchdog (seconds)', self.watchdog), ('New report directory', self.output)]: form.addRow(name, field)
        self.extra_settings = QVBoxLayout(); form.addRow(self.extra_settings)
        from .start_positions import StartPositions
        self.starts = StartPositions(); self.extra_settings.addWidget(self.starts)
        self.starts.error.connect(self.error); self.starts.preview.connect(self.preview_start)
        self.run_button = QPushButton('Run paired matches'); self.run_button.clicked.connect(self.run_matches); form.addRow(self.run_button)
        view = QVBoxLayout(); root.addLayout(view, 2)
        self.board = BoardWidget(); self.board.setEnabled(False); view.addWidget(self.board, 2)
        self.status = QLabel('Ready'); self.status.setWordWrap(True); view.addWidget(self.status)
        self.results = QListWidget(); view.addWidget(self.results)
        row = QHBoxLayout(); view.addLayout(row)
        self.cancel_button = self.button(row, 'Stop matches', self.cancel); self.cancel_button.setEnabled(False)
        self.button(row, 'Open game in Analysis', self.analyze_selected)
        self.button(row, 'Export PDN', self.export_pdn)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(110); view.addWidget(self.log)
        self.refresh_profiles()

    @staticmethod
    def button(layout, text, callback):
        button = QPushButton(text); layout.addWidget(button); button.clicked.connect(callback); return button

    def refresh_profiles(self):
        for combo in (self.a, self.b):
            index = combo.currentIndex(); combo.clear(); combo.addItems([e.name for e in self.engines]); combo.setCurrentIndex(max(0, index))
        if len(self.engines) > 1 and self.a.currentIndex() == self.b.currentIndex(): self.b.setCurrentIndex(1)

    def add_engine(self):
        dialog = ProfileDialog(parent=self)
        if dialog.exec():
            if any(e.name == dialog.value.name for e in self.engines): return self.error('Engine names must be unique')
            self.engines.append(dialog.value); self.refresh_profiles()

    def edit_engine(self):
        if self.a.currentIndex() < 0: return
        index = self.a.currentIndex(); dialog = ProfileDialog(self.engines[index], self)
        if dialog.exec():
            if any(e.name == dialog.value.name for i, e in enumerate(self.engines) if i != index): return self.error('Engine names must be unique')
            self.engines[index] = dialog.value; self.refresh_profiles()

    def load_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Engine profiles', '', 'JSON (*.json)')
        if path:
            try: self.engines = load_config(path, min_engines=1); self.refresh_profiles()
            except Exception as exc: self.error(str(exc))

    def save_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save profiles', '', 'JSON (*.json)')
        if path:
            try: save_profiles(path, self.engines)
            except Exception as exc: self.error(str(exc))

    def preview_start(self, item):
        try:
            from tools.testbench.start_positions import validate
            state = validate(item, Referee(self.referee.text()))
            self.board.set_position({int(k): v for k, v in state['pieces'].items()}, 'W' if state['turn'] == 'white' else 'B')
            self.status.setText(f"{item['name']}: {state['outcome']}, {len(state['legal_moves'])} legal moves")
        except Exception as exc: self.error(str(exc))

    def tournament_options(self):
        return {}

    def run_matches(self):
        if self.worker is not None: return
        try:
            a, b = self.a.currentIndex(), self.b.currentIndex()
            if a < 0 or b < 0 or a == b: raise ValueError('Select two different engine profiles')
            engines = [self.engines[a], self.engines[b]]
            for engine in engines: preflight(engine)
            referee = Referee(self.referee.text())
            limits = MatchLimits(depth=self.depth.value() if self.control.currentIndex() == 0 else None,
                move_time=self.budget.value() if self.control.currentIndex() == 1 else None,
                clock=self.budget.value() if self.control.currentIndex() == 2 else None,
                increment=self.increment.value(), max_plies=self.ply_cap.value(), response_timeout=self.watchdog.value())
            options = self.tournament_options()
            destination = Path(self.output.text()); rounds = self.rounds.value(); parallel = self.parallel.value()
            if destination.exists(): raise ValueError('Choose a new report directory')
            self.cancel_event = threading.Event(); self.games = []; self.results.clear(); self.last_error = None
            self.worker = Task(lambda emit: run_tournament(engines, referee, limits, rounds=rounds,
                parallel=parallel, cancel=self.cancel_event, on_event=emit, output=destination, **options), self)
            self.worker.event.connect(self.on_event); self.worker.failed.connect(self.error)
            self.worker.result.connect(self.completed); self.worker.finished.connect(self.finished)
            self.settings.setEnabled(False); self.cancel_button.setEnabled(True); self.status.setText('Starting matches…')
            self.worker.start()
        except Exception as exc: self.error(str(exc))

    @Slot(object)
    def on_event(self, event):
        kind = event['type']; prefix = f"Game {event.get('game', '?')}/{event.get('total', '?')}"
        if kind == 'position':
            state = event['state']; pieces = {int(k): v for k, v in state['pieces'].items()}
            self.board.set_position(pieces, 'W' if state['turn'] == 'white' else 'B')
        elif kind == 'game-started': self.status.setText(f"{prefix}: {event['white']} – {event['black']}")
        elif kind == 'thinking': self.status.setText(f"{prefix}: {event['engine']}, ply {event['ply'] + 1}")
        elif kind == 'game-finished':
            game = event['record']; self.log.appendPlainText(f"{prefix}: {game['result']} ({game['termination']})")

    @Slot(object)
    def completed(self, games):
        self.games = games; self.results.clear()
        for game in games: self.results.addItem(f"{game['white']} – {game['black']}: {game['result']} ({game['termination']})")
        if games: self.results.setCurrentRow(0)
        self.status.setText(f'{len(games)} games saved to {self.output.text()}')

    @Slot()
    def finished(self):
        task = self.worker; self.worker = None
        if task: task.deleteLater()
        self.settings.setEnabled(True); self.cancel_button.setEnabled(False); self.idle.emit()

    def cancel(self):
        self.cancel_event.set(); self.status.setText('Stopping matches…')

    @Slot(str)
    def error(self, message):
        self.last_error = message; self.status.setText(message); self.log.appendPlainText(message)

    def analyze_selected(self):
        index = self.results.currentRow()
        if 0 <= index < len(self.games): self.open_game.emit(self.games[index])

    def export_pdn(self):
        if not self.games: return
        path, _ = QFileDialog.getSaveFileName(self, 'Export match games', '', 'PDN (*.pdn)')
        if path:
            try: Path(path).write_text(pdn.dumps([pdn.from_record(g, dialect='scan') for g in self.games]), encoding='utf-8')
            except Exception as exc: self.error(str(exc))
