"""MainWindow - Frisian Draughts Analysis GUI."""

import sys
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDockWidget,
    QToolBar, QPushButton, QLabel, QTextEdit, QGroupBox, QGridLayout,
    QProgressBar, QCheckBox, QSplitter, QApplication, QStatusBar,
    QMessageBox, QComboBox, QFileDialog, QSlider, QInputDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPalette

from tools.scan_graphic.board_widget import BoardWidget
from tools.scan_graphic.engine import EngineProcess
from tools.scan_graphic.eval_graph import EvalGraph


class MainWindow(QMainWindow):
    """Main window for the Frisian Draughts Analysis GUI."""

    def __init__(self, engine_path: str, work_dir: str = None):
        super().__init__()

        self.setWindowTitle("Scan 3.1 — Frisian Draughts Analysis")
        self.setMinimumSize(1100, 700)

        # Engine
        self._engine = EngineProcess(engine_path, work_dir)
        self._connect_engine()

        # State
        self._current_pos = {}   # pieces dict
        self._current_turn = 'W'
        self._analyzing = False
        self._pos_fen = None     # current Hub FEN string

        # Game analysis state
        self._game_data = []     # per-ply eval + pos data from engine
        self._game_moves = []    # list of move strings
        self._current_ply = 0

        # Tactical arrow display (mode -> board arrows)
        self._arrow_sets = {}    # 'unified' -> list of arrows
        self._quality_arrows = {"best": [], "good": [], "inaccuracy": []}
        self._arrow_mode = 'quality'

        # Build UI
        self._create_widgets()
        self._create_toolbar()
        self._create_statusbar()
        self._create_game_panel()

        # Start engine
        self._engine.start()

    def _connect_engine(self):
        """Connect engine signals to handlers."""
        eng = self._engine

        eng.ready.connect(self._on_engine_ready)
        eng.error_occurred.connect(self._on_engine_error)
        eng.info_received.connect(self._on_search_info)
        eng.done_received.connect(self._on_search_done)
        eng.analysis_received.connect(self._on_analysis)
        eng.eval_decompose_received.connect(self._on_eval_decompose)
        eng.game_analysis_received.connect(self._on_game_analysis)
        eng.pattern_scores_received.connect(self._on_pattern_scores)
        eng.move_list_received.connect(self._on_move_list)
        eng.legal_moves_received.connect(self._on_legal_moves)
        eng.wing_control_received.connect(self._on_wing_control)
        eng.tactics_received.connect(self._on_tactics_received)
        eng.raw_line.connect(self._on_raw_line)

    # ---- UI Creation ----

    def _create_widgets(self):
        """Create the main UI layout."""
        # Central: board
        self._board = BoardWidget()
        self._board.setMinimumSize(550, 550)
        self._board.position_changed.connect(self._on_position_changed)
        self._board.move_played.connect(self._on_move_played)

        central = QWidget()
        layout = QHBoxLayout(central)

        # --- Left panel: Tactical Analysis ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(350)

        tact_header = QHBoxLayout()
        btn_analyze = QPushButton("🔍 Analyze Tactics")
        btn_analyze.clicked.connect(self._request_tactical)
        tact_header.addWidget(btn_analyze)
        left_layout.addLayout(tact_header)

        # Panel 1: Move Quality
        qual_group = QGroupBox("Move Quality")
        qual_layout = QVBoxLayout(qual_group)
        self._qual_text = QTextEdit()
        self._qual_text.setReadOnly(True)
        self._qual_text.setMaximumHeight(220)
        self._qual_text.setPlaceholderText("Blunders · Bad · Good · Best")
        qual_layout.addWidget(self._qual_text)
        left_layout.addWidget(qual_group)

        # Panel 2: Tactical Sequences
        unified_group = QGroupBox("Tactical Sequences")
        unified_layout = QVBoxLayout(unified_group)
        self._tactics_text = QTextEdit()
        self._tactics_text.setReadOnly(True)
        self._tactics_text.setMaximumHeight(320)
        self._tactics_text.setPlaceholderText("Shots · Exchanges · Losses (sorted by eval)")
        unified_layout.addWidget(self._tactics_text)
        left_layout.addWidget(unified_group)

        left_layout.addStretch()
        layout.addWidget(left_panel)

        layout.addWidget(self._board, 1)

        # Right panel: analysis info
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_panel.setMaximumWidth(400)

        # Search info group
        search_group = QGroupBox("Search Info (White's perspective)")
        search_layout = QGridLayout(search_group)
        self._lbl_depth = QLabel("--")
        self._lbl_score = QLabel("0.00")
        self._lbl_nodes = QLabel("0")
        self._lbl_time = QLabel("0.00s")
        self._lbl_nps = QLabel("0 MN/s")
        search_layout.addWidget(QLabel("Depth:"), 0, 0)
        search_layout.addWidget(self._lbl_depth, 0, 1)
        search_layout.addWidget(QLabel("Score:"), 1, 0)
        search_layout.addWidget(self._lbl_score, 1, 1)
        search_layout.addWidget(QLabel("Nodes:"), 2, 0)
        search_layout.addWidget(self._lbl_nodes, 2, 1)
        search_layout.addWidget(QLabel("Time:"), 3, 0)
        search_layout.addWidget(self._lbl_time, 3, 1)
        search_layout.addWidget(QLabel("Speed:"), 4, 0)
        search_layout.addWidget(self._lbl_nps, 4, 1)
        right_layout.addWidget(search_group)

        # PV display
        pv_group = QGroupBox("Principal Variation")
        pv_layout = QVBoxLayout(pv_group)
        self._pv_text = QTextEdit()
        self._pv_text.setReadOnly(True)
        self._pv_text.setMaximumHeight(80)
        pv_layout.addWidget(self._pv_text)
        right_layout.addWidget(pv_group)

        # Eval decomposition
        eval_group = QGroupBox("Evaluation (White's perspective)")
        eval_layout = QGridLayout(eval_group)
        self._eval_labels = {}
        for i, (key, label) in enumerate([
            ("material", "Material"), ("king_pst", "King PST"),
            ("king_mob", "King Mobility"), ("balance", "Balance"),
            ("pattern", "Patterns"), ("wolf", "Wolf"),
            ("total", "Total")
        ]):
            lbl = QLabel("0.00")
            eval_layout.addWidget(QLabel(label + ":"), i, 0)
            eval_layout.addWidget(lbl, i, 1)
            self._eval_labels[key] = lbl
        right_layout.addWidget(eval_group)

        # Phase progress
        phase_group = QGroupBox("Game Phase")
        phase_layout = QVBoxLayout(phase_group)
        self._phase_bar = QProgressBar()
        self._phase_bar.setRange(0, 300)
        self._phase_bar.setFormat("Stage: %v / 300")
        phase_layout.addWidget(self._phase_bar)
        self._lbl_tempo = QLabel("Tempo: --")
        phase_layout.addWidget(self._lbl_tempo)
        right_layout.addWidget(phase_group)

        # Piece counts
        piece_group = QGroupBox("Material")
        piece_layout = QGridLayout(piece_group)
        self._lbl_pieces = QLabel("White: 20 men, 0 kings\nBlack: 20 men, 0 kings")
        piece_layout.addWidget(self._lbl_pieces, 0, 0)
        self._lbl_wolf = QLabel("Wolf: none / none")
        piece_layout.addWidget(self._lbl_wolf, 1, 0)
        right_layout.addWidget(piece_group)

        # Wing control
        wing_group = QGroupBox("Wing Control")
        wing_layout = QGridLayout(wing_group)
        self._lbl_wing = QLabel("Left:  W:--  B:--  (C:--)\nRight: W:--  B:--  (C:--)")
        wing_layout.addWidget(self._lbl_wing, 0, 0)
        right_layout.addWidget(wing_group)

        # Move list
        move_group = QGroupBox("Legal Moves")
        move_layout = QVBoxLayout(move_group)
        self._move_text = QTextEdit()
        self._move_text.setReadOnly(True)
        self._move_text.setMaximumHeight(100)
        move_layout.addWidget(self._move_text)
        right_layout.addWidget(move_group)

        right_layout.addStretch()
        layout.addWidget(right_panel)

        self.setCentralWidget(central)

        # Log dock
        self._log_dock = QDockWidget("Engine Log", self)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_dock.setWidget(self._log_text)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._log_dock)

    def _create_game_panel(self):
        """Create the game-import dock with eval graph and navigation."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # Graph
        self._eval_graph = EvalGraph()
        self._eval_graph.setMinimumHeight(180)
        layout.addWidget(self._eval_graph, 1)

        # Navigation row
        nav = QHBoxLayout()

        btn_prev = QPushButton("◀")
        btn_prev.setFixedWidth(36)
        btn_prev.clicked.connect(lambda: self._goto_ply(self._current_ply - 1))
        nav.addWidget(btn_prev)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.valueChanged.connect(self._on_slider)
        nav.addWidget(self._slider, 1)

        btn_next = QPushButton("▶")
        btn_next.setFixedWidth(36)
        btn_next.clicked.connect(lambda: self._goto_ply(self._current_ply + 1))
        nav.addWidget(btn_next)

        self._lbl_move = QLabel("Ply 0 / 0")
        self._lbl_move.setMinimumWidth(70)
        self._lbl_move.setAlignment(Qt.AlignCenter)
        nav.addWidget(self._lbl_move)

        self._chk_quiet = QCheckBox("Quiet only")
        self._chk_quiet.setChecked(True)
        self._chk_quiet.setToolTip("Only evaluate at quiet positions "
                                    "(no capture available)")
        self._chk_quiet.toggled.connect(self._eval_graph.set_quiet_only)
        nav.addWidget(self._chk_quiet)

        layout.addLayout(nav)

        self._game_dock = QDockWidget("Game Analysis", self)
        self._game_dock.setWidget(panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._game_dock)
        self._game_dock.hide()  # hidden until a game is imported

    def _create_toolbar(self):
        """Create the main toolbar."""
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        # Analyze button
        self._btn_analyze = QPushButton("▶ Analyze")
        self._btn_analyze.clicked.connect(self._toggle_analysis)
        tb.addWidget(self._btn_analyze)

        tb.addSeparator()

        # Position controls
        btn_start = QPushButton("Start Pos")
        btn_start.clicked.connect(self._set_start_position)
        tb.addWidget(btn_start)

        btn_import = QPushButton("Import PDN...")
        btn_import.clicked.connect(self._import_pdn)
        tb.addWidget(btn_import)

        self._chk_heatmap = QCheckBox("Heatmap")
        self._chk_heatmap.setChecked(True)
        self._chk_heatmap.toggled.connect(self._board.set_show_heatmap)
        tb.addWidget(self._chk_heatmap)

        # Heatmap perspective mode: show pattern strength for White or Black
        self._combo_heatmap_view = QComboBox()
        self._combo_heatmap_view.addItem("White view", "W")
        self._combo_heatmap_view.addItem("Black view", "B")
        self._combo_heatmap_view.currentIndexChanged.connect(
            self._on_heatmap_view_changed)
        tb.addWidget(self._combo_heatmap_view)

        self._chk_flip = QCheckBox("Flip")
        self._chk_flip.toggled.connect(self._board.set_flipped)
        tb.addWidget(self._chk_flip)

        self._chk_legal = QCheckBox("Legal moves only")
        self._chk_legal.toggled.connect(self._board.set_legality_check)
        self._chk_legal.setChecked(True)  # emits toggled -> enables legality
        tb.addWidget(self._chk_legal)

        # Tactical arrow mode
        self._combo_arrows = QComboBox()
        self._combo_arrows.addItem("Arrows: Move Quality", "quality")
        self._combo_arrows.addItem("Arrows: Unified Tactics", "unified")
        self._combo_arrows.currentIndexChanged.connect(self._on_arrow_mode_changed)
        tb.addWidget(self._combo_arrows)

        self._chk_show_inaccuracies = QCheckBox("Inaccuracies")
        self._chk_show_inaccuracies.setToolTip(
            "Also show Inaccuracy moves as arrows in Move Quality mode")
        self._chk_show_inaccuracies.toggled.connect(self._apply_arrows)
        tb.addWidget(self._chk_show_inaccuracies)

        tb.addSeparator()

        # Turn toggle
        self._btn_turn = QPushButton("Turn: W")
        self._btn_turn.setCheckable(True)
        self._btn_turn.setChecked(False)  # False = White to move
        self._btn_turn.toggled.connect(self._toggle_turn)
        self._btn_turn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #000000; font-weight: bold; }"
            "QPushButton:checked { background: #333333; color: #ffffff; }")
        tb.addWidget(self._btn_turn)

        tb.addSeparator()

        btn_refresh = QPushButton("Refresh Analysis")
        btn_refresh.clicked.connect(self._refresh_analysis)
        tb.addWidget(btn_refresh)

        tb.addSeparator()

        # Score format
        tb.addWidget(QLabel("  Score display: "))
        self._lbl_score_main = QLabel("0.00")
        self._lbl_score_main.setStyleSheet("font-weight: bold; font-size: 14px;")
        tb.addWidget(self._lbl_score_main)

    def _create_statusbar(self):
        """Create status bar."""
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Starting engine...")

    # ---- Engine event handlers ----

    def _on_engine_ready(self):
        """Engine initialized."""
        self._status.showMessage("Engine ready (Frisian)")
        self._set_start_position()

    def _on_engine_error(self, msg: str):
        self._status.showMessage(f"Error: {msg}")
        self._log_text.append(f"[ERROR] {msg}")

    def _on_search_info(self, info: dict):
        """Received search info line."""
        self._lbl_depth.setText(str(info["depth"]))
        self._lbl_score.setText(f"{info['score']:.2f}")
        score_display = f"{info['score']:+.2f}"
        self._lbl_score_main.setText(score_display)
        if info["score"] > 0:
            self._lbl_score_main.setStyleSheet(
                "font-weight: bold; font-size: 14px; color: #006600;")
        elif info["score"] < 0:
            self._lbl_score_main.setStyleSheet(
                "font-weight: bold; font-size: 14px; color: #cc0000;")
        else:
            self._lbl_score_main.setStyleSheet(
                "font-weight: bold; font-size: 14px;")

        self._lbl_nodes.setText(f"{info['nodes']:,}")
        self._lbl_time.setText(f"{info['time']:.2f}s")
        self._lbl_nps.setText(f"{info['nps']:.1f} MN/s")
        self._pv_text.setText(info.get("pv", ""))

    def _on_search_done(self, done: dict):
        """Search completed."""
        self._analyzing = False
        self._btn_analyze.setText("▶ Analyze")
        self._status.showMessage("Analysis stopped")

    def _on_analysis(self, data: dict):
        """Received analysis data."""
        self._lbl_tempo.setText(f"Tempo: {data['tempo']}")
        self._phase_bar.setValue(data["stage"])
        self._lbl_pieces.setText(
            f"White: {data['wm']} men, {data['wk']} kings\n"
            f"Black: {data['bm']} men, {data['bk']} kings"
        )
        self._lbl_wolf.setText(
            f"Wolf: W={data['w_wolf']} ({data['w_count']}/3)  "
            f"B={data['b_wolf']} ({data['b_count']}/3)"
        )

        # Update wolf display on board
        self._board.set_wolf_info(
            data["w_wolf"], data["w_count"],
            data["b_wolf"], data["b_count"]
        )

    def _on_eval_decompose(self, data: dict):
        """Received eval decomposition."""
        for key in ["material", "king_pst", "king_mob", "balance", "pattern", "wolf", "total"]:
            if key in self._eval_labels:
                val = data.get(key, 0)
                self._eval_labels[key].setText(f"{val:+.2f}")
                if val > 0:
                    self._eval_labels[key].setStyleSheet("color: #006600;")
                elif val < 0:
                    self._eval_labels[key].setStyleSheet("color: #cc0000;")
                else:
                    self._eval_labels[key].setStyleSheet("")

    def _on_pattern_scores(self, patterns: list):
        """Received pattern scores."""
        self._board.set_heatmap(patterns)

    def _on_heatmap_view_changed(self, index: int):
        """Switch heatmap between White and Black perspective."""
        persp = self._combo_heatmap_view.itemData(index)
        self._board.set_heatmap_perspective(persp)

    def _on_move_list(self, moves: list):
        """Received move list."""
        lines = []
        for m in moves:
            mv = m["move"]
            typ = m["type"]
            prefix = {"capture": "✖", "promo": "★", "quiet": " "}.get(typ, " ")
            lines.append(f"{prefix} {mv}")
        self._move_text.setText("\n".join(lines))

    def _on_legal_moves(self, moves: list):
        """Received structured legal moves — pass to board for validation."""
        self._board.set_legal_moves(moves)

    def _on_move_played(self, from_sq: int, to_sq: int, captured: list):
        """A legal move was played on the board — switch turn (engine sync
        happens via the position_changed signal that follows)."""
        # Switch side to move
        new_turn = 'B' if self._board.get_turn() == 'W' else 'W'
        self._board.set_turn(new_turn)
        self._btn_turn.setChecked(new_turn == 'B')
        self._btn_turn.setText("Turn: B" if new_turn == 'B' else "Turn: W")

        move_str = f"{from_sq}-{to_sq}" if not captured else f"{from_sq}x{to_sq}" + "".join(f"x{c}" for c in captured)
        if captured:
            self._status.showMessage(
                f"Played {move_str} — {new_turn} to move, {len(captured)} captured")
        else:
            self._status.showMessage(f"Played {move_str} — {new_turn} to move")

    def _on_wing_control(self, data: dict):
        """Received wing control data."""
        self._lbl_wing.setText(
            f"Left:  W:{data['left_w']}  B:{data['left_b']}  (C:{data['left_c']})\n"
            f"Right: W:{data['right_w']}  B:{data['right_b']}  (C:{data['right_c']})"
        )

    def _clear_tactical(self):
        """Clear tactical analysis arrows and text."""
        self._arrow_sets = {}
        self._quality_arrows = {"best": [], "good": [], "inaccuracy": []}
        self._board.set_arrows([])
        self._qual_text.setHtml("")
        self._tactics_text.setHtml("")

    def _on_arrow_mode_changed(self, index: int):
        """Switch board arrows between move quality and unified tactics."""
        self._arrow_mode = self._combo_arrows.itemData(index)
        self._apply_arrows()

    def _apply_arrows(self):
        """Apply the currently selected arrow set to the board."""
        mode = getattr(self, "_arrow_mode", "quality")
        if mode == "quality":
            qa = getattr(self, "_quality_arrows", {})
            arrows = list(qa.get("best", [])) + list(qa.get("good", []))
            chk = getattr(self, "_chk_show_inaccuracies", None)
            if chk is not None and chk.isChecked():
                arrows += qa.get("inaccuracy", [])
        else:
            arrows = getattr(self, "_arrow_sets", {}).get(mode, [])
        self._board.set_arrows(arrows)

    def _request_tactical(self):
        """Request tactical analysis for the current position."""
        self._qual_text.setHtml("<i style='color:#888'>Analyzing...</i>")
        self._tactics_text.setHtml("<i style='color:#888'>Analyzing...</i>")
        f = self._board.to_hub_fen()
        self._engine.set_position(fen=f)
        self._engine.request_tactics()

    def _on_tactics_received(self, results: list):
        """Display unified tactical analysis: Move Quality + Tactical Sequences."""
        self._qual_text.setHtml("")
        self._tactics_text.setHtml("")
        if not results:
            self._arrow_sets = {"unified": []}
            self._quality_arrows = {"best": [], "good": [], "inaccuracy": []}
            self._board.set_arrows([])
            return

        best_eval = max(float(r.get("eval", 0)) for r in results)

        TIER_COLORS = {"best": "#2ecc71", "good": "#3498db", "inaccuracy": "#f1c40f",
                       "mistake": "#e67e22", "blunder": "#e74c3c"}
        TIER_LABELS = {"best": "Best", "good": "Good", "inaccuracy": "Inaccuracy",
                       "mistake": "Mistake", "blunder": "Blunder"}

        def tier_of(diff):
            if diff == 0:
                return "best"
            if diff <= 0.30:
                return "good"
            if diff <= 0.55:
                return "inaccuracy"
            if diff <= 1.00:
                return "mistake"
            return "blunder"

        # ---- Panel 1: Move Quality (all moves, tiered by eval) ----
        tiers = {"best": [], "good": [], "inaccuracy": [], "mistake": [], "blunder": []}
        for r in results:
            mv = r.get("move", "")
            ev = float(r.get("eval", 0))
            diff = best_eval - ev
            tiers[tier_of(diff)].append((mv, ev, diff))

        qual_html = ['<div style="font-family:Segoe UI,sans-serif; font-size:12px; line-height:1.4">']
        for tier in ("best", "good", "inaccuracy", "mistake", "blunder"):
            items = tiers[tier]
            if not items:
                continue
            color = TIER_COLORS[tier]
            label = TIER_LABELS[tier]
            qual_html.append(f'<div style="color:{color}; font-weight:bold; margin-top:2px">◆ {label}</div>')
            for mv, ev, diff in items:
                qual_html.append(
                    f'<div style="margin-left:12px">'
                    f'<span style="color:{color}"><b>{mv}</b></span>'
                    f'<span style="color:#888; font-size:10px"> eval: {ev:+.2f} (Δ={diff:+.2f})</span>'
                    f'</div>')

        qual_html.append('<div style="margin-top:4px; padding-top:3px; border-top:1px solid #444; '
                         f'color:#888; font-size:9px">{len(results)} moves, best eval={best_eval:+.2f}'
                         f'</div>')
        qual_html.append('</div>')
        self._qual_text.setHtml("".join(qual_html))

        # ---- Move Quality arrows (Best → green, Good → blue, Inaccuracy → gold) ----
        self._quality_arrows = {"best": [], "good": [], "inaccuracy": []}
        for mv, ev, diff in tiers["best"]:
            p = self._parse_move_for_arrow(mv)
            if p:
                self._quality_arrows["best"].append((p[0], p[1], "green", "Best"))
        for mv, ev, diff in tiers["good"]:
            p = self._parse_move_for_arrow(mv)
            if p:
                self._quality_arrows["good"].append((p[0], p[1], "blue", "Good"))
        for mv, ev, diff in tiers["inaccuracy"]:
            p = self._parse_move_for_arrow(mv)
            if p:
                self._quality_arrows["inaccuracy"].append((p[0], p[1], "gold", "Inacc"))

        # ---- Panel 2: Tactical Sequences (only moves that lead to an exchange) ----
        html = ['<div style="font-family:Segoe UI,sans-serif; font-size:12px; line-height:1.4">']
        arrows = []
        tac_count = 0

        for r in results:
            typ = r.get("type", "quiet")
            if typ == "quiet":
                continue  # skip moves that don't lead to an exchange

            tac_count += 1
            mv = r.get("move", "")
            ev = float(r.get("eval", 0))
            diff = best_eval - ev
            tier = tier_of(diff)

            give = int(r.get("give", 0))
            take = int(r.get("take", 0))
            net = int(r.get("net", 0))
            pv = r.get("pv", "")

            if net > 0:
                desc = f"{give}-for-{take} (+{net})"
            elif net == 0:
                desc = f"{give}-for-{take} (=)"
            else:
                desc = f"{give}-for-{take} ({net})"

            TIER_ARROW = {"best": "green", "good": "blue", "inaccuracy": "gold",
                          "mistake": "orange", "blunder": "red"}
            arrow_color = TIER_ARROW[tier]

            html.append(
                f'<div style="margin-left:6px">'
                f'<span style="color:{TIER_COLORS[tier]}"><b>{mv}</b></span>'
                f'<span style="color:{TIER_COLORS[tier]}"> {desc}</span>'
                f'<span style="color:#888; font-size:10px"> [{TIER_LABELS[tier]}] eval: {ev:+.2f}</span>'
                f'</div>')
            if pv:
                html.append(
                    f'<div style="margin-left:14px; color:#666; font-size:10px">{pv}</div>')
            p = self._parse_move_for_arrow(mv)
            if p:
                arrows.append((p[0], p[1], arrow_color, desc))

        if tac_count == 0:
            html.append('<i style="color:#888">No exchanges or combinations</i>')
        html.append('<div style="margin-top:4px; padding-top:3px; border-top:1px solid #444; '
                    f'color:#888; font-size:9px">{tac_count} exchange sequences</div>')
        html.append('</div>')
        self._tactics_text.setHtml("".join(html))

        self._arrow_sets = {
            "unified": arrows,
        }
        self._apply_arrows()

    @staticmethod
    def _parse_move_for_arrow(move_str: str):
        """Parse a move string into (from, to) for arrow drawing."""
        try:
            if '-' in move_str:
                a, b = move_str.split('-')
                return (int(a), int(b))
            elif 'x' in move_str:
                parts = move_str.split('x')
                return (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
        return None

    def _on_raw_line(self, line: str):
        """Unrecognized engine output — log it."""
        self._log_text.append(line)

    # ---- Actions ----

    def _toggle_analysis(self):
        """Start or stop analysis."""
        if self._analyzing:
            self._engine.stop_analysis()
        else:
            self._analyzing = True
            self._btn_analyze.setText("⏹ Stop")
            self._status.showMessage("Analyzing...")
            self._engine.start_analysis()

    def _set_start_position(self):
        """Set the starting position."""
        if self._analyzing:
            self._engine.stop_analysis()
            self._analyzing = False
            self._btn_analyze.setText("▶ Analyze")

        self._engine.send_command("new-game")
        self._engine.set_position()
        self._engine.request_analysis_data()

        # Parse starting position pieces for the board
        # Standard Frisian starting position
        self._current_pos = {}
        for sq in range(1, 21):
            self._current_pos[sq] = 'b'  # Black men
        for sq in range(31, 51):
            self._current_pos[sq] = 'w'  # White men
        self._current_turn = 'W'
        self._board.set_position(self._current_pos, self._current_turn)
        self._status.showMessage("Starting position")

    def _refresh_analysis(self):
        """Request updated analysis data for current position."""
        self._engine.request_analysis_data()

    def _on_position_changed(self):
        """User modified pieces on the board — send new position to engine."""
        # Stop any running analysis
        if self._analyzing:
            self._engine.stop_analysis()
            self._analyzing = False
            self._btn_analyze.setText("▶ Analyze")

        # Update local state from board
        self._current_pos = self._board.get_pieces()
        self._current_turn = self._board.get_turn()

        # Send new position to engine
        fen = self._board.to_hub_fen()
        self._engine.send_command("new-game")
        self._engine.set_position(fen=fen)
        self._engine.request_analysis_data()

        # Clear stale tactical analysis
        self._clear_tactical()

        self._status.showMessage(
            f"Position updated — {self._current_turn} to move, "
            f"{len(self._current_pos)} pieces")

    def _toggle_turn(self, checked: bool):
        """Toggle side to move."""
        self._board.set_turn('B' if checked else 'W')
        self._btn_turn.setText("Turn: B" if checked else "Turn: W")
        if checked:
            self._btn_turn.setStyleSheet(
                "QPushButton { background: #333333; color: #ffffff; font-weight: bold; }")
        else:
            self._btn_turn.setStyleSheet(
                "QPushButton { background: #ffffff; color: #000000; font-weight: bold; }")
        self._on_position_changed()

    # ---- Game analysis (PDN import + navigation) ----

    def _import_pdn(self):
        """Open a PDN file and request per-ply eval analysis."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import PDN Game", "", "PDN files (*.pdn *.PDN);;All files (*)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self, "Import Failed", f"Cannot read file:\n{e}")
            return

        games = parse_pdn_games(text)
        if not games:
            QMessageBox.warning(self, "Import Failed",
                                "No games/moves found in the PDN file.")
            return

        # Pick a game if the file contains several
        if len(games) > 1:
            labels = []
            for i, g in enumerate(games):
                who = f"{g.get('white', '?')} vs {g.get('black', '?')}"
                res = g.get('result', '')
                labels.append(f"{i + 1}. {who}  {res}  ({len(g['moves'])} plies)")
            choice, ok = QInputDialog.getItem(
                self, "Select Game", "Which game to analyze?", labels, 0, False)
            if not ok:
                return
            game = games[labels.index(choice)]
        else:
            game = games[0]

        moves = game["moves"]
        if not moves:
            QMessageBox.warning(self, "Import Failed",
                                "No moves found in the selected game.")
            return

        self._game_moves = moves
        self._game_fen = game.get("fen")  # hub FEN or None
        self._status.showMessage(f"Analyzing {len(moves)} plies...")
        self._engine.request_game_analysis(" ".join(moves), fen=self._game_fen)

    def _on_game_analysis(self, data: list):
        """Received per-ply eval data for the imported game."""
        self._game_data = data
        if not data:
            self._status.showMessage("Game analysis returned no data.")
            return

        self._eval_graph.set_data(data)
        max_ply = len(data) - 1
        self._slider.blockSignals(True)
        self._slider.setRange(0, max_ply)
        self._slider.blockSignals(False)
        self._game_dock.show()
        self._goto_ply(0)

        self._status.showMessage(
            f"Game imported: {len(self._game_moves)} plies, "
            f"{max_ply} positions analyzed")

    def _on_slider(self, value: int):
        self._goto_ply(value)

    def _goto_ply(self, ply: int):
        """Navigate to a specific ply: update board, graph cursor, engine."""
        if not self._game_data:
            return
        ply = max(0, min(ply, len(self._game_data) - 1))
        self._current_ply = ply

        # Update slider without re-triggering
        self._slider.blockSignals(True)
        self._slider.setValue(ply)
        self._slider.blockSignals(False)

        # Update graph cursor
        self._eval_graph.set_current_ply(ply)

        # Update board from stored position
        entry = self._game_data[ply]
        fen = entry.get("pos", "")
        pieces, turn = parse_hub_position(fen)
        self._board.set_position(pieces, turn)
        self._btn_turn.setChecked(turn == 'B')
        self._btn_turn.setText("Turn: B" if turn == 'B' else "Turn: W")
        self._current_pos = pieces
        self._current_turn = turn

        # Sync engine and refresh analysis panels
        if fen:
            self._engine.send_command("new-game")
            self._engine.set_position(fen=fen)
            self._engine.request_analysis_data()

        # Clear stale tactical analysis
        self._clear_tactical()

        # Move label
        if ply == 0:
            label = "Start"
        else:
            label = self._game_moves[ply - 1] if ply - 1 < len(self._game_moves) else ""
        self._lbl_move.setText(f"Ply {ply} ({label})")
        self._status.showMessage(f"Position: ply {ply} of {len(self._game_data) - 1}")

    # ---- Cleanup ----

    def closeEvent(self, event):
        self._engine.stop()
        super().closeEvent(event)


