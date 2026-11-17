from pathlib import Path
import json
import unittest

from tools.testbench.protocol import ProtocolError, parse, serialize, validate_position


class CodecTests(unittest.TestCase):
    def test_quotes_flags_spacing_and_unknown_fields(self):
        message = parse(' info\tdepth = 4 pv="31-26 16-21" custom="a=b" flag\r\n')
        self.assertEqual(message.command, 'info')
        self.assertEqual(message.get('pv'), '31-26 16-21')
        self.assertEqual(message.get('custom'), 'a=b')
        self.assertTrue(message.has('flag'))
        self.assertEqual(message.get('flag'), '')
        self.assertIsNone(message.get('missing'))

    def test_round_trip_without_shell_escaping(self):
        pairs = [('path', r'C:\Engine Folder\scan.exe'), ('empty', ''),
                 ('equals', 'a=b'), ('pv', '28x19x23 12x21x17'), ('flag', None)]
        result = parse(serialize('extension', pairs))
        self.assertEqual(result.pairs, tuple((k, '' if v is None else v) for k, v in pairs))

    def test_duplicate_arguments_follow_scan_order(self):
        self.assertEqual(parse('level depth=2 depth=4').get('depth'), '4')

    def test_invalid_lines(self):
        for line in ['', ' ', 'info pv="unfinished', 'info a=',
                     'info a="x"b=y', 'info =x', 'ping\nquit', 'info x=\x00']:
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                parse(line)

    def test_reject_wire_injection(self):
        for value in ['a"b', 'a\nb', 'a\rb', '\x00', '\t']:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                serialize('set-param', [('value', value)])
        for name in ['bad name', '', 'a=b']:
            with self.assertRaises(ProtocolError):
                serialize(name)

    def test_board_encoding_is_not_fen(self):
        initial = 'W' + 'b' * 20 + 'e' * 10 + 'w' * 20
        self.assertEqual(validate_position(initial), initial)
        for value in ['W:W31-50:B1-20', initial[:-1], initial + 'e',
                      'X' + initial[1:], 'W' + 'x' * 50]:
            with self.assertRaises(ProtocolError):
                validate_position(value)

    def test_reference_transcript(self):
        path = Path(__file__).parents[1] / 'fixtures' / 'scan-handshake.json'
        fixture = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(fixture['protocol'], 'Hub v2')
        output = [parse(e['line']) for e in fixture['events'] if e['direction'] == 'stdout']
        self.assertTrue(any(m.command == 'id' and m.get('name') == 'Scan' for m in output))
        self.assertIn('wait', [m.command for m in output])
        self.assertIn('pong', [m.command for m in output])


if __name__ == '__main__':
    unittest.main()
