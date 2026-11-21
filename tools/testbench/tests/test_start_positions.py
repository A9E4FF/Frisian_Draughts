import tempfile
import unittest
from pathlib import Path
from tools.testbench import start_positions as starts


class StartPositionTests(unittest.TestCase):
    def test_known_openings_prepare_without_mutating_input_or_history(self):
        original = starts.position('Saved', 'B:W31:B1:H0:F6:+0+0', moves=['1-6'], restrictions={'white': None})
        prepared = starts.prepare(original)
        self.assertEqual(prepared['fen'], 'B:W31:B1')
        self.assertEqual(prepared['original_fen'], original['fen'])
        self.assertEqual(prepared['legacy_fields'], ['H0', 'F6', '+0+0'])
        self.assertEqual(prepared['moves'], original['moves'])
        self.assertEqual(prepared['restrictions'], original['restrictions'])
        self.assertEqual(prepared['id'], original['id'])
        self.assertTrue(original['fen'].endswith('+0+0'))
        for suffix in ['H1:F6:+0+0', 'H0:F6:+1+0', 'H0:F0:+0+0', 'H0:F6:+0+0:unknown']:
            with self.assertRaises(ValueError): starts.prepare(starts.position(fen='B:W31:B1:'+suffix))
        with self.assertRaises(ValueError): starts.prepare(starts.position(fen='B:WK31:B1:H0:F6:+0+0'))

    def test_original_saved_list_explicit_conversion_retains_full_fen(self):
        original = starts.original_tool_positions()
        self.assertEqual(len(original), 6)
        converted = starts.fresh_setups(original)
        self.assertEqual([p['id'] for p in original], [p['id'] for p in converted])
        self.assertTrue(all(len(p['fen'].split(':')) > 3 for p in original))
        for before, after in zip(original, converted):
            self.assertEqual(after['original_fen'], before['fen'])
            self.assertEqual(after['fen'], ':'.join(before['fen'].split(':')[:3]))
            self.assertEqual(after['moves'], [])
            self.assertEqual(after['restrictions'], {})
            self.assertIn('Explicit fresh setup', after['conversion_note'])

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
