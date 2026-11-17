"""Headless suite runner with optional any-of expected-move verdicts."""
import argparse
from pathlib import Path
import re
import sys

from .client import AnalysisSession, format_event, format_header
from .model import DEFAULT_ENGINE, load_suite


def run_suite(args):
    try:
        cases = load_suite(args.suite)
        args.logs.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    counts = {}
    try:
        for index, original in enumerate(cases, 1):
            case = dict(original)
            if args.depth is not None:
                case['depth'] = args.depth
            if args.no_tt:
                case['tt_enabled'] = False
            parts = [format_header(case, args.engine)]
            def receive(event):
                parts.append(format_event(event))
                if args.verbose:
                    print(format_event(event), end='', flush=True)
            if args.protocol == 'hub':
                from tools.testbench.positions import HubAnalysisSession
                session = HubAnalysisSession(args.engine, args.referee, cwd=args.engine_cwd)
            else:
                session = AnalysisSession(args.engine)
            outcome = session.run(case, receive)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            parts.append(f'\nSTATUS: {outcome.status.upper()}\n{outcome.message}\n')
            safe = re.sub(r'[^A-Za-z0-9_-]+', '-', case['name']).strip('-') or 'position'
            path = args.logs / f'{index:03d}-{safe}.txt'
            path.write_text(''.join(parts), encoding='utf-8')
            print(f"{outcome.status.upper():8} {case['name']}  [{path}]")
        print('Summary: ' + (', '.join(f'{n} {status}' for status, n in sorted(counts.items())) or 'no positions'))
    except KeyboardInterrupt:
        # CLI Ctrl-C also reaches a foreground child; explicitly stop it when possible.
        print('\nCancelled; no success verdict for the interrupted position.', file=sys.stderr)
        return 130
    except OSError as exc:
        print(f'Error writing logs: {exc}', file=sys.stderr)
        return 2
    return 1 if counts.get('failed', 0) or counts.get('error', 0) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Frisian Draughts position suite')
    commands = parser.add_subparsers(dest='command')
    run = commands.add_parser('run', help='Run a saved suite without a GUI')
    run.add_argument('suite', type=Path)
    run.add_argument('--engine', type=Path, default=DEFAULT_ENGINE)
    run.add_argument('--protocol', choices=['json', 'hub'], default='json')
    run.add_argument('--referee', type=Path, help='Rust rules inspector, required for Hub engines')
    run.add_argument('--engine-cwd', help='Hub engine working directory')
    run.add_argument('--logs', type=Path, default=Path('position-logs'))
    run.add_argument('--depth', type=int, help='Override every case depth (1–64)')
    run.add_argument('--no-tt', action='store_true', help='Run the baseline without transposition tables')
    run.add_argument('--verbose', action='store_true', help='Print live search text as well as saving logs')
    args = parser.parse_args(argv)
    if args.command == 'run':
        if args.protocol == 'hub' and args.referee is None:
            parser.error('--referee is required with --protocol hub')
        if args.depth is not None and not 1 <= args.depth <= 64:
            parser.error('--depth must be 1–64')
        return run_suite(args)
    from .gui import launch
    launch()
    return 0