def parse_hub_position(fen: str) -> tuple:
    """Parse Hub FEN string (51 chars: W/B + 50 squares) to pieces dict."""
    if len(fen) < 51:
        return {}, 'W'

    turn = fen[0]
    squares = fen[1:51]
    pieces = {}
    for i, ch in enumerate(squares):
        if ch in ('w', 'b', 'W', 'B'):
            sq = i + 1
            pieces[sq] = ch

    return pieces, turn


def parse_pdn_moves(text: str) -> list:
    """Extract a flat move list from PDN text.

    Handles tag headers ([...]), move numbers (1., 2., 1...), comments in
    {braces} or (parentheses), and result tags (1-0, 1/2-1/2, ...). Works for
    both move-numbered PDNs (lidraughts) and move-only PDNs (Scan output).
    Returns moves in standard draughts notation (e.g. "32-28", "28x17x22").
    """
    import re

    # Result tags (must NOT match quiet moves like "32-28")
    _results = {"1-0", "0-1", "2-0", "0-2", "1/2-1/2", "*"}

    # Remove tag lines
    text = re.sub(r"\[[^\]]*\]", " ", text)
    # Remove brace comments
    text = re.sub(r"\{[^}]*\}", " ", text)
    # Remove parenthesized variations
    text = re.sub(r"\([^)]*\)", " ", text)

    tokens = text.split()
    moves = []
    for tok in tokens:
        # Skip move-number tokens like "1.", "12.", "1..."
        if re.fullmatch(r"\d+\.+", tok):
            continue
        # Skip result tags
        if tok in _results:
            continue
        # Keep move tokens:
        #   quiet: digits-digits (e.g. 32-28)
        #   capture: digits x digits x ... (e.g. 28x17x22)
        if re.fullmatch(r"[0-9]+(?:-[0-9]+)+", tok):
            moves.append(tok)
        elif re.fullmatch(r"[0-9]+x[0-9xX]+", tok):
            moves.append(tok)
    return moves


