"""Hub backend for the existing version-1 position suite, with rules validation."""
import threading
import time

from tools.position_suite.client import AnalysisOutcome
from tools.position_suite.model import validate_case
from .matches import canonical_move
from .referee import Referee
from .session import EngineProfile, HubSession, HubTimeout


class HubAnalysisSession:
    def __init__(self, engine, referee, *, timeout=300, cwd=None, parameters=None):
        self.profile = engine if isinstance(engine, EngineProfile) else EngineProfile(str(engine), cwd=cwd)
        self.referee = referee if hasattr(referee, 'inspect') else Referee(str(referee))
        self.timeout = timeout
        self.parameters = dict(parameters or {})
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self, case, on_event=lambda event: None, command='analyze'):
        session = None
        try:
            case = validate_case(case)
            if command not in ('inspect', 'analyze'):
                raise ValueError('unknown analysis command')
            if self.cancelled.is_set():
                return AnalysisOutcome('cancelled', message='Analysis cancelled')
            loaded = self.referee.inspect(case['fen'], case.get('moves', []),
                                          case.get('restrictions'), case.get('accepted_moves', []))
            on_event(loaded)
            if command == 'inspect':
                return AnalysisOutcome('inspected')
            start = self.referee.inspect(case['fen'], restrictions=case.get('restrictions'))
            state = case.get('restrictions', {})
            encoded_state = ','.join(f"{state[s]['square']}:{state[s]['count']}" if state.get(s) else '0:0'
                                     for s in ('white', 'black'))
            last = {'depth': 0, 'score': None, 'nodes': 0, 'elapsed_ms': 0, 'pv': []}
            if loaded['outcome'] != 'ongoing':
                move = None
            else:
                session = HubSession(self.profile)
                def parameters(peer):
                    supports_state = 'frisian-state-v1' in peer.identity.get('extensions', '').split() if peer.identity else False
                    if encoded_state != '0:0,0:0' and not supports_state:
                        raise ValueError('engine cannot represent imported king restrictions; use replay from a cleared state or a supporting engine')
                    params = {'variant': 'frisian', 'book': 'false', 'bb-size': 0, 'threads': 1, **self.parameters}
                    if 'tt_megabytes' in case:
                        if 'tt-size' not in peer.parameters:
                            raise ValueError('engine does not expose requested TT memory setting')
                        params['tt-size'] = case['tt_megabytes']
                    if 'tt_enabled' in case:
                        if 'tt-enabled' not in peer.parameters and not case['tt_enabled']:
                            raise ValueError('engine does not support disabling the TT')
                        if 'tt-enabled' in peer.parameters:
                            params['tt-enabled'] = str(case['tt_enabled']).lower()
                    return params
                session.start(parameters, cancel_event=self.cancelled)
                session.begin_search(start['hub'], moves=case.get('moves', []),
                                     restrictions=encoded_state if encoded_state != '0:0,0:0' else None,
                                     level=[('depth', case['depth'])], mode='analyze')
                def receive(message):
                    last.update(depth=int(message.get('depth', '0')),
                                nodes=int(message.get('nodes', '0')),
                                elapsed_ms=float(message.get('time', '0')) * 1000,
                                score=round(float(message.get('score')) * 100) if message.get('score') is not None else None,
                                pv=message.get('pv', '').split())
                    on_event({'type': 'iteration', **last})
                deadline = time.monotonic() + self.timeout
                while True:
                    if self.cancelled.is_set():
                        return AnalysisOutcome('cancelled', message='Analysis cancelled; no verdict recorded')
                    if time.monotonic() >= deadline:
                        raise HubTimeout('analysis deadline exceeded')
                    try:
                        done = session.wait_done(timeout=min(0.1, deadline - time.monotonic()), on_info=receive)
                        break
                    except HubTimeout:
                        continue
                move = canonical_move(done.get('move'), loaded['legal_moves'])
                if move is None:
                    raise ValueError('engine returned no legal move for an ongoing position')
                if last['pv']:
                    if canonical_move(last['pv'][0], loaded['legal_moves']) != move:
                        raise ValueError('final PV does not begin with the chosen move')
                    self.referee.inspect(case['fen'], [*case.get('moves', []), *last['pv']], case.get('restrictions'))
            if self.cancelled.is_set():
                return AnalysisOutcome('cancelled', message='Analysis cancelled; no verdict recorded')
            accepted = loaded['accepted_moves']
            status = 'analysis' if not accepted else 'passed' if move in accepted else 'failed'
            result = {'type': 'result', **last, 'best_move': move,
                      'passed': None if not accepted else move in accepted}
            on_event(result)
            return AnalysisOutcome(status, result)
        except Exception as exc:
            return AnalysisOutcome('cancelled' if self.cancelled.is_set() else 'error', message=str(exc))
        finally:
            if session is not None:
                session.close()
