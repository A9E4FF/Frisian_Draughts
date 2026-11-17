import contextlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tools.position_suite.client import AnalysisOutcome, AnalysisSession, format_event, format_header
from tools.position_suite.cli import main
from tools.position_suite.model import load_suite, request_for, save_suite, validate_case, validate_suite


CASE = {'name': 'Edge trap', 'fen': 'W:W31:B16', 'depth': 1,
        'accepted_moves': ['31-27', '31-26'], 'notes': 'Multiple accepted alternatives'}
LOADED = {'type': 'loaded', 'fen': CASE['fen'], 'turn': 'white', 'pieces': [],
          'legal_moves': ['31-26', '31-27'], 'accepted_moves': ['31-27', '31-26'],
          'restrictions': {'white': None, 'black': None}, 'warnings': ['History cleared']}
RESULT = {'type': 'result', 'depth': 1, 'score': -8, 'best_move': '31-26', 'pv': ['31-26'],
          'nodes': 4, 'quiescence_nodes': 3, 'elapsed_ms': .05,
          'tt_probes': 2, 'tt_hits': 1, 'tt_cutoffs': 0}


class FakeProcess:
    def __init__(self, events, code=0):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(''.join(json.dumps(e) + '\n' if isinstance(e, dict) else e for e in events))
        self.code = code
        self.returncode = None
        self.terminated = False
        self.killed = False
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        self.returncode = self.code if self.returncode is None else self.returncode
        return self.returncode
    def terminate(self):
        self.terminated = True
        self.returncode = -15
    def kill(self):
        self.killed = True
        self.returncode = -9


