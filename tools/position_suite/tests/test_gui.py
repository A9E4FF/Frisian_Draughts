"""Optional real-widget smoke test; headless CI skips it without a display."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY'), 'A display is required for the Tk widget test')
class GuiTests(unittest.TestCase):
    def test_preview_analyze_suite_export_cancel_and_recover(self):
        import tkinter as tk
        from tools.position_suite.gui import PositionApp, START_FEN
        engine = Path(os.environ.get('FRISIAN_TEST_ENGINE', 'target/debug/frisian-draughts')).resolve()
        if not engine.is_file():
            self.skipTest('Build the Rust engine before the widget test')
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        app = PositionApp(root)
        self.addCleanup(app.close)
        root.update()
        app.engine.set(str(engine))
        app.name.set('Edge trap alternatives')
        app.fen.set('W:W31:B16')
        app.depth.set('2')
        app.accepted.set('31-27, 31-26')

        def wait_done():
            deadline = time.monotonic() + 8
            while app.session and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            root.update()
            self.assertIsNone(app.session, app.status.get())

        app.start('inspect')
        wait_done()
        self.assertEqual(app.status.get(), 'INSPECTED')
        self.assertEqual(len(app.loaded['pieces']), 2)
        app.start('analyze')
        wait_done()
        self.assertEqual(app.status.get(), 'PASSED')
        self.assertIn('ITERATION depth=2', app.log.get('1.0', 'end'))
        with tempfile.TemporaryDirectory() as tmp:
            suite = Path(tmp) / 'suite.json'
            log = Path(tmp) / 'analysis.txt'
            app.store_case()
            self.assertEqual(len(app.cases), 1)
            with patch('tools.position_suite.gui.filedialog.asksaveasfilename', return_value=str(suite)):
                app.save()
            self.assertEqual(json.loads(suite.read_text())['positions'][0]['accepted_moves'], ['31-27', '31-26'])
            with patch('tools.position_suite.gui.filedialog.asksaveasfilename', return_value=str(log)):
                app.export()
            self.assertIn('STATUS: PASSED', log.read_text())
            app.new_case()
            with patch('tools.position_suite.gui.filedialog.askopenfilename', return_value=str(suite)):
                app.load()
            app.listbox.selection_set(0)
            app.select_case()
            self.assertEqual(app.fen.get(), 'W:W31:B16')
            self.assertEqual(app.tt_megabytes.get(), '16')
        app.fen.set(START_FEN)
        app.accepted.set('')
        app.depth.set('64')
        app.start('analyze')
        deadline = time.monotonic() + 4
        while not app.loaded and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        self.assertIsNotNone(app.loaded)
        app.cancel()
        wait_done()
        self.assertTrue(app.status.get().startswith('CANCELLED'))
        app.fen.set('W:W31:B16')
        app.depth.set('2')
        app.accepted.set('31-27, 31-26')
        app.start('analyze')
        wait_done()
        self.assertEqual(app.status.get(), 'PASSED')
