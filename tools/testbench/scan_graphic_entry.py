"""Launch the integrated ScanGraphic 0.1.0 desktop and packaged regression smoke."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase, QFont
    from PySide6.QtWidgets import QApplication
    from tools.scan_graphic.integrated import IntegratedWindow
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan-engine', type=Path)
    parser.add_argument('--rust-engine', type=Path)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--smoke-output', type=Path)
    args = parser.parse_args()
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]/'dist/ScanGraphic'
    scan = (args.scan_engine or root/'scan.exe').resolve()
    rust = (args.rust_engine or root/'Frisian_Draughts.exe').resolve()
    for file in (scan, rust):
        if not file.is_file(): raise RuntimeError(f'Missing bundled engine: {file.name}')
    app = QApplication([])
    app.setApplicationName('ScanGraphic'); app.setApplicationVersion('0.1.0')
    if sys.platform == 'win32' and not QFontDatabase.families():
        for font in ['segoeui.ttf', 'arial.ttf']: QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/font))
        app.setFont(QFont('Segoe UI', 9))
    window = IntegratedWindow(scan, scan.parent, rust); window.show()
    if args.smoke_test:
        if args.smoke_output is None: raise RuntimeError('--smoke-output is required')
        args.smoke_output.mkdir(parents=True, exist_ok=True)
        results = {'ready': False, 'search_info': 0, 'evaluation': False, 'patterns': False, 'analysis_done': False}
        started = time.monotonic(); replay_done = [False]
        def ready():
            results['ready'] = True
            window._engine.send_command('level depth=2'); window._engine.send_command('go think')
        def done(move): results.update(move=move.get('move'), analysis_done=True)
        window._engine.ready.connect(ready)
        window._engine.info_received.connect(lambda _: results.update(search_info=results['search_info']+1))
        window._engine.eval_decompose_received.connect(lambda _: results.update(evaluation=True))
        window._engine.pattern_scores_received.connect(lambda _: results.update(patterns=True))
        window._engine.done_received.connect(done)
        window._engine.game_analysis_received.connect(lambda data: replay_done.__setitem__(0, bool(data)))
        panel = window.matches
        panel.depth.setValue(1); panel.ply_cap.setValue(4)
        panel.starts.import_text('B:W31-50:B1-20')
        from tools.testbench import start_positions
        panel.starts.positions.extend(start_positions.fresh_setups(start_positions.original_tool_positions())); panel.starts.refresh()
        panel.output.setText(str(args.smoke_output/'matches'))
        phase = ['analysis']
        def finish(error=None):
            results.update(passed=error is None, games=len(panel.games), tabs=window.tabs.count())
            if error: results['error'] = error
            (args.smoke_output/'passed.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            window.close(); app.exit(0 if error is None else 1)
        def poll():
            try:
                if time.monotonic() - started > 90: raise ValueError('packaged workflow timeout')
                if phase[0] == 'analysis' and results['analysis_done']:
                    if not all(results[k] for k in ('ready','search_info','evaluation','patterns','move')): raise ValueError('Original Scan diagnostics failed')
                    window.tabs.setCurrentIndex(1); panel.run_matches(); phase[0] = 'matches'
                elif phase[0] == 'matches' and panel.worker is None:
                    if panel.last_error: raise ValueError(panel.last_error)
                    if len(panel.games) != 16 or any(g['termination'] != 'adjudication-ply-limit' for g in panel.games): raise ValueError('Paired Scan/Rust multi-FEN match failed')
                    from tools.testbench import pdn
                    from tools.testbench.referee import Referee
                    documents = pdn.loads((args.smoke_output/'matches/games.pdn').read_text(encoding='utf-8'))
                    for document in documents:
                        pdn.validate(document, Referee(str(rust)))
                        if document.errors: raise ValueError('; '.join(document.errors))
                    window.open_match(panel.games[4]); phase[0] = 'replay'
                elif phase[0] == 'replay' and replay_done[0]:
                    window._goto_ply(2)
                    if window._current_ply != 2: raise ValueError('Original game navigation failed')
                    results['replay'] = True; finish()
            except Exception as exc: finish(str(exc))
        timer = QTimer(); timer.timeout.connect(poll); timer.start(100)
    return app.exec()


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception:
        import traceback
        target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        (target/'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
