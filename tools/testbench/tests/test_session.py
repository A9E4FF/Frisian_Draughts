from pathlib import Path
import sys
import unittest

from tools.testbench.protocol import ProtocolError
from tools.testbench.session import EngineExited, EngineProfile, HubError, HubSession, HubTimeout
from tools.testbench.session import HubCancelled
import threading

FAKE = str(Path(__file__).with_name('fake_engine.py'))
INITIAL = 'W' + 'b' * 20 + 'e' * 10 + 'w' * 20


class SessionTests(unittest.TestCase):
    def test_handshake_can_be_cancelled_and_process_is_reaped(self):
        cancel = threading.Event()
        session = HubSession(EngineProfile(sys.executable, (FAKE, 'misleading-handshake')))
        timer = threading.Timer(0.05, cancel.set); timer.start()
        try:
            with self.assertRaises(HubCancelled):
                session.start(timeout=10, cancel_event=cancel)
            self.assertEqual(session.state, 'closed')
            self.assertIsNotNone(session._process.poll())
        finally:
            timer.join(); session.close()
    def session(self, scenario='normal', **kwargs):
        session = HubSession(EngineProfile(sys.executable, (FAKE, scenario)), **kwargs)
        self.addCleanup(session.close)
        session.start({'variant': 'frisian'}, timeout=2)
        return session

    def test_handshake_search_history_and_streamed_info(self):
        session = self.session()
        self.assertEqual(session.identity.get('name'), 'Fake Hub Engine')
        self.assertIn('variant', session.parameters)
        session.begin_search(INITIAL, moves=['31-26', '16-21'])
        reports = []
        result = session.wait_done(on_info=reports.append)
        self.assertEqual(result.get('move'), '31-26')
        self.assertEqual(reports[0].get('pv'), '31-26 16-21')
        self.assertEqual(session.state, 'ready')
        self.assertTrue(any('moves="31-26 16-21"' in e['line'] for e in session.transcript))
        session.begin_search(INITIAL)
        self.assertEqual(session.wait_done().get('move'), '31-26')

    def test_fragmented_crlf(self):
        session = self.session('fragmented')
        session.begin_search(INITIAL)
        self.assertEqual(session.wait_done().get('ponder'), '16-21')

    def test_stderr_flood_does_not_block_handshake(self):
        session = self.session('stderr', log_lines=20)
        self.assertEqual(session.ping().command, 'pong')
        self.assertLessEqual(len(session.transcript), 20)

    def test_stop_and_ping_during_search(self):
        session = self.session('stop')
        session.begin_search(INITIAL, level=[('infinite', None)], mode='analyze')
        self.assertEqual(session.ping().command, 'pong')
        self.assertEqual(session.state, 'searching')
        self.assertEqual(session.stop().get('move'), '31-26')
        session.begin_search(INITIAL)
        self.assertEqual(session.stop().get('move'), '31-26')

    def test_result_before_pong_is_preserved(self):
        session = self.session()
        session.begin_search(INITIAL)
        session.ping()
        self.assertEqual(session.wait_done().get('move'), '31-26')

    def test_timeout_is_not_a_no_move_result(self):
        session = self.session('missing-done')
        session.begin_search(INITIAL)
        with self.assertRaises(HubTimeout):
            session.wait_done(timeout=0.05)
        self.assertEqual(session.state, 'searching')
        with self.assertRaises(HubTimeout):
            session.stop(timeout=0.05)

    def test_timeout_can_be_recovered_with_stop(self):
        session = self.session('stop')
        session.begin_search(INITIAL)
        with self.assertRaises(HubTimeout):
            session.wait_done(timeout=0.05)
        self.assertEqual(session.stop().get('move'), '31-26')

    def test_stale_result_cannot_be_used_for_next_search(self):
        session = self.session('duplicate')
        session.begin_search(INITIAL)
        session.wait_done()
        with self.assertRaises(HubError):
            session.begin_search(INITIAL)

    def test_crash_is_not_terminal_loss(self):
        session = self.session('crash')
        session.begin_search(INITIAL)
        with self.assertRaises(EngineExited):
            session.wait_done()

    def test_terminal_result_has_no_adjudication(self):
        session = self.session('terminal')
        session.begin_search(INITIAL)
        result = session.wait_done()
        self.assertIsNone(result.get('move'))  # Later referee determines legality/outcome.

    def test_errors_and_bad_output(self):
        for scenario, expected in [('error', HubError), ('malformed', ProtocolError)]:
            with self.subTest(scenario=scenario):
                session = self.session(scenario)
                session.begin_search(INITIAL)
                with self.assertRaises(expected):
                    session.wait_done()

    def test_handshake_matches_commands_not_substrings(self):
        session = HubSession(EngineProfile(sys.executable, (FAKE, 'misleading-handshake')))
        self.addCleanup(session.close)
        with self.assertRaises(HubTimeout):
            session.start(timeout=0.1)
        self.assertEqual(session.state, 'closed')

    def test_oversized_output_and_launch_failure_clean_up(self):
        session = HubSession(EngineProfile(sys.executable, (FAKE, 'oversized')), max_line=256)
        self.addCleanup(session.close)
        with self.assertRaises(ProtocolError):
            session.start()
        self.assertEqual(session.state, 'closed')
        missing = HubSession(EngineProfile(str(Path(FAKE).with_name('missing-engine.exe'))))
        with self.assertRaises(OSError):
            missing.start()
        self.assertEqual(missing.state, 'closed')

    def test_state_guards_and_atomic_validation(self):
        session = self.session('stop')
        before = len(session.transcript)
        with self.assertRaises(ProtocolError):
            session.begin_search(INITIAL, moves=['bad\nquit'])
        self.assertEqual(len(session.transcript), before)
        session.begin_search(INITIAL)
        with self.assertRaises(HubError):
            session.begin_search(INITIAL)
        session.stop()
        with self.assertRaises(HubError):
            session.wait_done()
        session.close()
        session.close()
        self.assertIsNotNone(session._process.poll())

    def test_uncooperative_engine_is_reaped(self):
        session = self.session('ignore-quit')
        session.close()
        self.assertIsNotNone(session._process.poll())


if __name__ == '__main__':
    unittest.main()