def scan_fen_to_hub(fen: str):
    """Convert Scan FEN (e.g. 'B:W26,31,...:B1,2,...:H0:F6:+0+0') to hub FEN.

    Returns None if the FEN can't be parsed (caller then uses the start
    position). Handles comma lists, ranges (1-10), and king prefixes (K41).
    The trailing H/F/+n metadata sections are ignored.
    """
    if not fen:
        return None

    side = fen[0] if fen else ''
    if side not in ('W', 'B'):
        return None

    pieces = {}
    for part in fen.split(':'):
        part = part.strip()
        if not part or part[0] not in ('W', 'B'):
            continue
        color = part[0]
        for item in part[1:].split(','):
            item = item.strip()
            if not item:
                continue
            is_king = item.startswith('K')
            if is_king:
                item = item[1:]
            base = 'W' if color == 'W' else 'B'
            if '-' in item:  # range e.g. 1-10
                a, b = item.split('-')
                try:
                    for sq in range(int(a), int(b) + 1):
                        pieces[sq] = base if is_king else base.lower()
                except ValueError:
                    continue
            else:
                try:
                    sq = int(item)
                except ValueError:
                    continue
                pieces[sq] = base if is_king else base.lower()

    chars = [pieces.get(sq, 'e') for sq in range(1, 51)]
    return side + ''.join(chars)


def parse_pdn_games(text: str) -> list:
    """Parse a PDN file (possibly multiple games) into a list of games.

    Each game is a dict with keys:
      'moves': list of move strings
      'fen':   hub-FEN starting position, or None (=> standard start)
      'white','black','result': tag strings (may be empty)
    Games are split on the standard PDN separator (blank line + '[').
    """
    import re

    chunks = re.split(r"\n\s*\n(?=\[)", text)
    games = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Extract tags of interest
        tags = {}
        for tag in re.findall(r"\[(\w+)\s+\"([^\"]*)\"\]", chunk):
            tags[tag[0].lower()] = tag[1]

        fen = None
        if 'fen' in tags:
            fen = scan_fen_to_hub(tags['fen'])

        moves = parse_pdn_moves(chunk)
        if not moves:
            continue

        games.append({
            'moves': moves,
            'fen': fen,
            'white': tags.get('white', ''),
            'black': tags.get('black', ''),
            'result': tags.get('result', ''),
        })
    return games
