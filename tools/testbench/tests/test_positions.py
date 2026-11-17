import os
from pathlib import Path
import sys
import unittest

from tools.position_suite.client import AnalysisSession
from tools.position_suite.model import load_suite
from tools.testbench.positions import HubAnalysisSession
from tools.testbench.session import EngineProfile

FAKE = str(Path(__file__).with_name('fake_engine.py'))
CASE = {'name': 'Trap', 'fen': 'W:W31:B16', 'depth': 1, 'accepted_moves': ['31-27']}


class Inspector:
    def inspect(self, fen, moves=(), restrictions=None, accepted_moves=()):
        return {'type': 'loaded', 'hub': 'W' + 'b' * 20 + 'e' * 10 + 'w' * 20,
                'outcome': 'ongoing', 'legal_moves': ['31-26'], 'accepted_moves': list(accepted_moves),
                'fen': fen, 'turn': 'white'}


class HubPositionTests(unittest.TestCase):
    def test_cancel_before_launch_and_inspection_only(self):
        session = HubAnalysisSession('missing', Inspector())
        session.cancel()
        self.assertEqual(session.run(CASE).status, 'cancelled')
        session = HubAnalysisSession('missing', Inspector())
        self.assertEqual(session.run(CASE, command='inspect').status, 'inspected')

    def test_standard_hub_cannot_silently_drop_restrictions(self):
        profile = EngineProfile(sys.executable, (FAKE, 'normal'))
        case = {**CASE, 'restrictions': {'white': {'square': 28, 'count': 3}}}
        result = HubAnalysisSession(profile, Inspector()).run(case)
        self.assertEqual(result.status, 'error')
        self.assertIn('king restrictions', result.message)

    def test_requested_unsupported_tt_setting_is_explicit(self):
        profile = EngineProfile(sys.executable, (FAKE, 'normal'))
        result = HubAnalysisSession(profile, Inspector()).run({**CASE, 'tt_enabled': False})
        self.assertEqual(result.status, 'error')
        self.assertIn('disabling', result.message)

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real engine integration is opt-in')
    def test_original_and_expanded_cases_work_with_hub(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']
        for suite in ['tools/position_suite/sample-suite.json', 'tools/testbench/examples/regression-suite.json']:
            for case in load_suite(suite):
                with self.subTest(case=case['name']):
                    native = AnalysisSession(engine).run(case)
                    hub = HubAnalysisSession(engine, engine).run(case)
                    self.assertEqual(hub.status, native.status, hub.message)
                    self.assertIn(hub.status, ('analysis', 'passed'))
                    self.assertEqual(hub.result['best_move'], native.result['best_move'])


if __name__ == '__main__':
    unittest.main()
