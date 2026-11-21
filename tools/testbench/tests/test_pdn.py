import os
import unittest
from tools.testbench import pdn


class DocumentTests(unittest.TestCase):
    def test_multigame_annotations_variations_and_escaping_roundtrip(self):
        text = '[Event "A \\\"quote\\\""]\n[Result "*"]\n\n1. 31-26 {comment} $1 (1. 32-28 !? (1. 33-29)) 16-21 ;line\n*\n\n[Event "B"]\n[Result "*"]\n1. 32-28 *'
        games = pdn.loads(text)
        restored = pdn.loads(pdn.dumps(games))
        self.assertEqual(len(games), 2)
        self.assertEqual([(g.tags, g.tokens) for g in games], [(g.tags, g.tokens) for g in restored])

    def test_malformed_game_recovers_at_next_header(self):
        games = pdn.loads('[Event "Bad"]\n1. 31-26 {unclosed\n\n[Event "Good"]\n1. 32-28 *')
        self.assertEqual(len(games), 2)
        self.assertTrue(games[0].errors)
        self.assertEqual(games[1].tag('Event'), 'Good')

    def test_black_start_and_lossless_capture_export(self):
        game = pdn.from_record({'fen': 'B:WK28:B23', 'moves': ['23x32x28'], 'result': '*'})
        self.assertEqual(game.tokens[0], '1...')
        self.assertIn('{[%hub 23x32x28]}', game.tokens)
        self.assertEqual(pdn.loads('1. 31-26 16-21 1-0')[0].result, '1-0')

    def test_missing_setup_and_other_variants_are_explicit(self):
        for tags in [[('SetUp', '1')], [('GameType', '20')]]:
            game = pdn.validate(pdn.Game(tags), None)
            self.assertTrue(game.errors)

    def test_ambiguous_capture_never_guessed(self):
        state = {'legal_moves': ['49x47x7x11', '49x47x8x12'], 'pieces': [], 'turn': 'white'}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            pdn.resolve('49x47', state)
        self.assertEqual(pdn.resolve('49x47', state, '49x47x7x11'), '49x47x7x11')
        with self.assertRaises(ValueError):
            pdn.resolve('49x46', state, '49x47x7x11')

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real referee required')
    def test_referee_validates_variations_fen_and_landing_paths(self):
        from tools.testbench.referee import Referee
        referee = Referee(os.environ['FRISIAN_TEST_ENGINE'])
        games = pdn.loads('[Result "*"]\n1. 31-26 (1. 32-28 17-22) 16-21 *\n\n[FEN "W:WK28:B23"]\n[Result "1-0"]\n1. 28x19 1-0')
        for game in games:
            pdn.validate(game, referee)
            self.assertEqual(game.errors, [])
        self.assertEqual(games[1].moves, ['28x19x23'])
        exported = pdn.from_record({'fen': games[1].fen, 'moves': games[1].moves, 'result': '1-0'})
        restored = pdn.validate(pdn.loads(pdn.dumps([exported]))[0], referee)
        self.assertEqual(restored.moves, games[1].moves)
        self.assertEqual(restored.errors, [])

    @unittest.skipUnless(os.environ.get('FRISIAN_TEST_ENGINE'), 'real referee required')
    def test_standard_multicapture_and_scan_dialects(self):
        from tools.testbench.referee import Referee
        referee = Referee(os.environ['FRISIAN_TEST_ENGINE'])
        record = {'fen': 'W:W11:B7,8', 'moves': ['11x13x7x8'], 'result': '1-0'}
        standard = pdn.from_record(record, referee)
        self.assertIn('11x2x13', standard.tokens)
        for dialect in ['standard', 'scan']:
            exported = pdn.dumps([pdn.from_record(record, referee, dialect)])
            restored = pdn.validate(pdn.loads(exported)[0], referee)
            self.assertEqual(restored.errors, [])
            self.assertEqual(restored.moves, record['moves'])

    @unittest.skipUnless(os.environ.get('SCAN_GUI_SOURCE'), 'optional original Scan GUI compatibility check')
    def test_scan_gui_parser_reads_exported_capture_identities(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path(os.environ['SCAN_GUI_SOURCE']).read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('parse_pdn_moves', 'scan_fen_to_hub', 'parse_pdn_games')]
        scope = {}; exec(compile(ast.Module(functions, type_ignores=[]), '<Scan GUI parser>', 'exec'), scope)
        record = {'fen': 'W:W11:B7,8', 'moves': ['11x13x7x8'], 'result': '1-0'}
        text = pdn.dumps([pdn.from_record(record, dialect='scan')])
        self.assertEqual(scope['parse_pdn_games'](text)[0]['moves'], record['moves'])


if __name__ == '__main__':
    unittest.main()
