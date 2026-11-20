"""Board widget adapted from the user-supplied ScanGraphic GUI.

Retains the original board/heatmap rendering; rules come from the referee.
Distributed with this project under GPL-3.0-only; see NOTICE.md.
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath


# Board geometry
FILES = 10
RANKS = 10
DARK_SQUARES = 50

# Colors
LIGHT_SQUARE = QColor(240, 217, 181)   # cream
DARK_SQUARE_COLOR = QColor(181, 136, 99)  # brown
WHITE_PIECE = QColor(255, 255, 255)
BLACK_PIECE = QColor(50, 50, 50)
WHITE_PIECE_BORDER = QColor(80, 80, 80)
BLACK_PIECE_BORDER = QColor(30, 30, 30)
HIGHLIGHT = QColor(255, 255, 0, 80)
WOLF_RING = QColor(255, 165, 0)  # orange ring for wolf kings

# Heatmap colors
HEAT_GREEN = QColor(0, 180, 0)
HEAT_RED = QColor(220, 0, 0)


class BoardWidget(QWidget):
    """Displays a 10x10 draughts board with pieces and analysis overlays."""

    # Signals
    position_changed = Signal()          # pieces modified (setup mode)
    move_played = Signal(int, int, list) # (from, to, captured_list) legal move played

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 500)
        self.setMouseTracking(False)

        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy()
        )

        # Game state
        self._pieces = {}       # square_num -> 'w'/'b'/'W'/'B'
        self._turn = 'W'        # side to move
        self._wolf_white = None # wolf king square
        self._wolf_black = None
        self._wolf_count_w = 0
        self._wolf_count_b = 0

        # Overlays
        self._heatmap = {}      # square_num -> float score (-1..+1 normalized)
        self._highlights = set()  # highlighted squares (e.g., legal moves)
        self._arrows = []        # list of (from_sq, to_sq, color_tuple, label)

        # Layout
        self._margin = 30
        self._square_size = 50
        self._flipped = False  # White at top by default
        self._show_coords = True
        self._show_heatmap = True
        self._heatmap_persp = 'W'  # 'W' = show from White's view, 'B' = Black's view

        # Drag state
        self._drag_square = None   # square being dragged from
        self._drag_piece = None    # piece character ('w','b','W','B')
        self._drag_pos = None      # cursor position during drag

        # Legal moves: list of (from, to, captured_tuple, type)
        self._legal_moves = []
        self._legality_check = False   # when True, only legal moves are allowed

    # ---- Mouse interaction (drag & drop only) ----

    def mousePressEvent(self, event):
        sq = self.square_at_pos(event.position().toPoint())

        if event.button() == Qt.RightButton and not self._legality_check:
            if sq != 0:
                self._cycle_piece(sq)

        elif event.button() == Qt.LeftButton:
            if sq != 0 and sq in self._pieces:
                # Start drag — remove piece from board, it follows cursor
                self._drag_square = sq
                self._drag_piece = self._pieces.pop(sq)
                self._drag_pos = event.position().toPoint()
                self.update()

    def mouseMoveEvent(self, event):
        if self._drag_square is not None:
            self._drag_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_square is None:
            return

        target = self.square_at_pos(event.position().toPoint())
        from_sq = self._drag_square

        if self._legality_check:
            # Find matching legal move (from == from_sq, to == target)
            move = self._find_legal_move(from_sq, target)
            if move is not None:
                _, _, caps, mtype = move
                # Promote man -> king if it lands on its promotion rank
                # (covers quiet promotions AND captures ending on the last rank)
                piece = self._drag_piece
                if piece in ('w', 'b'):
                    _, dest_rank = self._num_to_file_rank(target)
                    promo_rank = 0 if piece == 'w' else 9
                    if dest_rank == promo_rank:
                        piece = piece.upper()  # 'w'->'W', 'b'->'B'
                # Place piece at target, remove captured pieces
                self._pieces.pop(target, None)
                self._pieces[target] = piece
                for c in caps:
                    self._pieces.pop(c, None)
                self._drag_square = None
                self._drag_piece = None
                self._drag_pos = None
                self.move_played.emit(from_sq, target, list(caps))
                self.position_changed.emit()
                self.update()
                return
            # Not a legal move — snap back
            self._pieces[from_sq] = self._drag_piece
        else:
            # Free setup mode: allow any placement
            if target != 0 and target != from_sq:
                self._pieces.pop(target, None)
                self._pieces[target] = self._drag_piece
            else:
                self._pieces[from_sq] = self._drag_piece
            self.position_changed.emit()

        self._drag_square = None
        self._drag_piece = None
        self._drag_pos = None
        self.update()

    def _find_legal_move(self, from_sq: int, to_sq: int):
        """Find a legal move matching from/to, or None."""
        matches = [mv for mv in self._legal_moves if mv[0] == from_sq and mv[1] == to_sq]
        # Endpoints can identify several Frisian captures. Use the full move
        # selector in that case rather than choosing an arbitrary capture set.
        return matches[0] if len(matches) == 1 else None

    def _cycle_piece(self, sq: int):
        """Right-click: cycle piece type on a square."""
        if sq in self._pieces:
            current = self._pieces[sq]
            if current == 'w':
                self._pieces[sq] = 'W'
            elif current == 'W':
                del self._pieces[sq]
            elif current == 'b':
                self._pieces[sq] = 'B'
            elif current == 'B':
                del self._pieces[sq]
        else:
            # Empty square: place opponent's man
            self._pieces[sq] = 'b' if self._turn == 'W' else 'w'
        self.position_changed.emit()
        self.update()

    # ---- Public API ----

    def set_position(self, pieces: dict, turn: str = 'W'):
        """Set piece positions. pieces: {square_num (1-50): piece_char}."""
        self._pieces = pieces.copy()
        self._turn = turn
        self.update()

    def set_wolf_info(self, w_wolf: str, w_count: int, b_wolf: str, b_count: int):
        """Set wolf king info."""
        try:
            self._wolf_white = int(w_wolf) if w_wolf != "none" else None
        except (ValueError, TypeError):
            self._wolf_white = None
        self._wolf_count_w = w_count
        try:
            self._wolf_black = int(b_wolf) if b_wolf != "none" else None
        except (ValueError, TypeError):
            self._wolf_black = None
        self._wolf_count_b = b_count
        self.update()

    def set_heatmap(self, patterns: list):
        """Set pattern heatmap data.

        The 8 "columns" are overlapping 4-file sliding windows:
          cols 0-3 (ranks 0-5): files (0-3),(2-5),(4-7),(6-9)
          cols 4-7 (ranks 4-9): files (0-3),(2-5),(4-7),(6-9)
        The full board (files 0-9) is covered. Squares in an overlap
        region get the average score of the covering columns.
        """
        self._heatmap = {}
        col_scores = {p["col"]: p["score"] for p in patterns}

        for f in range(FILES):
            for r in range(RANKS):
                if (f + r) % 2 == 0:
                    continue  # light square

                scores = []
                for c in range(8):
                    lo = 2 * (c % 4)
                    hi = lo + 3
                    if lo <= f <= hi:
                        if c < 4 and 0 <= r <= 5:
                            scores.append(col_scores.get(c, 0.0))
                        elif c >= 4 and 4 <= r <= 9:
                            scores.append(col_scores.get(c, 0.0))

                if scores:
                    num = self._file_rank_to_num(f, r)
                    self._heatmap[num] = sum(scores) / len(scores)

        self.update()

    def set_highlights(self, squares: set):
        """Highlight specific squares (e.g., legal move destinations)."""
        self._highlights = squares
        self.update()

    def set_arrows(self, arrows: list):
        """Set tactical arrows: list of (from_sq, to_sq, color_name, label).
        Colors: 'green' (combo), 'red' (threat), 'blue' (defense), 'orange' (warning)."""
        self._arrows = arrows
        self.update()

    def set_legal_moves(self, moves: list):
        """Set legal moves: list of (from, to, captured_tuple, type)."""
        self._legal_moves = moves
        self.update()

    def set_legality_check(self, enabled: bool):
        """When True, only legal moves from the engine are allowed."""
        self._legality_check = enabled
        self.update()

    def set_flipped(self, flipped: bool):
        """Flip board orientation."""
        self._flipped = flipped
        self.update()

    def set_turn(self, turn: str):
        """Set side to move ('W' or 'B')."""
        self._turn = turn
        self.update()

    def get_turn(self) -> str:
        return self._turn

    def get_pieces(self) -> dict:
        return self._pieces.copy()

    def to_hub_fen(self) -> str:
        """Convert current position to Hub FEN string (51 chars)."""
        chars = []
        for sq in range(1, 51):
            chars.append(self._pieces.get(sq, 'e'))
        return self._turn + ''.join(chars)

    def set_show_heatmap(self, show: bool):
        self._show_heatmap = show
        self.update()

    def set_heatmap_perspective(self, persp: str):
        """Set heatmap perspective: 'W' (White's view) or 'B' (Black's view).

        White view: green = pattern favors White, red = favors Black.
        Black view: green = pattern favors Black, red = favors White.
        """
        self._heatmap_persp = 'B' if persp == 'B' else 'W'
        self.update()

    def square_at_pos(self, pos: QPoint) -> int:
        """Convert mouse position to square number (1-50), or 0 if none."""
        # Account for the scaling/centering transform applied in paintEvent
        board_size = self._square_size * 10
        total_w = board_size + 2 * self._margin
        total_h = board_size + 2 * self._margin
        scale_x = self.width() / total_w if total_w > 0 else 1
        scale_y = self.height() / total_h if total_h > 0 else 1
        scale = min(scale_x, scale_y)
        offset_x = (self.width() - total_w * scale) / 2
        offset_y = (self.height() - total_h * scale) / 2

        bx = (pos.x() - offset_x) / scale
        by = (pos.y() - offset_y) / scale

        if bx < self._margin or by < self._margin:
            return 0
        col = int((bx - self._margin) // self._square_size)
        row = int((by - self._margin) // self._square_size)
        if col < 0 or col >= 10 or row < 0 or row >= 10:
            return 0
        if self._flipped:
            col = 9 - col
            row = 9 - row
        if (col + row) % 2 == 0:  # light square
            return 0
        return self._file_rank_to_num(col, row)

    # ---- Painting ----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        board_size = self._square_size * 10
        total_w = board_size + 2 * self._margin
        total_h = board_size + 2 * self._margin

        # Scale to fit
        scale_x = self.width() / total_w
        scale_y = self.height() / total_h
        scale = min(scale_x, scale_y)
        painter.translate(
            (self.width() - total_w * scale) / 2,
            (self.height() - total_h * scale) / 2
        )
        painter.scale(scale, scale)

        self._draw_board(painter)
        self._draw_heatmap(painter)
        self._draw_pieces(painter)
        self._draw_drag_piece(painter)
        self._draw_overlays(painter)
        self._draw_arrows(painter)
        self._draw_coordinates(painter)

    def _draw_board(self, painter: QPainter):
        """Draw the board squares."""
        for f in range(FILES):
            for r in range(RANKS):
                x = self._margin + f * self._square_size
                y = self._margin + r * self._square_size
                rect = QRect(x, y, self._square_size, self._square_size)

                if (f + r) % 2 == 1:
                    painter.fillRect(rect, DARK_SQUARE_COLOR)
                else:
                    painter.fillRect(rect, LIGHT_SQUARE)

    def _draw_heatmap(self, painter: QPainter):
        """Draw pattern heatmap overlay on dark squares."""
        if not self._show_heatmap or not self._heatmap:
            return

        max_abs = max(abs(v) for v in self._heatmap.values()) if self._heatmap else 1
        if max_abs == 0:
            max_abs = 1

        for f in range(FILES):
            for r in range(RANKS):
                if (f + r) % 2 == 0:
                    continue  # light square

                num = self._file_rank_to_num(f, r)

                df = 9 - f if self._flipped else f
                dr = 9 - r if self._flipped else r

                x = self._margin + df * self._square_size
                y = self._margin + dr * self._square_size

                if num in self._heatmap:
                    score = self._heatmap[num]
                    # Apply perspective: Black view flips the sign
                    if self._heatmap_persp == 'B':
                        score = -score
                    intensity = min(abs(score) / max_abs, 1.0) * 0.6
                    if score >= 0:
                        color = QColor(
                            int(0 * intensity + 181 * (1 - intensity)),
                            int(180 * intensity + 136 * (1 - intensity)),
                            int(0 * intensity + 99 * (1 - intensity))
                        )
                    else:
                        color = QColor(
                            int(220 * intensity + 181 * (1 - intensity)),
                            int(0 * intensity + 136 * (1 - intensity)),
                            int(0 * intensity + 99 * (1 - intensity))
                        )
                else:
                    # Uncovered by pattern system (files 8-9) — subtle gray hash
                    color = QColor(160, 140, 120)

                rect = QRect(x + 2, y + 2, self._square_size - 4, self._square_size - 4)
                painter.fillRect(rect, color)

        # Legend
        legend_x = self._margin + FILES * self._square_size + 8
        legend_y = self._margin + RANKS * self._square_size - 70
        font = QFont("Arial", 9)
        painter.setFont(font)

        if self._heatmap_persp == 'B':
            strong = "Black"
            weak = "White"
        else:
            strong = "White"
            weak = "Black"

        # Green legend (favors current perspective)
        painter.fillRect(QRect(legend_x, legend_y, 12, 12), QColor(0, 140, 0))
        painter.setPen(QPen(QColor(0, 0, 0)))
        painter.drawText(legend_x + 16, legend_y + 11, f"+ {strong}")

        # Red legend (favors opponent)
        painter.fillRect(QRect(legend_x, legend_y + 16, 12, 12), QColor(200, 60, 40))
        painter.drawText(legend_x + 16, legend_y + 27, f"− {weak}")

    def _draw_pieces(self, painter: QPainter):
        """Draw pieces on the board."""
        for num, piece in self._pieces.items():
            f, r = self._num_to_file_rank(num)
            if self._flipped:
                f = 9 - f
                r = 9 - r

            cx = int(self._margin + (f + 0.5) * self._square_size)
            cy = int(self._margin + (r + 0.5) * self._square_size)
            radius = int(self._square_size * 0.4)

            is_white = piece in ('w', 'W')
            is_king = piece in ('W', 'B')

            # Piece body
            if is_white:
                painter.setBrush(QBrush(WHITE_PIECE))
                painter.setPen(QPen(WHITE_PIECE_BORDER, 2))
            else:
                painter.setBrush(QBrush(BLACK_PIECE))
                painter.setPen(QPen(BLACK_PIECE_BORDER, 2))

            painter.drawEllipse(QPoint(cx, cy), radius, radius)

            # King crown (inner circle)
            if is_king:
                inner_radius = int(radius * 0.55)
                if is_white:
                    painter.setBrush(QBrush(QColor(220, 220, 220)))
                else:
                    painter.setBrush(QBrush(QColor(80, 80, 80)))
                painter.drawEllipse(QPoint(cx, cy), inner_radius, inner_radius)

            # Wolf ring
            if (is_white and num == self._wolf_white) or \
               (not is_white and num == self._wolf_black):
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(WOLF_RING, 3))
                painter.drawEllipse(QPoint(cx, cy), radius + 3, radius + 3)

    def _draw_drag_piece(self, painter: QPainter):
        """Draw the piece being dragged at the cursor position."""
        if self._drag_square is None or self._drag_piece is None or self._drag_pos is None:
            return

        # Save painter state and reset transform to widget coordinates
        painter.save()
        # Reset to identity transform so we can draw directly at widget position
        painter.resetTransform()

        is_white = self._drag_piece in ('w', 'W')
        is_king = self._drag_piece in ('W', 'B')

        cx = int(self._drag_pos.x())
        cy = int(self._drag_pos.y())
        radius = int(self._square_size * 0.4)

        # Semi-transparent piece
        painter.setOpacity(0.75)

        if is_white:
            painter.setBrush(QBrush(WHITE_PIECE))
            painter.setPen(QPen(WHITE_PIECE_BORDER, 2))
        else:
            painter.setBrush(QBrush(BLACK_PIECE))
            painter.setPen(QPen(BLACK_PIECE_BORDER, 2))

        painter.drawEllipse(QPoint(cx, cy), radius, radius)

        if is_king:
            inner_radius = int(radius * 0.55)
            if is_white:
                painter.setBrush(QBrush(QColor(220, 220, 220)))
            else:
                painter.setBrush(QBrush(QColor(80, 80, 80)))
            painter.drawEllipse(QPoint(cx, cy), inner_radius, inner_radius)

        painter.setOpacity(1.0)
        painter.restore()

    def _draw_overlays(self, painter: QPainter):
        """Draw highlights."""
        for num in self._highlights:
            f, r = self._num_to_file_rank(num)
            if self._flipped:
                f = 9 - f
                r = 9 - r
            x = self._margin + f * self._square_size
            y = self._margin + r * self._square_size
            painter.fillRect(QRect(x, y, self._square_size, self._square_size),
                           HIGHLIGHT)

    def _draw_arrows(self, painter: QPainter):
        """Draw tactical analysis arrows."""
        if not self._arrows:
            return

        color_map = {
            'green': QColor(0, 180, 0, 180),
            'red': QColor(220, 40, 40, 180),
            'blue': QColor(40, 100, 220, 180),
            'orange': QColor(240, 160, 40, 180),
            'purple': QColor(150, 50, 200, 180),
            'violet': QColor(180, 80, 220, 180),
            'magenta': QColor(220, 60, 160, 180),
            'gold': QColor(220, 180, 40, 180),
            'gray': QColor(150, 150, 150, 180),
        }

        for from_sq, to_sq, color_name, label in self._arrows:
            f1, r1 = self._num_to_file_rank(from_sq)
            f2, r2 = self._num_to_file_rank(to_sq)
            if self._flipped:
                f1, r1 = 9 - f1, 9 - r1
                f2, r2 = 9 - f2, 9 - r2

            cx1 = int(self._margin + (f1 + 0.5) * self._square_size)
            cy1 = int(self._margin + (r1 + 0.5) * self._square_size)
            cx2 = int(self._margin + (f2 + 0.5) * self._square_size)
            cy2 = int(self._margin + (r2 + 0.5) * self._square_size)

            color = color_map.get(color_name, QColor(255, 255, 0, 180))
            pen = QPen(color, max(3, self._square_size // 12))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(cx1, cy1, cx2, cy2)

            # Arrowhead
            import math
            dx = cx2 - cx1
            dy = cy2 - cy1
            length = math.sqrt(dx * dx + dy * dy)
            if length > 5:
                ux, uy = dx / length, dy / length
                head_len = self._square_size * 0.25
                head_w = self._square_size * 0.12
                # Left wing
                lx = cx2 - ux * head_len + uy * head_w
                ly = cy2 - uy * head_len - ux * head_w
                # Right wing
                rx = cx2 - ux * head_len - uy * head_w
                ry = cy2 - uy * head_len + ux * head_w
                path = QPainterPath()
                path.moveTo(cx2, cy2)
                path.lineTo(lx, ly)
                path.lineTo(rx, ry)
                path.closeSubpath()
                painter.setBrush(QBrush(color))
                painter.drawPath(path)

    def _draw_coordinates(self, painter: QPainter):
        """Draw square numbers on the board."""
        if not self._show_coords:
            return

        font = QFont("Arial", max(6, self._square_size // 5))
        painter.setFont(font)
        painter.setPen(QPen(QColor(60, 60, 60)))

        for f in range(FILES):
            for r in range(RANKS):
                if (f + r) % 2 == 0:  # only dark squares
                    continue
                num = self._file_rank_to_num(f, r)
                if self._flipped:
                    df = 9 - f
                    dr = 9 - r
                else:
                    df = f
                    dr = r
                x = self._margin + df * self._square_size + 3
                y = self._margin + (dr + 1) * self._square_size - 3
                painter.drawText(x, y, str(num))

    # ---- Coordinate helpers ----

    @staticmethod
    def _file_rank_to_num(f: int, r: int) -> int:
        """Convert file (0-9) and rank (0-9, 0=top) to draughts square number (1-50)."""
        return r * 5 + (f // 2) + 1

    @staticmethod
    def _num_to_file_rank(num: int) -> tuple:
        """Convert draughts square number (1-50) to (file, rank). Rank 0 = top."""
        n = num - 1
        r = n // 5
        f = (n % 5) * 2 + (1 - r % 2)  # staggered: even rows start file 1, odd rows start file 0
        return f, r

    def sizeHint(self):
        return QSize(600, 600)
