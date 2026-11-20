"""Unified desktop over the shared headless analysis/match/rules backends."""
import json
from pathlib import Path
import re
import sys
import threading

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSlider,
    QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from tools.position_suite.client import format_event
from tools.position_suite.model import DEFAULT_ENGINE, load_suite, save_suite, validate_case
from tools.testbench.matches import (Entrant, MatchLimits, load_config, play_game,
                                    save_reports, schedule, run_tournament)
from tools.testbench.positions import HubAnalysisSession
from tools.testbench.protocol import parse
from tools.testbench.referee import Referee
from tools.testbench.session import EngineProfile, HubSession
from .board import BoardWidget
from .models import board_fen, load_replay, move_tuple
from tools.testbench import pdn


class Task(QThread):
    event = Signal(object)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function(self.event.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Frisian Draughts Testbench')
        self.resize(1280, 850)
        self.engines = [Entrant('Rust', EngineProfile(str(DEFAULT_ENGINE)), {})]
        self.cases = []
        self.games = []
        self.worker = None
        self.job_state = 'idle'
        self.last_error = None
        self._busy_widgets = []
        self._pending_replay = False
        self.cancel_active = lambda: None
        self._close_pending = False
        self._move_signal = False
        self._legal = []
        self._case_base = {}
        self.pdn_document = None
        self.analysis_notes = []
        root = QWidget(); outer = QVBoxLayout(root); self.setCentralWidget(root)
        row = QHBoxLayout(); outer.addLayout(row)
        self.engine = QComboBox(); self.engine.addItem('Rust'); row.addWidget(QLabel('Analyze with')); row.addWidget(self.engine)
        self.button(row, 'Load profiles', self.load_profiles)
        self.button(row, 'Add engine', self.add_engine)
        self.button(row, 'Edit engine', self.edit_engine)
        self.button(row, 'Test Hub', self.test_engine)
        self.button(row, 'Save profiles', self.save_profiles)
        self.referee = QLineEdit(str(DEFAULT_ENGINE)); row.addWidget(QLabel('Rules engine')); row.addWidget(self.referee)
        self.button(row, 'Browse', self.browse_referee)
        self.tabs = QTabWidget(); outer.addWidget(self.tabs)
        self.make_analysis(); self.make_cases(); self.make_matches(); self.make_replay()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(180); outer.addWidget(self.log)
        row = QHBoxLayout(); outer.addLayout(row)
        self.cancel_button = self.button(row, 'Cancel work', self.cancel)
        self.cancel_button.setEnabled(False)
        self.button(row, 'Export log', self.export_log)
        self.status = QLabel('Ready — FEN setups start with cleared history unless supplemented.'); row.addWidget(self.status)
        self.engine.currentIndexChanged.connect(self.update_capabilities)
        self.update_capabilities()

    def button(self, layout, text, callback):
        button = QPushButton(text); layout.addWidget(button); button.clicked.connect(callback); return button

    def make_analysis(self):
        tab = QWidget(); layout = QHBoxLayout(tab); self.tabs.addTab(tab, 'Analysis')
        self.board = BoardWidget(); self.board.set_legality_check(True); layout.addWidget(self.board, 2)
        panel = QWidget(); form = QFormLayout(panel); layout.addWidget(panel, 2)
        self.name = QLineEdit('New position'); self.fen = QLineEdit('W:W31-50:B1-20')
        self.replay_moves = QPlainTextEdit(); self.replay_moves.setMaximumHeight(90)
        self.restrictions = QLineEdit('{}'); self.expected = QLineEdit(); self.notes = QLineEdit()
        self.depth = QSpinBox(); self.depth.setRange(1, 64); self.depth.setValue(12)
        for label, field in [('Name', self.name), ('Starting FEN', self.fen), ('Replay moves', self.replay_moves),
                             ('Initial restrictions (JSON)', self.restrictions), ('Depth', self.depth),
                             ('Accepted alternatives', self.expected), ('Notes', self.notes)]:
            form.addRow(label, field)
        self.setup = QCheckBox('Edit a new setup (clears history)'); form.addRow(self.setup)
        self.setup.toggled.connect(self.setup_changed)
        row = QHBoxLayout(); form.addRow(row)
        self.button(row, 'Preview', self.preview)
        self.button(row, 'Analyze', self.analyze)
        self.button(row, 'Flip', lambda: self.board.set_flipped(not self.board._flipped))
        self.moves = QComboBox(); form.addRow('Legal move', self.moves)
        row = QHBoxLayout(); form.addRow(row)
        self.button(row, 'Play selected', self.play_selected)
        self.diagnostics = self.button(row, 'Scan diagnostics', self.scan_diagnostics)
        self.capability_label = QLabel(); self.capability_label.setWordWrap(True); form.addRow(self.capability_label)
        self.board.move_played.connect(self.board_move)
        self.board.position_changed.connect(self.board_changed)

    def make_cases(self):
        tab = QWidget(); layout = QVBoxLayout(tab); self.tabs.addTab(tab, 'Position suite')
        self.case_list = QListWidget(); layout.addWidget(self.case_list)
        self.case_list.currentRowChanged.connect(self.select_case)
        row = QHBoxLayout(); layout.addLayout(row)
        self.button(row, 'Load suite', self.load_cases); self.button(row, 'Save suite', self.save_cases)
        self.button(row, 'Add / update analysis case', self.add_case)
        self.button(row, 'Run all cases', self.run_cases)
        self.button(row, 'Run selected case', self.run_selected_case)

    def make_matches(self):
        tab = QWidget(); layout = QHBoxLayout(tab); settings = QWidget(); form = QFormLayout(settings)
        layout.addWidget(settings, 1); view = QWidget(); live_layout = QVBoxLayout(view); layout.addWidget(view, 2)
        self.tabs.addTab(tab, 'Matches')
        self.opponent_a = QComboBox(); self.opponent_b = QComboBox()
        self.opponent_a.addItems([e.name for e in self.engines]); self.opponent_b.addItems([e.name for e in self.engines])
        form.addRow('Opponent A (colors swapped)', self.opponent_a); form.addRow('Opponent B', self.opponent_b)
        self.watchdog = QDoubleSpinBox(); self.watchdog.setRange(1, 86400); self.watchdog.setValue(300)
        self.parallel = QSpinBox(); self.parallel.setRange(1, 32)
        form.addRow('Response watchdog (seconds, not a clock)', self.watchdog); form.addRow('Simultaneous games', self.parallel)
        self.control = QComboBox(); self.control.addItems(['Depth', 'Move time', 'Fischer clock'])
        self.budget = QDoubleSpinBox(); self.budget.setRange(0.01, 86400); self.budget.setValue(1)
        self.increment = QDoubleSpinBox(); self.increment.setRange(0, 3600)
        self.rounds = QSpinBox(); self.rounds.setRange(1, 10000)
        self.ply_cap = QSpinBox(); self.ply_cap.setRange(1, 10000); self.ply_cap.setValue(200)
        self.output = QLineEdit('match-results')
        for label, field in [('Control (depth uses analysis depth)', self.control), ('Time / initial clock (seconds)', self.budget),
                             ('Increment (seconds)', self.increment), ('Paired rounds', self.rounds),
                             ('Adjudication ply cap', self.ply_cap), ('New report directory', self.output)]:
            form.addRow(label, field)
        row = QHBoxLayout(); form.addRow(row); self.button(row, 'Run all paired matches', self.run_matches)
        self.match_log = QPlainTextEdit(); self.match_log.setReadOnly(True); form.addRow(self.match_log)
        self.match_board = BoardWidget(); self.match_board.setMinimumSize(300, 300); self.match_board.setEnabled(False); live_layout.addWidget(self.match_board)
        self.live = QLabel('Waiting for a match'); self.live.setWordWrap(True); live_layout.addWidget(self.live)

    def make_replay(self):
        tab = QWidget(); layout = QVBoxLayout(tab); self.tabs.addTab(tab, 'Replay')
        row = QHBoxLayout(); layout.addLayout(row)
        self.button(row, 'Load games.json', self.open_replay)
        self.button(row, 'Import PDN', self.open_pdn)
        self.button(row, 'Export game PDN', lambda: self.choose_pdn_export(False))
        self.button(row, 'Export all PDN', lambda: self.choose_pdn_export(True))
        self.game_selector = QComboBox(); row.addWidget(self.game_selector)
        self.game_selector.currentIndexChanged.connect(self.select_game)
        self.replay_board = BoardWidget(); self.replay_board.setEnabled(False); layout.addWidget(self.replay_board)
        self.slider = QSlider(Qt.Horizontal); self.slider.valueChanged.connect(self.replay_position); layout.addWidget(self.slider)
        self.replay_label = QLabel('Load a canonical JSON match report.'); layout.addWidget(self.replay_label)
        self.annotation_view = QPlainTextEdit(); self.annotation_view.setReadOnly(True); self.annotation_view.setMaximumHeight(110); layout.addWidget(self.annotation_view)
        row = QHBoxLayout(); layout.addLayout(row)
        self.button(row, 'Analyze this position', self.analyze_replay)
        self.button(row, 'Export analysis PDN', self.choose_analysis_export)
        self.dialect = QComboBox(); self.dialect.addItems(['Standard landing paths', 'Scan captured squares']); row.addWidget(self.dialect)

    def selected_engine(self):
        return self.engines[self.engine.currentIndex()]

    def current_case(self):
        return validate_case({**self._case_base, 'name': self.name.text(), 'fen': self.fen.text(), 'depth': self.depth.value(),
            'moves': self.replay_moves.toPlainText().split(), 'restrictions': json.loads(self.restrictions.text()),
            'accepted_moves': [m for m in re.split(r'[\s,]+', self.expected.text()) if m], 'notes': self.notes.text()})

    def start(self, function, completed=None, cancel=None):
        if self.worker is not None:
            return False
        self._completed = completed
        self.job_state = 'running'; self.last_error = None
        self.cancel_active = cancel or (lambda: None)
        self._busy_widgets = [(w, w.isEnabled()) for w in self.findChildren(QWidget)
            if isinstance(w, (QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QSlider, BoardWidget)) and w is not self.cancel_button]
        for widget, _ in self._busy_widgets: widget.setEnabled(False)
        self.replay_moves.setReadOnly(True)
        self.cancel_button.setEnabled(True); self.status.setText('Working…')
        self.worker = Task(function, self)
        self.worker.event.connect(self.on_event); self.worker.result.connect(self.on_result)
        self.worker.failed.connect(self.error); self.worker.finished.connect(self.idle)
        self.worker.start(); return True

    @Slot(object)
    def on_result(self, result):
        if self._completed:
            try: self._completed(result)
            except Exception as exc: self.error(str(exc))

    @Slot()
    def idle(self):
        self.worker.deleteLater(); self.worker = None
        self.job_state = 'idle'
        for widget, enabled in self._busy_widgets: widget.setEnabled(enabled)
        self._busy_widgets = []
        self.replay_moves.setReadOnly(False)
        self.cancel_button.setEnabled(False); self.status.setText(self.last_error or 'Ready'); self.cancel_active = lambda: None
        if self._close_pending: self.close()
        elif self._pending_replay:
            self._pending_replay = False
            self.replay_position(self.slider.value())

    @Slot(str)
    def error(self, message):
        self.last_error = message
        self.log.appendPlainText('ERROR: ' + message)
        self.status.setText(message)

    @Slot(object)
    def on_event(self, event):
        kind = event.get('type')
        if kind == 'position':
            self.show_board(self.match_board, event['state'])
            self.match_log.appendPlainText(f"Game {event['game']}: {' '.join(event['moves'])}")
        elif kind == 'thinking':
            self.live.setText(f"Game {event['game']}/{event['total']}: {event['engine']} thinking, ply {event['ply']+1}")
        elif kind == 'search-info':
            fields = event['fields']
            self.live.setText(f"{event['engine']} | depth {fields.get('depth', '?')} | score {fields.get('score', '?')} men | PV {fields.get('pv', '')}")
        elif kind == 'game-finished':
            record = event['record']
            self.match_log.appendPlainText(f"Game {event['game']}: {record['result']} ({record['termination']})")
        elif kind == 'game-started':
            self.match_log.appendPlainText(f"Game {event['game']}: {event['white']} vs {event['black']}")
        elif kind == 'loaded':
            self.show_board(self.board, event)
            self._legal = event['legal_moves']; self.moves.clear(); self.moves.addItems(self._legal)
        elif event.get('type') == 'case-finished':
            self.log.appendPlainText(f"{event['name']}: {event['status']} {event.get('message', '')}")
        else:
            self.log.appendPlainText(format_event(event))

    def show_board(self, board, loaded):
        pieces = {p['square']: ('W' if p['side'] == 'white' else 'B') if p['piece'] == 'king'
                  else ('w' if p['side'] == 'white' else 'b') for p in loaded['pieces']}
        board.set_position(pieces, 'W' if loaded['turn'] == 'white' else 'B')
        board.set_legal_moves([move_tuple(m) for m in loaded['legal_moves']])
        restrictions = loaded.get('restrictions', {})
        w = restrictions.get('white') or {}; b = restrictions.get('black') or {}
        board.set_wolf_info(str(w.get('square', 'none')), w.get('count', 0), str(b.get('square', 'none')), b.get('count', 0))

    def preview(self):
        try:
            case = self.current_case(); referee = Referee(self.referee.text())
            def work(emit):
                loaded = referee.inspect(case['fen'], case['moves'], case['restrictions'], case['accepted_moves'])
                emit(loaded); return loaded
            self.start(work)
        except Exception as exc: self.error(str(exc))

    def analyze(self):
        try:
            case = self.current_case(); entrant = self.selected_engine()
            session = HubAnalysisSession(entrant.profile, self.referee.text(), parameters=entrant.parameters)
            def finished(outcome):
                self.log.appendPlainText(f'{outcome.status.upper()} {outcome.message}')
                if outcome.result and outcome.status in ('passed', 'failed', 'analysis'):
                    self.analysis_notes.append({'case': case, 'engine': entrant.name, 'result': outcome.result})
            self.start(lambda emit: session.run(case, emit), finished, session.cancel)
        except Exception as exc: self.error(str(exc))

    def setup_changed(self, enabled):
        self.board.set_legality_check(not enabled)
        if enabled:
            self._case_base = {}
            self.replay_moves.clear(); self.restrictions.setText('{}'); self.expected.clear()
            self.log.appendPlainText('New setup: history and restriction counters cleared.')

    def board_changed(self):
        if self._move_signal:
            self._move_signal = False; return
        if self.setup.isChecked():
            self.fen.setText(board_fen(self.board.get_pieces(), self.board.get_turn()))

    def board_move(self, source, destination, captures):
        matches = [m for m in self._legal if move_tuple(m)[:3] == (source, destination, tuple(captures))]
        self._move_signal = True
        if len(matches) == 1: self.append_move(matches[0])

    def append_move(self, move):
        self.replay_moves.setPlainText(' '.join([*self.replay_moves.toPlainText().split(), move]))
        self.expected.clear(); self.preview()

    def play_selected(self):
        if self.moves.currentText(): self.append_move(self.moves.currentText())

    def cancel(self):
        if self.worker is not None:
            self.job_state = 'cancelling'; self.cancel_active(); self.status.setText('Cancelling…')

    def load_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Engine profiles', '', 'JSON (*.json)')
        if path:
            try:
                self.engines = load_config(path, min_engines=1); self.refresh_profiles()
            except Exception as exc: self.error(str(exc))

    def refresh_profiles(self):
        for combo in [self.engine, self.opponent_a, self.opponent_b]:
            index = combo.currentIndex(); combo.clear(); combo.addItems([e.name for e in self.engines]); combo.setCurrentIndex(max(0, min(index, len(self.engines)-1)))
        if len(self.engines) > 1: self.opponent_b.setCurrentIndex(1)

    def add_engine(self):
        from .profile_dialog import ProfileDialog
        dialog = ProfileDialog(parent=self)
        if dialog.exec():
            if dialog.value.name in [e.name for e in self.engines]: return self.error('Engine names must be unique')
            self.engines.append(dialog.value); self.refresh_profiles()

    def edit_engine(self):
        from .profile_dialog import ProfileDialog
        index = self.engine.currentIndex(); dialog = ProfileDialog(self.selected_engine(), self)
        if dialog.exec():
            if any(e.name == dialog.value.name for i,e in enumerate(self.engines) if i != index): return self.error('Engine names must be unique')
            self.engines[index] = dialog.value; self.refresh_profiles()

    def test_engine(self):
        from tools.testbench.profiles import preflight
        engine = self.selected_engine()
        def work(emit):
            preflight(engine)
            with HubSession(engine.profile) as session:
                session.start({'variant': 'frisian', **engine.parameters})
                return session.identity.get('name', engine.name)
        self.start(work, lambda name: self.log.appendPlainText('Hub initialization passed: ' + name))

    def save_profiles(self):
        from tools.testbench.profiles import save_profiles
        path, _ = QFileDialog.getSaveFileName(self, 'Save engine profiles', 'engines.json', 'JSON (*.json)')
        if path:
            try: save_profiles(path, self.engines)
            except Exception as exc: self.error(str(exc))

    def browse_referee(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Rust rules engine')
        if path: self.referee.setText(path)

    def load_cases(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load suite', '', 'JSON (*.json)')
        if path:
            try:
                self.cases = load_suite(path); self.case_list.clear(); self.case_list.addItems([c['name'] for c in self.cases])
            except Exception as exc: self.error(str(exc))

    def save_cases(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save suite', 'positions.json', 'JSON (*.json)')
        if path:
            try: save_suite(path, self.cases)
            except Exception as exc: self.error(str(exc))

    def add_case(self):
        try:
            case = self.current_case()
            index = next((i for i, c in enumerate(self.cases) if c['name'] == case['name']), len(self.cases))
            if index == len(self.cases): self.cases.append(case); self.case_list.addItem(case['name'])
            else: self.cases[index] = case
        except Exception as exc: self.error(str(exc))

    def select_case(self, index):
        if not 0 <= index < len(self.cases): return
        case = self.cases[index]; self.name.setText(case['name']); self.fen.setText(case['fen'])
        self._case_base = dict(case)
        self.replay_moves.setPlainText(' '.join(case.get('moves', []))); self.depth.setValue(case.get('depth', 10))
        self.restrictions.setText(json.dumps(case.get('restrictions', {}))); self.expected.setText(', '.join(case.get('accepted_moves', [])))
        self.notes.setText(case.get('notes', ''))

    def run_selected_case(self):
        index = self.case_list.currentRow()
        if 0 <= index < len(self.cases): self.run_cases([self.cases[index]])

    def run_cases(self, cases=None):
        cases = list(self.cases) if not isinstance(cases, list) else list(cases)
        entrant = self.selected_engine(); referee = self.referee.text(); cancel = threading.Event()
        current = [None]
        def work(emit):
            outcomes = []
            for case in cases:
                if cancel.is_set(): break
                session = HubAnalysisSession(entrant.profile, referee, parameters=entrant.parameters); current[0] = session
                if cancel.is_set(): session.cancel()
                outcome = session.run(case, emit); outcomes.append(outcome)
                emit({'type': 'case-finished', 'name': case['name'], 'status': outcome.status, 'message': outcome.message})
            return outcomes
        def stop():
            cancel.set()
            if current[0]: current[0].cancel()
        self.start(work, cancel=stop)

    def run_matches(self):
        try:
            if len(self.engines) < 2: raise ValueError('Add at least two engines')
            destination = Path(self.output.text())
            if destination.exists(): raise ValueError('Choose a new report directory')
            limits = MatchLimits(depth=self.depth.value() if self.control.currentIndex() == 0 else None,
                move_time=self.budget.value() if self.control.currentIndex() == 1 else None,
                clock=self.budget.value() if self.control.currentIndex() == 2 else None,
                increment=self.increment.value(), max_plies=self.ply_cap.value(), response_timeout=self.watchdog.value())
            from tools.testbench.profiles import preflight
            a, b = self.opponent_a.currentIndex(), self.opponent_b.currentIndex()
            if a == b: raise ValueError('Select two different engine profiles')
            engines = [self.engines[a], self.engines[b]]
            for engine in engines: preflight(engine)
            referee = Referee(self.referee.text()); cancel = threading.Event(); rounds = self.rounds.value(); parallel = self.parallel.value()
            self.start(lambda emit: run_tournament(engines, referee, limits, rounds=rounds, parallel=parallel, cancel=cancel, on_event=emit, output=destination), self.matches_finished, cancel.set)
        except Exception as exc: self.error(str(exc))

    def matches_finished(self, games):
        self.match_log.setPlainText('\n'.join(f'{g["white"]} – {g["black"]}: {g["result"]} ({g["termination"]})' for g in games))
        self.set_games(games)

    def open_replay(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Canonical match report', '', 'JSON (*.json)')
        if path:
            try: self.set_games(load_replay(path))
            except Exception as exc: self.error(str(exc))

    def open_pdn(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import games', '', 'PDN (*.pdn *.PDN)')
        if path: self.import_pdn(path)

    def import_pdn(self, path):
        referee = Referee(self.referee.text()); cancel = threading.Event()
        def work(emit):
            documents = pdn.loads(Path(path).read_text(encoding='utf-8-sig'))
            for index, document in enumerate(documents, 1):
                if cancel.is_set():
                    document.errors.append('Import cancelled'); continue
                pdn.validate(document, referee)
                emit({'type': 'case-finished', 'name': f'PDN game {index}',
                      'status': 'error' if document.errors else 'loaded', 'message': '; '.join(document.errors)})
            return documents
        def completed(documents):
            games = [{'fen': g.fen, 'moves': list(g.moves), 'white': g.tag('White', '?'),
                'black': g.tag('Black', '?'), 'event': g.tag('Event', '?'), 'result': g.tag('Result', '*'),
                'errors': list(g.errors), 'termination': 'PDN import'} for g in documents]
            self.set_games(games); self.pdn_document = documents
            index = self.game_selector.currentIndex()
            if index >= 0: self.annotation_view.setPlainText(' '.join(documents[index].tokens) + '\n' + '; '.join(documents[index].errors))
        self.start(work, completed, cancel.set)

    def choose_pdn_export(self, all_games):
        path, _ = QFileDialog.getSaveFileName(self, 'Export PDN games', 'games.pdn', 'PDN (*.pdn)')
        if path: self.export_pdn(path, all_games=all_games)

    def export_pdn(self, path, *, all_games=False):
        import copy
        index = self.game_selector.currentIndex()
        if not 0 <= index < len(self.games): return self.error('Select a game first')
        indices = list(range(len(self.games))) if all_games else [index]
        records = [copy.deepcopy(self.games[i]) for i in indices]
        originals = [copy.deepcopy(self.pdn_document[i]) for i in indices] if self.pdn_document else None
        referee = Referee(self.referee.text()); dialect = 'scan' if self.dialect.currentIndex() else 'standard'
        def work(emit):
            if any(any(g.get('restrictions', {}).values()) for g in records):
                raise ValueError('PDN cannot store initial king counters; retain canonical JSON instead')
            documents = originals or [pdn.from_record(g, referee, dialect) for g in records]
            for number, (document, record) in enumerate(zip(documents, records), 1):
                if document.errors or record.get('errors'):
                    raise ValueError(f'Game {number}: fix import errors before export')
            Path(path).write_text(pdn.dumps(documents), encoding='utf-8')
            return len(documents)
        self.start(work, lambda n: self.log.appendPlainText(f'Exported {n} PDN game(s)'))

    def analyze_replay(self):
        index = self.game_selector.currentIndex()
        if not 0 <= index < len(self.games): return
        game = self.games[index]
        if game.get('errors'): return self.error('; '.join(game['errors']))
        self._case_base = {}; self.name.setText('Replay analysis'); self.fen.setText(game['fen'])
        self.replay_moves.setPlainText(' '.join(game['moves'][:self.slider.value()]))
        self.restrictions.setText(json.dumps(game.get('restrictions', {}))); self.expected.clear()
        self.tabs.setCurrentIndex(0); self.analyze()

    def choose_analysis_export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export latest analysis', 'analysis.pdn', 'PDN (*.pdn)')
        if path: self.export_analysis_pdn(path)

    def export_analysis_pdn(self, path):
        import copy
        if not self.analysis_notes: return self.error('Run an analysis first')
        note = copy.deepcopy(self.analysis_notes[-1]); case = note['case']; referee = Referee(self.referee.text())
        originals = copy.deepcopy(self.pdn_document)
        def work(emit):
            if any(case.get('restrictions', {}).values()):
                raise ValueError('PDN cannot represent imported restriction counters; keep the JSON position case')
            document = next((d for d in originals or [] if d.fen == case['fen'] and d.moves[:len(case['moves'])] == case['moves']), None)
            if document is None:
                document = pdn.from_record({'fen': case['fen'], 'moves': case['moves'], 'result': '*', 'event': 'Analysis'}, referee)
            result = note['result']; score = result.get('score')
            text = f"Engine analysis ({note['engine']}): depth {result.get('depth', 0)}; score {score/100 if score is not None else 'unsearched'} men, side to move; PV {' '.join(result.get('pv', []))}"
            annotation = '{' + text.replace('{', '(').replace('}', ')') + '}'
            wanted = len(case['moves']); count = 0; nesting = 0; insertion = 0
            for i, token in enumerate(document.tokens):
                if token == '(': nesting += 1
                elif token == ')': nesting -= 1
                elif nesting == 0 and pdn.MOVE.fullmatch(token) and token not in pdn.RESULTS:
                    count += 1
                    if count == wanted: insertion = i+1; break
            document.tokens.insert(insertion, annotation)
            Path(path).write_text(pdn.dumps([document]), encoding='utf-8')
        self.start(work, lambda _: self.log.appendPlainText('Exported PDN with clearly labeled engine analysis'))

    def set_games(self, games):
        self.pdn_document = None
        self._pending_replay = self.worker is not None
        self.games = games; self.game_selector.clear()
        self.game_selector.addItems([f'{g.get("event", "Game")} | {g.get("white", "White")} – {g.get("black", "Black")} {g.get("result", "*")}' + (' [ERROR]' if g.get('errors') else '') for g in games])

    def select_game(self, index):
        if 0 <= index < len(self.games):
            game = self.games[index]
            self.annotation_view.setPlainText('\n'.join(game.get('errors', [])) or (' '.join(self.pdn_document[index].tokens) if self.pdn_document else 'Canonical match replay'))
            self.slider.setRange(0, len(self.games[index]['moves'])); self.slider.setValue(0)
            if self.worker is None: self.replay_position(0)

    def replay_position(self, ply):
        index = self.game_selector.currentIndex()
        if not 0 <= index < len(self.games) or self.worker is not None: return
        game = self.games[index]; referee = Referee(self.referee.text())
        if game.get('errors'):
            self.replay_label.setText('Cannot replay: ' + '; '.join(game['errors'])); return
        self.replay_label.setText(f'Ply {ply}/{len(game["moves"])} — {game.get("termination", "")}')
        self.start(lambda emit: referee.inspect(game['fen'], game['moves'][:ply], game.get('restrictions')),
                   lambda loaded: self.show_board(self.replay_board, loaded))

    def update_capabilities(self):
        supported = bool(self.engines and self.engine.currentIndex() >= 0 and 'scan-diagnostics-v1' in self.selected_engine().capabilities)
        self.diagnostics.setEnabled(supported)
        self.capability_label.setText('Scan diagnostics enabled by profile.' if supported else 'Standard Hub analysis. Scan-specific diagnostics are disabled for this profile.')

    def scan_diagnostics(self):
        try:
            entrant = self.selected_engine()
            if 'scan-diagnostics-v1' not in entrant.capabilities: return
            case = self.current_case(); referee = Referee(self.referee.text())
            if any(case['restrictions'].values()): raise ValueError('Scan diagnostics need replay from a cleared initial state')
            def work(emit):
                loaded = referee.inspect(case['fen'])
                with HubSession(entrant.profile) as peer:
                    peer.start({'variant': 'frisian', 'book': 'false', **entrant.parameters})
                    peer.send('pos', [('pos', loaded['hub']), ('moves', ' '.join(case['moves']))])
                    for command in ['analysis', 'eval-decompose', 'pattern-scores', 'move-list', 'wing-control']:
                        peer.send(command)
                    peer.ping(timeout=30)
                    return [e['line'] for e in peer.transcript if e['direction'] == 'stdout']
            def completed(lines):
                self.log.appendPlainText('\n'.join(lines))
                patterns = []
                for raw in lines:
                    m = parse(raw)
                    if m.command == 'pattern-info': patterns.append({'col': int(m.get('col')), 'score': float(m.get('score'))})
                if patterns: self.board.set_heatmap(patterns)
            self.start(work, completed)
        except Exception as exc: self.error(str(exc))

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export log', 'analysis.txt', 'Text (*.txt)')
        if path:
            try: Path(path).write_text(self.log.toPlainText() + '\n', encoding='utf-8')
            except Exception as exc: self.error(str(exc))

    def closeEvent(self, event):
        if self.worker is not None:
            self._close_pending = True; self.cancel(); event.ignore()
        else: event.accept()


def launch():
    app = QApplication.instance() or QApplication(sys.argv)
    window = Window(); window.show(); return app.exec()
