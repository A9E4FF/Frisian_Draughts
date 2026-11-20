"""Frozen entry for the user-provided ScanGraphic source; built by build_scan_graphic."""
import argparse
import json
from pathlib import Path
import sys


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase, QFont
    from PySide6.QtWidgets import QApplication
    from gui.main import find_engine, _app_root
    from gui.main_window import MainWindow
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--smoke-output', type=Path)
    args = parser.parse_args()
    app = QApplication([])
    if sys.platform == 'win32' and not QFontDatabase.families():
        for font in ['segoeui.ttf', 'arial.ttf']:
            QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/font))
        app.setFont(QFont('Segoe UI', 9))
    engine = find_engine()
    if not engine: raise RuntimeError('scan.exe is missing next to ScanGraphic.exe')
    window = MainWindow(engine, _app_root()); window.show()
    if args.smoke_test:
        if args.smoke_output is None: raise RuntimeError('--smoke-output is required')
        results = {'ready': False, 'search_info': 0, 'evaluation': False, 'patterns': False}
        def ready():
            results['ready'] = True
            window._engine.send_command('level depth=2'); window._engine.send_command('go think')
        def done(move):
            results['move'] = move.get('move'); results['passed'] = bool(results['ready'] and results['search_info'] and results.get('move'))
            args.smoke_output.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_output.write_text(json.dumps(results), encoding='utf-8')
            window.close(); app.exit(0 if results['passed'] else 1)
        window._engine.ready.connect(ready)
        window._engine.info_received.connect(lambda _: results.update(search_info=results['search_info']+1))
        window._engine.eval_decompose_received.connect(lambda _: results.update(evaluation=True))
        window._engine.pattern_scores_received.connect(lambda _: results.update(patterns=True))
        window._engine.done_received.connect(done)
        def timeout():
            if not args.smoke_output.exists():
                args.smoke_output.write_text(json.dumps({**results, 'passed': False, 'error': 'timeout'}), encoding='utf-8')
                window.close(); app.exit(1)
        QTimer.singleShot(30000, timeout)
    return app.exec()


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception:
        import traceback
        (Path(sys.executable).parent/'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
