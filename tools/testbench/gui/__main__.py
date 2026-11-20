import sys


def main():
    try:
        from .window import launch
    except ImportError as exc:
        print(f'Install the desktop dependencies: python -m pip install -r tools/testbench/requirements-gui.txt\n{exc}', file=sys.stderr)
        return 1
    return launch()


if __name__ == '__main__':
    sys.exit(main())
