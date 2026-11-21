"""EngineProcess - Wrapper for Scan engine Hub protocol communication."""

import subprocess
import os
from PySide6.QtCore import QProcess, QByteArray, Signal, QObject, QTimer


class EngineProcess(QObject):
    """Manages a Scan engine process via Hub protocol over stdin/stdout."""

    # Signals
    ready = Signal()
    error_occurred = Signal(str)
    info_received = Signal(dict)          # search info (depth, score, nodes, pv)
    analysis_received = Signal(dict)       # analysis command response
    pattern_scores_received = Signal(list) # list of pattern info dicts
    move_list_received = Signal(list)      # list of move info dicts
    legal_moves_received = Signal(list)    # structured legal moves [(from,to,caps,type)]
    wing_control_received = Signal(dict)   # wing control info
    eval_decompose_received = Signal(dict) # eval decomposition
    game_analysis_received = Signal(list)  # per-ply eval series for a game
    tactics_received = Signal(list)         # unified shot/exchange/loss results
    done_received = Signal(dict)           # search complete
    raw_line = Signal(str)                 # any unrecognized line

    def __init__(self, engine_path: str, work_dir: str = None):
        super().__init__()
        self._engine_path = engine_path
        self._work_dir = work_dir or os.path.dirname(engine_path)
        self._process = None
        self._pending_callbacks = {}
        self._buffer = ""
        self._pattern_buffer = []
        self._move_buffer = []
        self._legal_moves = []
        self._game_buffer = []
        self._tactics_buffer = []

        # Timer to flush accumulated move list
        self._move_timer = QTimer(self)
        self._move_timer.setSingleShot(True)
        self._move_timer.setInterval(30)
        self._move_timer.timeout.connect(self._flush_moves)

        # Timer to flush accumulated unified tactics results
        self._tactics_timer = QTimer(self)
        self._tactics_timer.setSingleShot(True)
        self._tactics_timer.setInterval(5000)
        self._tactics_timer.timeout.connect(self._flush_tactics)

    def start(self):
        """Launch the engine and perform Hub handshake."""
        self._process = QProcess(self)
        if self._work_dir:
            self._process.setWorkingDirectory(self._work_dir)
        self._process.setProgram(self._engine_path)
        self._process.setArguments(["hub"])
        self._process.readyReadStandardOutput.connect(self._on_ready_read)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.started.connect(lambda: self.send_command("hub"))
        self._process.start()

    def stop(self):
        """Stop the engine."""
        if self._process and self._process.state() != QProcess.NotRunning:
            self.send_command("quit")
            self._process.waitForFinished(1000)
            self._process.kill()

    def send_command(self, command: str):
        """Send a raw command line to the engine."""
        if self._process and self._process.state() == QProcess.Running:
            self._process.write(QByteArray((command + "\n").encode("utf-8")))

    # ---- High-level commands ----

    def init_frisian(self):
        """Initialize engine for Frisian variant."""
        self.send_command("set-param name=variant value=frisian")
        self.send_command("init")

    def set_position(self, fen: str = None, moves: str = None):
        """Set the board position."""
        if fen:
            cmd = f'pos pos={fen}'
        else:
            cmd = 'pos start'
        if moves:
            cmd += f' moves="{moves}"'
        self.send_command(cmd)

    def start_analysis(self):
        """Start infinite analysis."""
        self.send_command("level infinite")
        self.send_command("go analyze")

    def stop_analysis(self):
        """Stop analysis."""
        self.send_command("stop")

    def request_analysis_data(self):
        """Request all analysis data for current position."""
        self.send_command("analysis")
        self.send_command("eval-decompose")
        self.send_command("pattern-scores")
        self.send_command("move-list")
        self.send_command("wing-control")

    def request_game_analysis(self, moves: str, fen: str = None):
        """Request per-ply eval decomposition for a move sequence."""
        self._game_buffer = []
        if fen:
            self.send_command(f'game-analysis pos={fen} moves="{moves}"')
        else:
            self.send_command(f'game-analysis moves="{moves}"')

    def request_tactics(self, search_depth: int = 20, quiet: int = 3, max_ply: int = 40):
        """Request unified tactical analysis (shots + exchanges in one list)."""
        self._tactics_buffer = []
        self.send_command(f"position-tactics search-depth={search_depth} quiet={quiet} max-ply={max_ply}")

    # ---- Internal parsing ----

    def _on_ready_read(self):
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._parse_line(line.strip())

    def _on_stderr(self):
        data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        if data.strip():
            print(f"[engine stderr] {data.strip()}")

    def _on_finished(self, exit_code, exit_status):
        print(f"[engine] Process finished: code={exit_code} status={exit_status}")

    def _on_error(self, error):
        self.error_occurred.emit(f"Engine process error: {error}")

    def _flush_moves(self):
        """Parse and emit accumulated move list as structured legal moves."""
        if not self._move_buffer:
            return

        raw_moves = list(self._move_buffer)
        self._move_buffer = []

        # Parse into structured (from, to, captured, type)
        structured = []
        for m in raw_moves:
            move_str = m["move"]
            mtype = m["type"]
            parsed = self._parse_move_string(move_str)
            if parsed:
                structured.append(parsed + (mtype,))

        self._legal_moves = structured
        self.move_list_received.emit(raw_moves)
        self.legal_moves_received.emit(structured)

    def _flush_tactics(self):
        """Emit accumulated unified tactics results."""
        if not self._tactics_buffer:
            return
        results = list(self._tactics_buffer)
        self._tactics_buffer = []
        self.tactics_received.emit(results)

    @staticmethod
    def _parse_move_string(s: str):
        """Parse Hub move string into (from, to, captured_tuple).

        Quiet:   "32-28" -> (32, 28, ())
        Capture: "28x17x22" -> (28, 22, (17,))   [from x to x cap1 x cap2 ...]
        Returns None if unparseable.
        """
        try:
            if 'x' in s:
                parts = s.split('x')
                if len(parts) >= 3:
                    from_sq = int(parts[0])
                    to_sq = int(parts[1])
                    caps = tuple(int(p) for p in parts[2:])
                    return (from_sq, to_sq, caps)
                elif len(parts) == 2:
                    # from x to (single, no explicit caps listed)
                    return (int(parts[0]), int(parts[1]), ())
                return None
            elif '-' in s:
                a, b = s.split('-')
                return (int(a), int(b), ())
            else:
                return None
        except ValueError:
            return None

    def _parse_line(self, line: str):
        """Parse a single Hub protocol line."""
        if not line:
            return

        parts = self._split_pairs(line)
        if not parts:
            return

        cmd = parts[0][0]  # first word is the command
        pairs = dict(parts[1:])

        if cmd == "ready":
            self.ready.emit()

        elif cmd == "info":
            parsed = {
                "depth": int(pairs.get("depth", 0)),
                "mean_depth": float(pairs.get("mean-depth", 0)),
                "score": float(pairs.get("score", 0)),
                "nodes": int(pairs.get("nodes", 0)),
                "time": float(pairs.get("time", 0)),
                "nps": float(pairs.get("nps", 0)),
                "pv": pairs.get("pv", ""),
            }
            self.info_received.emit(parsed)

        elif cmd == "done":
            parsed = {
                "move": pairs.get("move", ""),
                "ponder": pairs.get("ponder", ""),
            }
            self.done_received.emit(parsed)

        elif cmd == "eval-info":
            parsed = {
                "total": float(pairs.get("total", 0)),
                "material": float(pairs.get("material", 0)),
                "king_pst": float(pairs.get("king-pst", 0)),
                "king_mob": float(pairs.get("king-mob", 0)),
                "balance": float(pairs.get("balance", 0)),
                "pattern": float(pairs.get("pattern", 0)),
                "wolf": float(pairs.get("wolf", 0)),
                "stage": int(pairs.get("stage", 0)),
            }
            self.eval_decompose_received.emit(parsed)

        elif cmd == "pattern-info":
            parsed = {
                "col": int(pairs.get("col", 0)),
                "sq": int(pairs.get("sq", 0)),
                "index": int(pairs.get("index", 0)),
                "mg": float(pairs.get("mg", 0)),
                "eg": float(pairs.get("eg", 0)),
                "score": float(pairs.get("score", 0)),
            }
            self._pattern_buffer.append(parsed)
            if len(self._pattern_buffer) == 8:
                self.pattern_scores_received.emit(list(self._pattern_buffer))
                self._pattern_buffer = []

        elif cmd == "move-info":
            parsed = {
                "move": pairs.get("move", ""),
                "type": pairs.get("type", "quiet"),
            }
            # Accumulate all moves, emit when next non-move-info arrives
            if not hasattr(self, '_move_buffer'):
                self._move_buffer = []
            self._move_buffer.append(parsed)
            self._move_timer.start()

        elif cmd == "analysis":
            parsed = {
                "tempo": int(pairs.get("tempo", 0)),
                "stage": int(pairs.get("stage", 0)),
                "w_wolf": pairs.get("w-wolf", "none"),
                "w_count": int(pairs.get("w-count", 0)),
                "b_wolf": pairs.get("b-wolf", "none"),
                "b_count": int(pairs.get("b-count", 0)),
                "wm": int(pairs.get("wm", 0)),
                "bm": int(pairs.get("bm", 0)),
                "wk": int(pairs.get("wk", 0)),
                "bk": int(pairs.get("bk", 0)),
                "skew_w": int(pairs.get("skew-w", 0)),
                "skew_b": int(pairs.get("skew-b", 0)),
            }
            self.analysis_received.emit(parsed)

        elif cmd == "wing":
            parsed = {
                "left_w": int(pairs.get("left-w", 0)),
                "left_b": int(pairs.get("left-b", 0)),
                "left_c": int(pairs.get("left-c", 0)),
                "right_w": int(pairs.get("right-w", 0)),
                "right_b": int(pairs.get("right-b", 0)),
                "right_c": int(pairs.get("right-c", 0)),
            }
            self.wing_control_received.emit(parsed)

        elif cmd == "game-eval":
            parsed = {
                "ply": int(pairs.get("ply", 0)),
                "pos": pairs.get("pos", ""),
                "total": float(pairs.get("total", 0)),
                "material": float(pairs.get("material", 0)),
                "king_pst": float(pairs.get("king-pst", 0)),
                "king_mob": float(pairs.get("king-mob", 0)),
                "balance": float(pairs.get("balance", 0)),
                "pattern": float(pairs.get("pattern", 0)),
                "wolf": float(pairs.get("wolf", 0)),
                "stage": int(pairs.get("stage", 0)),
                "quiet": int(pairs.get("quiet", 1)),
            }
            self._game_buffer.append(parsed)

        elif cmd == "game-analysis-end":
            self.game_analysis_received.emit(list(self._game_buffer))
            self._game_buffer = []

        elif cmd == "tactical-info":
            parsed = {
                "move": pairs.get("move", ""),
                "type": pairs.get("type", "quiet"),
                "eval": float(pairs.get("eval", 0)),
                "give": int(pairs.get("give", 0)),
                "take": int(pairs.get("take", 0)),
                "net": int(pairs.get("net", 0)),
                "pv": pairs.get("pv", ""),
            }
            self._tactics_buffer.append(parsed)
            self._tactics_timer.start()

        elif cmd == "analysis-done":
            # Explicit end marker — flush immediately
            self._tactics_timer.stop()
            self._flush_tactics()

        elif cmd == "error":
            msg = pairs.get("message", "unknown error")
            self.error_occurred.emit(f"Engine: {msg}")

        elif cmd == "id":
            pass  # engine identification, ignore

        elif cmd == "param":
            pass  # parameter declaration, ignore

        elif cmd == "wait":
            # Engine finished sending params — now send variant + init
            self.init_frisian()

        elif cmd == "pong":
            pass  # ping response

        else:
            self.raw_line.emit(line)

    @staticmethod
    def _split_pairs(line: str) -> list:
        """Parse Hub protocol line into list of (name, value) tuples."""
        result = []
        i = 0
        n = len(line)

        while i < n:
            # Skip whitespace
            while i < n and line[i] in ' \t':
                i += 1
            if i >= n:
                break

            # Read name (until = or whitespace)
            name_start = i
            while i < n and line[i] not in ' \t=':
                i += 1
            name = line[name_start:i]

            # Skip whitespace before =
            while i < n and line[i] in ' \t':
                i += 1

            value = ""
            if i < n and line[i] == '=':
                i += 1  # skip =
                # Skip whitespace after =
                while i < n and line[i] in ' \t':
                    i += 1
                # Read value (quoted or unquoted)
                if i < n and line[i] == '"':
                    i += 1  # skip opening quote
                    val_start = i
                    while i < n and line[i] != '"':
                        i += 1
                    value = line[val_start:i]
                    if i < n:
                        i += 1  # skip closing quote
                else:
                    val_start = i
                    while i < n and line[i] not in ' \t':
                        i += 1
                    value = line[val_start:i]

            result.append((name, value))

        return result