class ModelTests(unittest.TestCase):
    def test_roundtrip_optional_multiple_moves_and_supplementary_state(self):
        case = {**CASE, 'restrictions': {'white': {'square': 28, 'count': 2}, 'black': None},
                'moves': ['28-22'], 'tt_enabled': False}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'suite.json'
            save_suite(path, [case, {**CASE, 'accepted_moves': []}])
            cases = load_suite(path)
        self.assertEqual(cases[0]['accepted_moves'], ['31-27', '31-26'])
        self.assertEqual(cases[0]['restrictions'], case['restrictions'])
        request = request_for(cases[0])
        self.assertEqual(request['moves'], ['28-22'])
        self.assertNotIn('notes', request)
        self.assertFalse(request['tt_enabled'])

    def test_invalid_case_and_schema_values(self):
        for bad in [None, [], {'version': 2, 'positions': []}, {'version': True, 'positions': []},
                    {'version': 1, 'positions': {}}]:
            with self.assertRaises(ValueError):
                validate_suite(bad)
        for update in [{'depth': True}, {'depth': 0}, {'depth': 65}, {'accepted_moves': '31-27'},
                       {'accepted_moves': ['']}, {'fen': ''}, {'name': ''}, {'moves': [3]},
                       {'restrictions': []}, {'tt_enabled': 1}, {'tt_megabytes': 0}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_case({**CASE, **update})

    def test_failed_save_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'suite.json'
            path.write_text('original', encoding='utf-8')
            with self.assertRaises(ValueError):
                save_suite(path, [{**CASE, 'depth': 0}])
            self.assertEqual(path.read_text(), 'original')

    def test_readable_logs_include_settings_full_pv_and_tt_stats(self):
        text = format_header(CASE, 'engine') + format_event(LOADED) + format_event(RESULT)
        for fragment in [CASE['fen'], '31-27, 31-26', 'History cleared', 'PV: 31-26',
                         'TT probes/hits/cutoffs=2/1/0', 'score=-8']:
            self.assertIn(fragment, text)
        self.assertIn('unsearched', format_event({**RESULT, 'score': None}))


class ClientTests(unittest.TestCase):
    def run_events(self, events, case=CASE, code=0, command='analyze'):
        process = FakeProcess(events, code)
        received = []
        with patch('tools.position_suite.client.subprocess.Popen', return_value=process):
            result = AnalysisSession('/fake/engine').run(case, received.append, command)
        return result, received, process

    def test_any_accepted_alternative_passes(self):
        # The second accepted alternative is valid, not just the first.
        result, events, _ = self.run_events([LOADED, {**RESULT, 'type': 'iteration'}, RESULT])
        self.assertEqual(result.status, 'passed')
        self.assertEqual([e['type'] for e in events], ['loaded', 'iteration', 'result'])

    def test_fail_and_analysis_only_are_distinct(self):
        self.assertEqual(self.run_events([LOADED, {**RESULT, 'best_move': 'other'}])[0].status, 'failed')
        case = {**CASE, 'accepted_moves': []}
        self.assertEqual(self.run_events([{**LOADED, 'accepted_moves': []}, RESULT], case)[0].status, 'analysis')

    def test_illegal_expected_move_is_error_even_when_process_exits_zero(self):
        result, _, _ = self.run_events([{'type': 'error', 'message': 'Illegal accepted move'}])
        self.assertEqual(result.status, 'error')
        self.assertIn('Illegal accepted move', result.message)

    def test_invalid_json_missing_result_and_nonzero_exit_are_errors(self):
        for events, code in [(['not JSON\n'], 0), ([LOADED], 0), ([LOADED, RESULT], 4),
                             ([RESULT], 0), ([{'type': 'unknown'}], 0)]:
            with self.subTest(events=events, code=code):
                self.assertEqual(self.run_events(events, code=code)[0].status, 'error')

    def test_inspect_requires_loaded_but_no_result(self):
        result, _, _ = self.run_events([LOADED], command='inspect')
        self.assertEqual(result.status, 'inspected')

    def test_cancel_before_start_does_not_launch(self):
        session = AnalysisSession('/fake/engine')
        session.cancel()
        with patch('tools.position_suite.client.subprocess.Popen') as launch:
            self.assertEqual(session.run(CASE).status, 'cancelled')
            launch.assert_not_called()

    def test_cancel_during_stream_never_reports_pass(self):
        session = AnalysisSession('/fake/engine')
        process = FakeProcess([LOADED, {**RESULT, 'type': 'iteration'}, RESULT])
        def receive(event):
            if event['type'] == 'iteration':
                session.cancel()
        with patch('tools.position_suite.client.subprocess.Popen', return_value=process):
            result = session.run(CASE, receive)
        self.assertEqual(result.status, 'cancelled')
        self.assertTrue(process.terminated)

    def test_missing_executable_is_actionable_error(self):
        result = AnalysisSession('/a/nonexistent/frisian-engine').run(CASE)
        self.assertEqual(result.status, 'error')
        self.assertIn('frisian-engine', result.message)


class RealProcessTests(unittest.TestCase):
    def launch_script(self, script, receive=None):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fake_engine.py'
            path.write_text(script,encoding='utf-8')
            original=subprocess.Popen
            def spawn(args, **kwargs):
                return original([sys.executable,str(path),*args[1:]],**kwargs)
            session=AnalysisSession('/unused/engine')
            with patch('tools.position_suite.client.subprocess.Popen',side_effect=spawn):
                return session.run(CASE, (lambda event: receive(session,event)) if receive else lambda event: None)

    def test_real_stream_with_large_stderr_does_not_block(self):
        script=("import json,sys\nrequest=json.loads(sys.stdin.readline())\n"
                "assert request['command']=='analyze'\n"
                "sys.stderr.write('diagnostic'*10000)\n"
                f"print({json.dumps(json.dumps(LOADED))},flush=True)\n"
                f"print({json.dumps(json.dumps(RESULT))},flush=True)\n")
        self.assertEqual(self.launch_script(script).status,'passed')

    def test_real_running_process_is_cancelled_without_a_verdict(self):
        script=("import json,sys,time\njson.loads(sys.stdin.readline())\n"
                f"print({json.dumps(json.dumps(LOADED))},flush=True)\n"
                f"print({json.dumps(json.dumps({**RESULT,'type':'iteration'}))},flush=True)\n"
                "time.sleep(60)\n")
        start=time.monotonic()
        outcome=self.launch_script(script,lambda session,event: session.cancel() if event['type']=='iteration' else None)
        self.assertEqual(outcome.status,'cancelled')
        self.assertLess(time.monotonic()-start,5)


class CliTests(unittest.TestCase):
    def test_mixed_cases_logs_and_failure_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = Path(tmp) / 'suite.json'
            logs = Path(tmp) / 'logs'
            save_suite(suite, [CASE, {**CASE, 'name': 'Manual', 'accepted_moves': []}])
            with patch('tools.position_suite.cli.AnalysisSession') as sessions:
                sessions.return_value.run.side_effect = [AnalysisOutcome('failed', RESULT), AnalysisOutcome('analysis', RESULT)]
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(['run', str(suite), '--logs', str(logs), '--depth', '2', '--no-tt'])
                first = sessions.return_value.run.call_args_list[0].args[0]
                self.assertEqual(first['depth'], 2)
                self.assertFalse(first['tt_enabled'])
            self.assertEqual(code, 1)
            paths = sorted(logs.glob('*.txt'))
            self.assertEqual(len(paths), 2)
            self.assertIn('STATUS: FAILED', paths[0].read_text())
            self.assertIn('STATUS: ANALYSIS', paths[1].read_text())

    def test_bad_suite_returns_two(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['run', '/no/such/suite.json']), 2)


if __name__ == '__main__':
    unittest.main()
