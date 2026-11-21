"""The original ScanGraphic analysis window with the shared Matches tab."""
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTabWidget, QToolBar, QDockWidget, QPushButton
from tools.testbench.gui.matches_panel import MatchesPanel
from tools.testbench.matches import Entrant
from tools.testbench.session import EngineProfile
from tools.testbench.referee import Referee
from .main_window import MainWindow


class IntegratedWindow(MainWindow):
    def __init__(self, scan, work_dir, rust):
        super().__init__(str(scan), str(work_dir))
        self.setWindowTitle('ScanGraphic — Frisian Draughts 0.1.0')
        self._close_pending = False
        self._analysis_visibility = {}
        analysis = self.takeCentralWidget()
        self.tabs = QTabWidget(); self.tabs.addTab(analysis, 'Analysis')
        self.matches = MatchesPanel([
            Entrant('Frisian_Draughts', EngineProfile(str(rust)), {}),
            Entrant('Scan Graphic', EngineProfile(str(scan), cwd=str(work_dir)), {}, capabilities=('scan-diagnostics-v1',)),
        ], rust, self)
        self.tabs.addTab(self.matches, 'Matches'); self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.matches.open_game.connect(self.open_match)
        self.matches.idle.connect(self.matches_idle)

    def tab_changed(self, index):
        widgets = self.findChildren(QDockWidget) + self.findChildren(QToolBar)
        if index:
            if self._analyzing: self._engine.stop_analysis(); self._analyzing = False
            self._analysis_visibility = {w: not w.isHidden() for w in widgets}
            for widget in widgets: widget.hide()
        else:
            for widget, visible in self._analysis_visibility.items(): widget.setVisible(visible)

    def open_match(self, record):
        try:
            if record.get('restrictions'): raise ValueError('Scan analysis cannot load nonzero initial restriction counters')
            root = Referee(self.matches.referee.text()).inspect(record['fen'])
            self._game_fen = root['hub']; self._game_moves = list(record['moves'])
            self.tabs.setCurrentIndex(0)
            self._engine.request_game_analysis(' '.join(self._game_moves), fen=self._game_fen)
            self._status.showMessage(f"Opening {record.get('position_name', 'match')} in Analysis")
        except Exception as exc: self.matches.error(str(exc))

    def _goto_ply(self, ply):
        super()._goto_ply(ply)
        if self._game_data:
            # Replaying from the root preserves repetitions and Frisian king history.
            self._engine.send_command('new-game')
            self._engine.set_position(fen=getattr(self, '_game_fen', None), moves=' '.join(self._game_moves[:self._current_ply]))

    def matches_idle(self):
        if self._close_pending: QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if self.matches.worker is not None:
            self._close_pending = True; self.matches.cancel(); event.ignore(); return
        super().closeEvent(event)
