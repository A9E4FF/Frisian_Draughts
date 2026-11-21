import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from tools.testbench import pdn, start_positions as starts
from tools.testbench.matches import Entrant, MatchLimits, run_tournament
from tools.testbench.referee import Referee
from tools.testbench.session import EngineProfile


@unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real referee required')
class PositionScheduleTests(unittest.TestCase):
    def test_each_start_both_colors_and_history_reports(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']; referee = Referee(engine)
        entrants = [Entrant(name, EngineProfile(engine), {}) for name in ['A', 'B']]
        positions = [starts.position('Opening', moves=['31-26']),
                     starts.position('Disabled', enabled=False), starts.position('Black first', 'B:W31-50:B1-20')]
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)/'reports'
            events = []
            games = run_tournament(entrants, referee, MatchLimits(depth=1, max_plies=2),
                positions=positions, rounds=2, parallel=2, on_event=events.append, output=destination)
            self.assertEqual(len(games), 8)
            self.assertTrue(all(g['termination'] == 'adjudication-ply-limit' for g in games), games)
            self.assertEqual([g['white'] for g in games[:4]], ['A', 'B', 'A', 'B'])
            self.assertEqual([g['position_id'] for g in games[:4]], [positions[0]['id']]*4)
            for game in games:
                referee.inspect(game['fen'], game['moves'])
                self.assertEqual(len(game['plies']), 2)
                if game['position_name'] == 'Opening': self.assertEqual(game['moves'][0], '31-26')
            documents = pdn.loads((destination/'games.pdn').read_text())
            for document in documents:
                pdn.validate(document, referee); self.assertFalse(document.errors, document.errors)
            self.assertEqual(documents[0].tag('StartPosition'), 'Opening')
            self.assertEqual(json.loads((destination/'manifest.json').read_text())['positions'], [positions[0], positions[2]])
            self.assertIn('Opening', (destination/'results.csv').read_text())
            self.assertEqual(sum(e['type'] == 'game-finished' for e in events), 8)

    def test_invalid_or_empty_selection_launches_no_games(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']; entrants = [Entrant(n, EngineProfile(engine), {}) for n in ['A', 'B']]
        for positions in [[], [starts.position(fen='W:W31:B1:H0')]]:
            events = []
            with self.assertRaises(ValueError): run_tournament(entrants, Referee(engine), MatchLimits(), positions=positions, on_event=events.append)
            self.assertEqual(events, [])


@unittest.skipUnless(importlib.util.find_spec('PySide6') and os.environ.get('FRISIAN_QT_TESTS') and os.environ.get('FRISIAN_TEST_ENGINE'), 'Qt and real referee required')
class MatchPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_collection_live_match_cancel_restart(self):
        from tools.testbench.gui.matches_panel import MatchesPanel
        engine = os.environ['FRISIAN_TEST_ENGINE']
        panel = MatchesPanel([Entrant(n, EngineProfile(engine), {}) for n in ['A', 'B']], engine)
        self.addCleanup(panel.close)
        panel.starts.import_text('FEN: B:W31-50:B1-20')
        panel.preview_start(panel.starts.positions[1]); self.assertIsNone(panel.last_error)
        self.assertIn('2 enabled', panel.total.text())
        with tempfile.TemporaryDirectory() as tmp:
            panel.depth.setValue(1); panel.ply_cap.setValue(2); panel.output.setText(str(Path(tmp)/'first'))
            panel.run_matches(); self.assertIsNotNone(panel.worker)
            deadline = time.monotonic() + 30
            while panel.worker is not None and time.monotonic() < deadline:
                self.app.processEvents(); time.sleep(.005)
            self.assertIsNone(panel.worker); self.assertIsNone(panel.last_error)
            self.assertEqual(len(panel.games), 4)
            panel.depth.setValue(30); panel.output.setText(str(Path(tmp)/'cancelled')); panel.run_matches(); panel.cancel()
            deadline = time.monotonic() + 30
            while panel.worker is not None and time.monotonic() < deadline:
                self.app.processEvents(); time.sleep(.005)
            self.assertIsNone(panel.worker); self.assertTrue(panel.settings.isEnabled())
            self.assertTrue(all(g['termination'] == 'user-cancelled' for g in panel.games))


if __name__ == '__main__': unittest.main()
