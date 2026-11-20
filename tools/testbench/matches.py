"""Paired headless matches with a separate rules referee and explicit outcomes."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import time
import threading

from .protocol import ProtocolError
from .referee import InvalidState, Referee, RefereeUnavailable
from .session import EngineExited, EngineProfile, HubError, HubSession, HubTimeout, HubCancelled
from . import pdn

START = 'W:W31-50:B1-20'


@dataclass(frozen=True)
class Entrant:
    name: str
    profile: EngineProfile
    parameters: dict
    revision: str | None = None
    capabilities: tuple[str, ...] = ()


def load_config(path, *, min_engines=2):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('expected version-1 engine configuration')
    engines = []
    for engine in data.get('engines', []):
        def absolute(value):
            return os.path.abspath(path.parent / os.path.expandvars(value))
        name = engine['name']
        if not isinstance(name, str) or not name or any(e.name == name for e in engines):
            raise ValueError('engine names must be nonempty and unique')
        args = engine.get('arguments', ['hub'])
        params = engine.get('parameters', {})
        if not isinstance(args, list) or not all(isinstance(s, str) for s in args) or not isinstance(params, dict):
            raise ValueError('invalid arguments/parameters')
        engines.append(Entrant(name, EngineProfile(absolute(engine['executable']), tuple(args),
                       absolute(engine['cwd']) if engine.get('cwd') else None), params, engine.get('revision'), tuple(engine.get('capabilities', []))))
    if len(engines) < min_engines:
        raise ValueError(f'at least {min_engines} engine profiles are required')
    return engines


def schedule(engines, rounds=1, master=None):
    return [(a, b) for _ in range(rounds) for i, j in pairs_for(engines, master)
            for a, b in [(i, j), (j, i)]]


def pairs_for(engines, master):
    return [(i, j) for i, j in itertools.combinations(range(len(engines)), 2)
            if master is None or engines[i].name == master or engines[j].name == master]


@dataclass(frozen=True)
class MatchLimits:
    depth: int | None = 4
    move_time: float | None = None
    clock: float | None = None
    increment: float = 0.0
    max_plies: int = 200
    response_timeout: float = 60.0
    clock_margin: float = 0.05

    def __post_init__(self):
        if sum(v is not None for v in (self.depth, self.move_time, self.clock)) != 1:
            raise ValueError('choose exactly one depth, move-time or clock control')
        if self.depth is not None and (type(self.depth) is not int or not 1 <= self.depth <= 64):
            raise ValueError('depth must be 1–64')
        if type(self.max_plies) is not int or self.max_plies < 1:
            raise ValueError('max plies must be positive')
        for value in (self.move_time, self.clock, self.increment, self.response_timeout, self.clock_margin):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError('time values must be finite and nonnegative')
        if self.response_timeout == 0:
            raise ValueError('response timeout must be positive')


def canonical_move(text, legal_moves):
    """Normalize captured-square order; endpoint shorthand must be unambiguous."""
    if text in legal_moves:
        return text
    def parts(value):
        items = value.split('x')
        return tuple(int(s) for s in items)
    try:
        wanted = parts(text)
        if len(wanted) < 2:
            return None
        candidates = [mv for mv in legal_moves if 'x' in mv and parts(mv)[:2] == wanted[:2]
                      and (len(wanted) == 2 or sorted(parts(mv)[2:]) == sorted(wanted[2:]))]
        return candidates[0] if len(candidates) == 1 else None
    except (ValueError, TypeError, AttributeError):
        return None


def play_game(white, black, referee, limits, *, fen=START, session_factory=HubSession, cancel=None, on_event=lambda event: None):
    entrants = [white, black]
    sessions = []
    moves = []
    clocks = [limits.clock, limits.clock]
    result = {'white': white.name, 'black': black.name, 'fen': fen, 'moves': moves,
              'result': '*', 'termination': 'unfinished', 'plies': [], 'transcripts': {}}
    side = None
    if cancel is not None and cancel.is_set():
        result['termination'] = 'user-cancelled'
        return result
    try:
        state = referee.inspect(fen)
        initial = state['hub']
        on_event({'type': 'position', 'state': state, 'moves': []})
        for side, entrant in enumerate(entrants):
            session = session_factory(entrant.profile)
            sessions.append(session)
            session.start({'variant': 'frisian', 'book': 'false', 'bb-size': 0, 'threads': 1,
                           **entrant.parameters}, cancel_event=cancel)
            session.send('new-game')
        for ply in range(limits.max_plies + 1):
            if cancel is not None and cancel.is_set():
                result.update(result='*', termination='user-cancelled')
                break
            outcome = state['outcome']
            if outcome != 'ongoing':
                result['result'] = {'draw': '1/2-1/2', 'white-win': '1-0', 'black-win': '0-1'}[outcome]
                result['termination'] = 'rules-draw' if outcome == 'draw' else 'terminal-loss'
                break
            if ply == limits.max_plies:
                result.update(result='1/2-1/2', termination='adjudication-ply-limit')
                break
            side = 0 if state['turn'] == 'white' else 1
            session = sessions[side]
            if limits.clock is not None:
                clocks[side] += limits.increment  # Hub increment is added before the move.
                budget = clocks[side]
                level = [('time', max(0, budget - limits.increment)), ('inc', limits.increment)]
            elif limits.move_time is not None:
                budget = limits.move_time
                level = [('move-time', budget)]
            else:
                budget = None
                level = [('depth', limits.depth)]
            session.begin_search(initial, moves=moves, level=level)
            on_event({'type': 'thinking', 'engine': entrants[side].name, 'ply': ply})
            started = session.search_started
            timeout = limits.response_timeout if budget is None else max(0.001, budget + limits.clock_margin)
            while True:
                remaining = started + timeout - time.monotonic()
                if remaining <= 0:
                    raise HubTimeout('response/clock deadline exceeded')
                if cancel is not None and cancel.is_set():
                    result.update(result='*', termination='user-cancelled')
                    return result
                try:
                    done = session.wait_done(timeout=min(0.1, remaining),
                        on_info=lambda m: on_event({'type': 'search-info', 'engine': entrants[side].name, 'fields': dict(m.pairs)}))
                    break
                except HubTimeout:
                    continue
            elapsed = time.monotonic() - started
            if budget is not None and elapsed > budget + limits.clock_margin:
                raise HubTimeout('clock exceeded')
            if limits.clock is not None:
                clocks[side] -= elapsed
            move = canonical_move(done.get('move'), state['legal_moves'])
            if move is None:
                result['termination'] = 'missing-move' if not done.get('move') else 'illegal-move'
                result['result'] = '0-1' if side == 0 else '1-0'
                break
            moves.append(move)
            result['plies'].append({'move': move, 'seconds': elapsed,
                                    'remaining_clock': clocks[side]})
            state = referee.inspect(fen, moves)
            on_event({'type': 'position', 'state': state, 'moves': list(moves)})
    except HubCancelled:
        result.update(result='*', termination='user-cancelled')
    except (InvalidState, RefereeUnavailable) as exc:
        result.update(result='*', termination='referee-error', error=str(exc))
    except (HubTimeout, EngineExited, HubError, ProtocolError, OSError) as exc:
        reason = ('timeout' if isinstance(exc, HubTimeout) else 'engine-crash' if isinstance(exc, EngineExited)
                  else 'protocol-error' if isinstance(exc, (ProtocolError, HubError)) else 'launch-error')
        result.update(result=('0-1' if side == 0 else '1-0') if side is not None else '*',
                      termination=reason, error=str(exc))
    finally:
        for entrant, session in zip(entrants, sessions):
            session.close()
            result['transcripts'][entrant.name] = session.transcript
    return result


def save_reports(directory, games, manifest):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (directory / 'games.json').write_text(json.dumps(games, indent=2) + '\n', encoding='utf-8')
    with (directory / 'results.csv').open('w', newline='', encoding='utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=['white', 'black', 'result', 'termination'])
        writer.writeheader()
        writer.writerows({k: game[k] for k in writer.fieldnames} for game in games)
    (directory / 'games.pdn').write_text(pdn.dumps([pdn.from_record(g) for g in games]), encoding='utf-8')



def manifest_for(engines, referee, limits, rounds=1):
    return {'schema': 1, 'limits': vars(limits), 'rounds': rounds,
        'referee_sha256': hashlib.sha256(Path(referee.executable).read_bytes()).hexdigest(),
        'engines': [{'name': e.name, 'executable': e.profile.executable, 'arguments': e.profile.arguments,
                     'cwd': e.profile.cwd, 'parameters': e.parameters, 'revision': e.revision,
                     'sha256': hashlib.sha256(Path(e.profile.executable).read_bytes()).hexdigest()} for e in engines]}


def run_tournament(engines, referee, limits, *, rounds=1, parallel=1, master=None,
                   cancel=None, on_event=lambda event: None, output=None):
    if rounds < 1 or parallel < 1 or len(engines) < 2:
        raise ValueError('positive rounds/parallel and two engines required')
    if master is not None and master not in [e.name for e in engines]:
        raise ValueError('unknown master engine')
    if output is not None and Path(output).exists():
        raise ValueError('choose a new report directory')
    manifest = manifest_for(engines, referee, limits, rounds)
    cancel = cancel or threading.Event()
    pairs = schedule(engines, rounds, master)
    def run(item):
        number, (a, b) = item
        def progress(event):
            on_event({**event, 'game': number, 'total': len(pairs)})
        progress({'type': 'game-started', 'white': engines[a].name, 'black': engines[b].name})
        game = play_game(engines[a], engines[b], referee, limits, cancel=cancel, on_event=progress)
        progress({'type': 'game-finished', 'record': game})
        return game
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(run, item) for item in enumerate(pairs, 1)]
        try:
            games = [f.result() for f in futures]
        except KeyboardInterrupt:
            cancel.set()
            games = [f.result() for f in futures]
    if output is not None:
        save_reports(output, games, manifest)
    return games


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--referee', required=True)
    parser.add_argument('--output', type=Path, required=True)
    control = parser.add_mutually_exclusive_group()
    control.add_argument('--depth', type=int)
    control.add_argument('--move-time', type=float)
    control.add_argument('--clock', type=float)
    parser.add_argument('--increment', type=float, default=0)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--parallel', type=int, default=1)
    parser.add_argument('--master')
    parser.add_argument('--max-plies', type=int, default=200)
    parser.add_argument('--response-timeout', type=float, default=60)
    args = parser.parse_args(argv)
    try:
        engines = load_config(args.config)
        if args.rounds < 1 or args.parallel < 1 or (args.master and args.master not in [e.name for e in engines]):
            raise ValueError('invalid rounds, parallel count or master')
        if args.output.exists():
            raise ValueError('choose a new output directory; existing reports are never overwritten')
        limits = MatchLimits(depth=args.depth if args.depth is not None else (4 if args.move_time is None and args.clock is None else None),
                             move_time=args.move_time, clock=args.clock, increment=args.increment,
                             max_plies=args.max_plies, response_timeout=args.response_timeout)
        referee_path = os.path.abspath(args.referee)
        referee = Referee(referee_path)
        games = run_tournament(engines, referee, limits, rounds=args.rounds, parallel=args.parallel, master=args.master, output=args.output)
        for game in games:
            print(f"{game['white']} – {game['black']}: {game['result']} ({game['termination']})")
        return 1 if any(g['termination'] not in ('terminal-loss', 'rules-draw', 'adjudication-ply-limit') for g in games) else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Configuration/report error: {exc}')
        return 2
