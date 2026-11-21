"""EvalGraph - Line chart widget for eval decomposition over a game."""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush


# Component colors
SERIES = [
    ("total",    QColor(20, 20, 20),     True),   # thick dark
    ("material", QColor(30, 90, 220),    False),
    ("balance",  QColor(0, 150, 60),     False),
    ("pattern",  QColor(230, 120, 0),    False),
    ("king_pst", QColor(150, 60, 200),   False),
    ("king_mob", QColor(0, 170, 200),    False),
]


class EvalGraph(QWidget):
    """Draws line charts of eval components (material, balance, pattern, ...)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._data = []          # full per-ply dicts
        self._current_ply = 0
        self._quiet_only = True   # only plot quiet positions

    def set_data(self, data: list):
        """Set per-ply eval data (list of dicts with keys matching _keys)."""
        self._data = list(data)
        self._current_ply = 0
        self.update()

    def set_current_ply(self, ply: int):
        self._current_ply = max(0, min(ply, len(self._data) - 1)) if self._data else 0
        self.update()

    def set_quiet_only(self, enabled: bool):
        self._quiet_only = enabled
        self.update()

    def clear(self):
        self._data = []
        self.update()

    # ---- Painting ----

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._do_paint(painter)
        finally:
            painter.end()

    def _do_paint(self, painter: QPainter):
        painter.setRenderHint(QPainter.Antialiasing)

        if not self._data:
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Import a PDN game to see the evaluation graph")
            return

        m = 45          # left margin
        top = 15
        right = 10
        bot = 25
        w = self.width() - m - right
        h = self.height() - top - bot

        # Guard: widget too small — don't draw
        if w < 20 or h < 10:
            return

        n = len(self._data)

        # ------- Y-axis: smart auto-scale -------
        vals = []
        for d in self._data:
            if d and (not self._quiet_only or d.get("quiet", 1)):
                for k, _, _ in SERIES:
                    v = d.get(k)
                    if isinstance(v, (int, float)):
                        vals.append(v)

        max_abs = max([abs(v) for v in vals] + [0.5]) * 1.15

        # Pick a nice round top value
        if max_abs <= 0.5:
            y_hi = 0.5
        elif max_abs <= 1:
            y_hi = 1.0
        elif max_abs <= 2:
            y_hi = 2.0
        elif max_abs <= 5:
            y_hi = 5.0
        else:
            mag = 10 ** (len(str(int(max_abs))) - 1)
            y_hi = int(max_abs / mag + 0.999) * mag

        # Grid + y labels
        painter.setPen(QPen(QColor(200, 200, 200), 1, Qt.DashLine))
        painter.setFont(QFont("Arial", 8))
        for i in range(5):
            sy = top + h - int(i / 4.0 * h)
            sv = y_hi * (1 - i / 4.0 * 2)
            painter.drawLine(m, sy, m + w, sy)
            painter.setPen(QPen(QColor(60, 60, 60)))
            lbl = f"{sv:+.1f}" if abs(sv) < 10 else f"{sv:+.0f}"
            painter.drawText(QRect(2, sy - 7, m - 6, 14), Qt.AlignRight | Qt.AlignVCenter, lbl)
            painter.setPen(QPen(QColor(200, 200, 200), 1, Qt.DashLine))

        # Zero line
        y0 = top + h - int((y_hi - 0) / (2 * y_hi) * h)
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.drawLine(m, y0, m + w, y0)

        def to_x(ply):
            if n <= 1:
                return m + w // 2
            return m + int(ply / (n - 1) * w)

        def to_y(val):
            return top + h - int((y_hi - val) / (2 * y_hi) * h)

        # ------- Series lines (skip non-quiet positions) -------
        for key, color, bold in SERIES:
            if key not in self._data[0]:
                continue
            painter.setPen(QPen(color, 3 if bold else 2))

            pts = []
            for ply, d in enumerate(self._data):
                if d and (not self._quiet_only or d.get("quiet", 1)):
                    v = d.get(key)
                    if isinstance(v, (int, float)):
                        pts.append(QPoint(to_x(ply), to_y(v)))
            if len(pts) >= 2:
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])

        # ------- Current-ply cursor -------
        cx = to_x(self._current_ply)
        painter.setPen(QPen(QColor(255, 0, 0), 2))
        painter.drawLine(cx, top, cx, top + h)

        # ------- X labels -------
        painter.setPen(QPen(QColor(60, 60, 60)))
        step = max(1, n // 8)
        for ply in range(0, n, step):
            painter.drawText(QRect(to_x(ply) - 15, top + h + 4, 30, 14),
                             Qt.AlignCenter, str(ply))

        # ------- Legend -------
        lx, ly = m + 5, top + 2
        for key, color, _ in SERIES:
            if key not in self._data[0]:
                continue
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRect(lx, ly, 10, 10))
            painter.setPen(QPen(QColor(0, 0, 0)))
            painter.drawText(QRect(lx + 13, ly - 2, 70, 14), Qt.AlignLeft | Qt.AlignVCenter, key)
            ly += 13
