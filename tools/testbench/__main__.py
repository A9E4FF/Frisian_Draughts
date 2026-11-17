"""Small protocol probe; no match adjudication or playing-strength claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from .session import EngineProfile, HubSession


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'match':
        from .matches import main as matches_main
        return matches_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', help='Hub executable path')
    parser.add_argument('--cwd', help='Engine working directory (Scan data files)')
    parser.add_argument('--arg', action='append', help='Launch argument; defaults to hub')
    parser.add_argument('--output', type=Path, required=True, help='JSON transcript destination')
    parser.add_argument('--depth', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if not 1 <= args.depth <= 64 or args.timeout <= 0:
        parser.error('depth must be 1–64 and timeout must be positive')
    executable = Path(os.path.abspath(args.engine))
    profile = EngineProfile(str(executable), tuple(args.arg or ['hub']), args.cwd)
    session = HubSession(profile)
    result = {'protocol': 'Hub v2', 'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'arguments': list(profile.arguments), 'depth': args.depth, 'passed': False}
    try:
        # These parameters are understood by Scan and the planned Rust adapter.
        # Unknown parameters must be ignored under the Hub forward-compatibility rule.
        session.start({'variant': 'frisian', 'book': 'false', 'bb-size': 0, 'threads': 1},
                      timeout=args.timeout)
        session.begin_search('W' + 'b' * 20 + 'e' * 10 + 'w' * 20,
                             level=[('depth', args.depth)])
        done = session.wait_done(timeout=args.timeout)
        if not done.get('move'):
            raise ValueError('starting-position search returned no move')
        session.ping(timeout=args.timeout)
        result['passed'] = True
        result['move'] = done.get('move')
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        session.close()
        result['events'] = session.transcript
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Protocol probe passed' if result['passed'] else result['error'])
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
