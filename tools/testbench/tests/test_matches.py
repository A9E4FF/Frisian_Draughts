import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import threading

from tools.testbench.matches import (Entrant, MatchLimits, canonical_move, load_config,
                                    play_game, save_reports, schedule, run_tournament)
from tools.testbench.protocol import parse
from tools.testbench.referee import Referee, RefereeUnavailable
from tools.testbench.session import EngineExited, EngineProfile

WHITE = Entrant('White engine', EngineProfile('unused'), {})
BLACK = Entrant('Black engine', EngineProfile('unused'), {})
INITIAL = 'W' + 'b' * 20 + 'e' * 10 + 'w' * 20


class ScriptedReferee:
    def inspect(self, fen, moves=()):
        return {'hub': INITIAL, 'turn': 'white', 'legal_moves': ['31-26'],
                'outcome': 'black-win' if moves else 'ongoing'}


class Peer:
    result = 'done move=31-26'
    def __init__(self, profile):
        self.transcript = []
        self.search_started = None
    def start(self, parameters, **kwargs):
        pass
    def send(self, command):
        pass
    def begin_search(self, *args, **kwargs):
        self.search_started = time.monotonic()
    def wait_done(self, **kwargs):
        return parse(self.result)
    def close(self):
        pass


class MatchTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real engine integration is opt-in')
    def test_shared_tournament_progress_cancel_and_reports(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']
        entrants = [Entrant(name, EngineProfile(engine), {}) for name in ['A', 'B']]
        cancel = threading.Event(); events = []
        def progress(event):
            events.append(event)
            if event['type'] == 'thinking': cancel.set()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'reports'
            games = run_tournament(entrants, Referee(engine), MatchLimits(depth=12), cancel=cancel, on_event=progress, output=output)
            self.assertTrue(all(g['termination'] == 'user-cancelled' for g in games))
            self.assertEqual(len(json.loads((output / 'games.json').read_text())), 2)
        self.assertTrue(any(e['type'] == 'thinking' for e in events))
        self.assertEqual(sum(e['type'] == 'game-finished' for e in events), 2)
    def test_paired_schedule_and_master(self):
        third = Entrant('Other', EngineProfile('unused'), {})
        self.assertEqual(schedule([WHITE, BLACK], 2), [(0, 1), (1, 0), (0, 1), (1, 0)])
        self.assertEqual(len(schedule([WHITE, BLACK, third], 1)), 6)
        self.assertEqual(len(schedule([WHITE, BLACK, third], 1, WHITE.name)), 4)

    def test_capture_identifiers_and_ambiguity(self):
        legal = ['49x47x7x11x19x30x42', '49x47x8x12']
        self.assertEqual(canonical_move('49x47x42x30x19x11x7', legal), legal[0])
        self.assertIsNone(canonical_move('49x47', legal))
        self.assertEqual(canonical_move('49x47', legal[:1]), legal[0])
        for invalid in [None, 'illegal', '49x47x7', '31-27']:
            self.assertIsNone(canonical_move(invalid, legal))

    def test_terminal_result_requires_referee(self):
        result = play_game(WHITE, BLACK, ScriptedReferee(), MatchLimits(), session_factory=Peer)
        self.assertEqual((result['result'], result['termination']), ('0-1', 'terminal-loss'))
        self.assertEqual(result['moves'], ['31-26'])

    def test_missing_and_illegal_moves_are_distinct(self):
        for message, reason in [('done', 'missing-move'), ('done move=31-27', 'illegal-move')]:
            class BadPeer(Peer):
                result = message
            result = play_game(WHITE, BLACK, ScriptedReferee(), MatchLimits(), session_factory=BadPeer)
            self.assertEqual(result['termination'], reason)
            self.assertEqual(result['moves'], [])

    def test_crash_is_not_terminal_loss(self):
        class Crashed(Peer):
            def wait_done(self, **kwargs):
                raise EngineExited('gone')
        result = play_game(WHITE, BLACK, ScriptedReferee(), MatchLimits(), session_factory=Crashed)
        self.assertEqual(result['termination'], 'engine-crash')

    def test_clock_overrun_is_enforced(self):
        class SlowPeer(Peer):
            def begin_search(self, *args, **kwargs):
                self.search_started = time.monotonic() - 1
        limits = MatchLimits(depth=None, clock=0.01, clock_margin=0)
        result = play_game(WHITE, BLACK, ScriptedReferee(), limits, session_factory=SlowPeer)
        self.assertEqual(result['termination'], 'timeout')

    def test_referee_failure_does_not_blame_an_engine(self):
        class Failed:
            def inspect(self, *_):
                raise RefereeUnavailable('gone')
        result = play_game(WHITE, BLACK, Failed(), MatchLimits(), session_factory=Peer)
        self.assertEqual((result['result'], result['termination']), ('*', 'referee-error'))

    def test_ply_cap_is_labeled_adjudication(self):
        class Endless(ScriptedReferee):
            def inspect(self, fen, moves=()):
                return {**super().inspect(fen), 'outcome': 'ongoing'}
        result = play_game(WHITE, BLACK, Endless(), MatchLimits(max_plies=1), session_factory=Peer)
        self.assertEqual(result['termination'], 'adjudication-ply-limit')

    def test_configuration_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'engines.json'
            path.write_text(json.dumps({'version': 1, 'engines': [
                {'name': 'A', 'executable': 'Engine Folder/a.exe'},
                {'name': 'B', 'executable': 'b.exe', 'arguments': []}]}), encoding='utf-8')
            entrants = load_config(path)
            self.assertIn('Engine Folder', entrants[0].profile.executable)
            self.assertEqual(entrants[1].profile.arguments, ())
            game = play_game(WHITE, BLACK, ScriptedReferee(), MatchLimits(), session_factory=Peer)
            output = Path(tmp) / 'reports'
            save_reports(output, [game], {'schema': 1})
            self.assertEqual(json.loads((output / 'games.json').read_text()) [0]['moves'], ['31-26'])
            self.assertIn('terminal-loss', (output / 'results.csv').read_text())
            self.assertIn('[Result "0-1"]', (output / 'games.pdn').read_text())
            with self.assertRaises(FileExistsError):
                save_reports(output, [game], {})

    def test_invalid_limits(self):
        for options in [{'depth': 0}, {'depth': None}, {'clock': 1}, {'max_plies': 0},
                        {'increment': float('nan')}, {'response_timeout': 0}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                MatchLimits(**options)

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real engine integration is opt-in')
    def test_real_engine_game_replays_through_referee(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']
        referee = Referee(engine)
        a = Entrant('Rust A', EngineProfile(engine), {})
        b = Entrant('Rust B', EngineProfile(engine), {})
        game = play_game(a, b, referee, MatchLimits(depth=1, max_plies=6))
        self.assertEqual(game['termination'], 'adjudication-ply-limit', game)
        referee.inspect(game['fen'], game['moves'])


if __name__ == '__main__':
    unittest.main()
