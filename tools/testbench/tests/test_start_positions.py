import tempfile
import unittest
from pathlib import Path
from tools.testbench import start_positions as starts


class StartPositionTests(unittest.TestCase):
    def test_legacy_text_and_metadata_preserved(self):
        items = starts.parse_text('# comment\nFEN: W:W31-50:B1-20\n; another\nB:WK28:B1:H0:F6:+0+0\nstart')
        self.assertEqual(len(items), 3)
        self.assertTrue(items[1]['fen'].endswith(':H0:F6:+0+0'))
        with self.assertRaisesRegex(ValueError, 'retained'): starts.validate(items[1], None)
        with self.assertRaisesRegex(ValueError, 'Line 2'): starts.parse_text('start\ninvalid')

    def test_collection_roundtrip_order_identity_history(self):
        items = [starts.position('First', moves=['31-26'], restrictions={'white': {'square': 28, 'count': 2}}, notes='retain'), starts.position('Second', enabled=False)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'starts.json'; starts.save(path, items)
            self.assertEqual(starts.load(path), items)
            with self.assertRaisesRegex(ValueError, 'Duplicate'): starts.save(path, [items[0], items[0]])


if __name__ == '__main__': unittest.main()
