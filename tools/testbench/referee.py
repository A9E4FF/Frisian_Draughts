"""Rules-only adapter to the Rust JSON inspector; never uses search scores."""
import json
import subprocess


class RefereeUnavailable(RuntimeError):
    pass


class InvalidState(ValueError):
    pass


class Referee:
    def __init__(self, executable, timeout=15):
        self.executable = executable
        self.timeout = timeout

    def inspect(self, fen, moves=(), restrictions=None, accepted_moves=()):
        request = {'command': 'inspect', 'fen': fen, 'moves': list(moves),
                   'accepted_moves': list(accepted_moves), 'restrictions': restrictions or {}}
        try:
            result = subprocess.run([self.executable, '--analysis-json'],
                                    input=json.dumps(request) + '\n', text=True,
                                    encoding='utf-8', capture_output=True, timeout=self.timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RefereeUnavailable(str(exc)) from exc
        if result.returncode:
            raise RefereeUnavailable(f'referee exit {result.returncode}: {result.stderr[-1000:]}')
        try:
            events = [json.loads(line) for line in result.stdout.splitlines()]
            errors = [e['message'] for e in events if e.get('type') == 'error']
            if errors:
                raise InvalidState('; '.join(errors))
            loaded = next(e for e in events if e.get('type') == 'loaded')
            if loaded['outcome'] not in ('ongoing', 'draw', 'white-win', 'black-win'):
                raise ValueError('unknown outcome')
            if len(loaded['hub']) != 51 or not isinstance(loaded['legal_moves'], list):
                raise ValueError('invalid board/legality response')
            return loaded
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            if isinstance(exc, InvalidState):
                raise
            raise RefereeUnavailable('invalid referee response; use the stage-4 Rust build') from exc
