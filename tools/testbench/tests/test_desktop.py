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


if __name__ == '__main__': unittest.main()
