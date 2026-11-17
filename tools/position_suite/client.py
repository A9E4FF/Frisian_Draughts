"""Streaming subprocess bridge and plain-text search logs; no GUI dependencies."""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
import threading

from .model import HISTORY_NOTE, request_for


@dataclass
class AnalysisOutcome:
    status: str
    result: dict | None = None
    message: str = ''


def format_header(case, engine):
    return (f"Position: {case['name']}\nEngine: {Path(engine).resolve()}\n"
            f"FEN: {case['fen']}\nDepth: {case.get('depth', 10)}\n"
            f"Accepted moves: {', '.join(case.get('accepted_moves', [])) or '(analysis only)'}\n"
            f"TT: {'on' if case.get('tt_enabled', True) else 'off'}; "
            f"memory: {case.get('tt_megabytes', 16)} MiB\n"
            f"Restrictions: {json.dumps(case.get('restrictions', {}), sort_keys=True)}\n"
            f"Replay moves: {' '.join(case.get('moves', [])) or '(none)'}\n"
            f"Notes: {case.get('notes', '')}\n{HISTORY_NOTE}\n\n")


def format_event(event):
    kind = event.get('type')
    if kind == 'loaded':
        warnings = ''.join(f'Warning: {w}\n' for w in event.get('warnings', []))
        return (f"Loaded FEN: {event.get('fen', '')}\nTurn: {event.get('turn', '')}\n"
                f"Restrictions: {json.dumps(event.get('restrictions', {}), sort_keys=True)}\n"
                f"Legal moves: {' '.join(event.get('legal_moves', []))}\n"
                f"Canonical accepted moves: {' '.join(event.get('accepted_moves', [])) or '(none)'}\n{warnings}")
    if kind in ('iteration', 'result'):
        score = event.get('score')
        score_text = 'unsearched' if score is None else f'{score:+}'
        return (f"{kind.upper()} depth={event.get('depth', 0)} score={score_text} "
                f"best={event.get('best_move') or '(none)'} nodes={event.get('nodes', 0)} "
                f"qnodes={event.get('quiescence_nodes', 0)} time={event.get('elapsed_ms', 0):.3f}ms "
                f"TT probes/hits/cutoffs={event.get('tt_probes', 0)}/{event.get('tt_hits', 0)}/{event.get('tt_cutoffs', 0)}\n"
                f"PV: {' '.join(event.get('pv', [])) or '(none)'}\n")
    if kind == 'error':
        return f"ERROR: {event.get('message', 'Unknown engine error')}\n"
    return f'{json.dumps(event, ensure_ascii=False)}\n'


class AnalysisSession:
    """Run in a worker thread; cancel() is safe to call from the GUI thread."""
    def __init__(self, engine):
        self.engine = str(Path(engine).expanduser().resolve())
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process = None

    def cancel(self):
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                return
            # Never wait on Tk's event thread. A stubborn child is killed shortly.
            def reap():
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
            threading.Thread(target=reap, daemon=True).start()

    def run(self, case, on_event=lambda event: None, command='analyze'):
        process = None
        result = None
        loaded = None
        errors = []
        try:
            request = request_for(case, command)
            if self._cancelled.is_set():
                return AnalysisOutcome('cancelled', message='Analysis cancelled')
            with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stderr:
                process = subprocess.Popen([self.engine, '--analysis-json'], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=stderr, text=True,
                                           encoding='utf-8', bufsize=1)
                with self._lock:
                    self._process = process
                if self._cancelled.is_set():
                    self.cancel()
                try:
                    process.stdin.write(json.dumps(request) + '\n')
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    if not self._cancelled.is_set():
                        errors.append('Engine closed its input unexpectedly')
                for line in process.stdout:
                    if self._cancelled.is_set():
                        break
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict) or event.get('type') not in ('loaded', 'iteration', 'result', 'error'):
                            raise ValueError('unknown event type')
                    except (ValueError, TypeError) as exc:
                        errors.append(f'Invalid engine output: {exc}: {line.strip()}')
                        break
                    if event['type'] == 'loaded':
                        loaded = event
                    elif event['type'] == 'error':
                        errors.append(str(event.get('message', 'Engine error')))
                    elif event['type'] == 'result':
                        result = event
                    on_event(event)
                if errors or self._cancelled.is_set():
                    if process.poll() is None:
                        process.terminate()
                try:
                    code = process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    errors.append('Engine did not exit after the request')
                stderr.seek(0)
                details = stderr.read().strip()
                if self._cancelled.is_set():
                    return AnalysisOutcome('cancelled', message='Analysis cancelled; no test verdict recorded')
                if code != 0:
                    errors.append(f'Engine exited with code {code}' + (f': {details}' if details else ''))
                if errors:
                    return AnalysisOutcome('error', message='; '.join(errors))
                if loaded is None:
                    return AnalysisOutcome('error', message='Engine did not confirm a loaded position')
                if command == 'inspect':
                    return AnalysisOutcome('inspected')
                if result is None:
                    return AnalysisOutcome('error', message='Engine exited without a result')
                accepted = loaded.get('accepted_moves', [])
                if case.get('accepted_moves') and not accepted:
                    return AnalysisOutcome('error', message='Engine did not validate accepted moves')
                # Match full canonical move identities, including captured sets.
                status = ('passed' if result.get('best_move') in accepted else 'failed') if request['accepted_moves'] else 'analysis'
                return AnalysisOutcome(status, result)
        except (OSError, ValueError, TypeError) as exc:
            return AnalysisOutcome('cancelled' if self._cancelled.is_set() else 'error', message=f'{self.engine}: {exc}')
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
            with self._lock:
                self._process = None

