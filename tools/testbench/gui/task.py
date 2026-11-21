"""Background task shared by desktop hosts; Qt signals cross thread boundaries."""
from PySide6.QtCore import QThread, Signal


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
