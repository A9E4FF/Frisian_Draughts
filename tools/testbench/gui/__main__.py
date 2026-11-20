import sys


def main():
    try:
        from .window import launch
    except ImportError as exc:
        if getattr(sys, 'frozen', False): raise
        print(f'Install the desktop dependencies: python -m pip install -r tools/testbench/requirements-gui.txt\n{exc}', file=sys.stderr)
        return 1
    if '--smoke-test' in sys.argv:
        return smoke()
    return launch()


def smoke():
    """Exercise a packaged launch, paired games and PDN roundtrip in CI."""
    import argparse
    import json
    from pathlib import Path
    import time
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .window import Window
    from tools.testbench.profiles import entrant
    from tools.testbench.referee import Referee
    from tools.testbench import pdn
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--smoke-output', type=Path, required=True)
    args = parser.parse_args()
    args.smoke_output.mkdir(parents=True, exist_ok=False)
    app = QApplication([]); window = Window(); engine = window.referee.text()
    window.engines = [entrant('Rust A', engine), entrant('Rust B', engine)]; window.refresh_profiles()
    window.depth.setValue(1); window.ply_cap.setValue(2)
    output = args.smoke_output / 'match'; window.output.setText(str(output)); window.show(); window.run_matches()
    started = time.monotonic()
    def poll():
        if time.monotonic() - started > 30: window.cancel()
        if window.worker is not None: return
        try:
            games = json.loads((output/'games.json').read_text(encoding='utf-8'))
            if len(games) != 2 or any(g['termination'] != 'adjudication-ply-limit' for g in games):
                raise ValueError('packaged match workflow failed')
            documents = pdn.loads((output/'games.pdn').read_text(encoding='utf-8'))
            for game in documents:
                pdn.validate(game, Referee(engine))
                if game.errors: raise ValueError('; '.join(game.errors))
            (args.smoke_output/'passed.json').write_text(json.dumps({'passed': True, 'games': len(games), 'tabs': window.tabs.count()}), encoding='utf-8')
            window.close(); app.exit(0)
        except Exception as exc:
            (args.smoke_output/'error.txt').write_text(str(exc) + '\n' + window.log.toPlainText(), encoding='utf-8')
            window.close(); app.exit(1)
    timer = QTimer(); timer.timeout.connect(poll); timer.start(100)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
