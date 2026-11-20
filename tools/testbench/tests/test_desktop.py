import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from tools.testbench.profiles import entrant, preflight, save_profiles
from tools.testbench.matches import load_config


class ProfileTests(unittest.TestCase):
    def test_roundtrip_and_invalid_profiles(self):
        engine = entrant('A', 'engine folder/engine.exe', cwd='data folder', parameters='{"threads":1}')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'engines.json'; save_profiles(path, [engine])
            loaded = load_config(path, min_engines=1)
            self.assertEqual(loaded[0].profile.arguments, ('hub',))
            self.assertEqual(loaded[0].parameters, {'threads': 1})
        with self.assertRaises(ValueError): entrant('A', 'engine', arguments='{}')
        with self.assertRaises(ValueError): preflight(engine)


@unittest.skipUnless(importlib.util.find_spec('PySide6') and os.environ.get('FRISIAN_QT_TESTS'), 'optional Qt tests')
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tools.testbench.gui.window import Window
        self.window = Window(); self.addCleanup(self.window.close)

    def settle(self):
        deadline = time.monotonic() + 30
        while self.window.worker is not None and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.005)
        self.assertIsNone(self.window.worker, self.window.log.toPlainText())

    def test_defaults_and_profile_dialog(self):
        from tools.testbench.gui.profile_dialog import ProfileDialog
        window = self.window
        self.assertEqual(window.depth.value(), 12)
        self.assertEqual(window.parallel.value(), 1)
        self.assertEqual(window.rounds.value(), 1)
        self.assertEqual(window.watchdog.value(), 300)
        self.assertFalse(window.diagnostics.isEnabled())
        dialog = ProfileDialog(entrant('A', 'engine', parameters='{"threads":1}'))
        dialog.accept(); self.assertEqual(dialog.value.parameters, {'threads': 1}); dialog.close()

    def test_worker_error_recovers_and_navigation_stays_available(self):
        w = self.window
        def failed(emit): raise ValueError('deliberate failure')
        w.start(failed); self.assertTrue(w.tabs.isEnabled()); self.assertEqual(w.job_state, 'running')
        self.assertFalse(w.start(lambda emit: None))
        self.settle(); self.assertEqual(w.job_state, 'idle')
        self.assertIn('deliberate failure', w.status.text())
        values = []; w.start(lambda emit: 42, values.append); self.settle(); self.assertEqual(values, [42])

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real engine required')
    def test_cancel_restart_and_close_during_analysis(self):
        w = self.window; engine = os.environ['FRISIAN_TEST_ENGINE']
        w.engines = [entrant('A', engine)]; w.refresh_profiles(); w.referee.setText(engine)
        w.depth.setValue(64); w.analyze(); w.cancel()
        self.assertEqual(w.job_state, 'cancelling'); self.settle()
        self.assertIn('CANCELLED', w.log.toPlainText())
        w.fen.setText('W:W31:B16'); w.depth.setValue(1); w.analyze(); self.settle()
        self.assertIn('ANALYSIS', w.log.toPlainText())
        w.fen.setText('W:W31-50:B1-20'); w.depth.setValue(64); w.analyze(); w.close(); self.settle()
        self.assertTrue(w._close_pending)

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real engine required')
    def test_live_match_workflow(self):
        engine = os.environ['FRISIAN_TEST_ENGINE']; w = self.window
        w.engines = [entrant('A', engine), entrant('B', engine)]; w.refresh_profiles()
        w.referee.setText(engine); w.depth.setValue(1); w.ply_cap.setValue(2)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'match'; w.output.setText(str(output))
            w.run_matches(); self.settle()
            self.assertTrue((output / 'games.json').is_file(), w.log.toPlainText())
            self.assertEqual(len(json.loads((output / 'games.json').read_text())), 2)
        self.assertIn('adjudication-ply-limit', w.match_log.toPlainText())

    def test_case_metadata_survives_editing_and_ambiguous_drag_is_rejected(self):
        w = self.window
        w.cases = [{'name': 'Case', 'fen': 'W:W31:B16', 'depth': 1,
                    'tt_enabled': False, 'tt_megabytes': 2, 'accepted_moves': ['31-27']}]
        w.select_case(0); w.notes.setText('edited')
        self.assertFalse(w.current_case()['tt_enabled']); self.assertEqual(w.current_case()['tt_megabytes'], 2)
        w.board.set_legal_moves([(49,47,(7,),'capture'), (49,47,(8,),'capture')])
        self.assertIsNone(w.board._find_legal_move(49,47))

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real referee required')
    def test_pdn_import_export_replay_and_analysis_annotations(self):
        from tools.testbench import pdn
        from tools.testbench.referee import Referee
        w = self.window; engine = os.environ['FRISIAN_TEST_ENGINE']
        w.referee.setText(engine); w.engines = [entrant('A', engine)]; w.refresh_profiles(); w.depth.setValue(1)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'input.pdn'
            source.write_text('[Event "Game"]\n[Result "*"]\n1. 31-26 {original} $1 (1. 32-28) 16-21 *', encoding='utf-8')
            w.import_pdn(source); self.settle()
            self.assertEqual(w.games[0]['errors'], [])
            w.slider.setValue(1); self.settle()
            self.assertIn(26, w.replay_board.get_pieces()); self.assertNotIn(31, w.replay_board.get_pieces())
            output = Path(tmp) / 'output.pdn'; w.export_pdn(output, all_games=True); self.settle()
            original = pdn.loads(source.read_text())[0]; restored = pdn.loads(output.read_text())[0]
            self.assertEqual(original.tokens, restored.tokens)
            w.analyze_replay(); self.settle()
            analysis = Path(tmp) / 'analysis.pdn'; w.export_analysis_pdn(analysis); self.settle()
            text = analysis.read_text(); self.assertIn('original', text); self.assertIn('Engine analysis (A)', text)
            checked = pdn.validate(pdn.loads(text)[0], Referee(engine)); self.assertEqual(checked.errors, [])


if __name__ == '__main__': unittest.main()
