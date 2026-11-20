"""Absolute-import entry point with a diagnostic log for windowed startup errors."""
import sys
from pathlib import Path
import traceback


def boot():
    try:
        from tools.testbench.gui.__main__ import main
        return main()
    except Exception:
        (Path(sys.executable).parent/'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        return 1

if __name__ == '__main__':
    raise SystemExit(boot())
