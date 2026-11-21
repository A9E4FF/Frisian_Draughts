#!/usr/bin/env python3
"""Scan 3.1 — Frisian Draughts Analysis GUI

Launches the Scan engine in Hub mode and provides a graphical interface
for position analysis with pattern heatmap, wing control, legal-move
playback, and eval decomposition.
"""

import sys
import os

# Add parent directory to path for absolute imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# Auto-detect venv Python if running with wrong interpreter (dev only; a
# frozen app bundles PySide6 and never reaches this relaunch path).
if not getattr(sys, "frozen", False):
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        venv_python = os.path.join(_project_root, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python):
            print(f"PySide6 not found in current Python. Re-launching with venv: {venv_python}")
            os.execv(venv_python, [venv_python] + sys.argv)
        else:
            sys.exit(
                "PySide6 is not installed.\n\n"
                "Run: pip install PySide6\n"
                "Or use the project venv: .venv\\Scripts\\python.exe gui/main.py"
            )
else:
    from PySide6.QtWidgets import QApplication, QMessageBox

from PySide6.QtCore import QDir

from tools.scan_graphic.main_window import MainWindow


def _app_root() -> str:
    """Directory that anchors runtime file discovery.

    Frozen (PyInstaller): the folder containing the executable, which also
    holds scan.exe, scan.ini and data/ in the flat onedir layout.
    Dev: the project root (parent of gui/).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_engine() -> str:
    """Find the scan.exe engine binary."""
    base = _app_root()
    candidates = [
        os.path.join(base, "scan.exe"),
        os.path.join(base, "src", "scan.exe"),
        os.path.join(base, "gui", "scan.exe"),
        "scan.exe",
    ]
    for path in candidates:
        abs_path = os.path.normpath(path)
        if os.path.exists(abs_path):
            return abs_path
    return ""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Scan Analysis GUI")
    app.setOrganizationName("Scan")

    engine_path = find_engine()
    if not engine_path:
        QMessageBox.critical(None, "Engine Not Found",
            "Could not find scan.exe.\n\n"
            "Place scan.exe in the same directory as this script,\n"
            "or in the 'src' directory.")
        return 1

    # Engine needs scan.ini and data/ in its working directory
    if getattr(sys, "frozen", False):
        work_dir = _app_root()  # flat dist layout: scan.ini + data/ next to exe
    else:
        work_dir = os.path.dirname(os.path.dirname(engine_path))  # parent of src/
        if not os.path.exists(os.path.join(work_dir, "scan.ini")):
            work_dir = os.path.dirname(engine_path)  # fallback

    print(f"Using engine: {engine_path}")
    print(f"Working dir: {work_dir}")

    window = MainWindow(engine_path, work_dir)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
