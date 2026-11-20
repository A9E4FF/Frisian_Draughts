"""GUI-independent Hub subprocess session with explicit lifecycle and deadlines."""
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
import queue
import subprocess
import threading
import time

from .protocol import Message, ProtocolError, parse, serialize, validate_position


class HubError(RuntimeError):
    pass


class HubTimeout(HubError):
    pass


class HubCancelled(HubError):
    pass


class EngineExited(HubError):
    pass


@dataclass(frozen=True)
class EngineProfile:
    executable: str
    arguments: tuple[str, ...] = ('hub',)
    cwd: str | None = None


class HubSession:
    """Single-owner API; reader threads only transport bytes and record logs.

    A timeout is an error, never a terminal loss. Call stop() after a search
    timeout if recovery is desired. A board referee must separately validate
    done.move. The bounded transcript is diagnostic, not a complete game record.
    """

    def __init__(self, profile: EngineProfile, *, max_line=1_048_576, log_lines=2000):
        if max_line < 1 or log_lines < 1:
            raise ValueError('line and transcript limits must be positive')
        self.profile = profile
        self.state = 'new'
        self.identity: Message | None = None
        self.parameters: dict[str, Message] = {}
        self._max_line = max_line
        self._events = queue.Queue()
        self._log = deque(maxlen=log_lines)
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._process = None
        self._readers = []
        self._pending_done = None
        self.cancel_event = None
        self.search_started = None

    @property
    def transcript(self):
        with self._lock:
            return list(self._log)

    def _record(self, direction, line):
        with self._lock:
            self._log.append({'seconds': time.monotonic() - self._started,
                              'direction': direction, 'line': line})

    def _read(self, stream, direction):
        try:
            while True:
                raw = stream.readline(self._max_line + 1)
                if not raw:
                    break
                if len(raw) > self._max_line:
                    if direction == 'stdout':
                        self._events.put(ProtocolError('engine line exceeds limit'))
                        break
                    # Drain large diagnostic output in chunks; never block stderr.
                text = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                self._record(direction, text)
                if direction == 'stdout':
                    self._events.put(text)
        except (OSError, ValueError) as exc:
            if direction == 'stdout':
                self._events.put(EngineExited(str(exc)))
        finally:
            if direction == 'stdout':
                self._events.put(EngineExited('engine stdout closed'))

    def send(self, command, pairs=()):
        line = serialize(command, pairs)
        if self._process is None or self.state == 'closed':
            raise EngineExited('engine is not running')
        self._record('stdin', line)
        try:
            self._process.stdin.write((line + '\n').encode('utf-8'))
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise EngineExited('engine input closed') from exc

    def _wait(self, command, timeout, on_info=None):
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        deadline = time.monotonic() + timeout
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise HubCancelled('engine operation cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HubTimeout(f'timed out waiting for {command}')
            try:
                event = self._events.get(timeout=min(0.1, remaining))
            except queue.Empty as exc:
                continue
            if isinstance(event, Exception):
                raise event
            if not event.strip():
                continue
            message = parse(event)
            if message.command == 'error':
                raise HubError(message.get('message', 'engine error'))
            if message.command == 'id':
                self.identity = message
            elif message.command == 'param' and message.get('name'):
                self.parameters[message.get('name')] = message
            elif message.command == 'info' and on_info:
                on_info(message)
            if message.command == command:
                return message
            if message.command == 'done':
                # A fast search may finish before the engine answers ping.
                if command == 'pong' and self.state == 'searching' and self._pending_done is None:
                    self._pending_done = message
                else:
                    raise HubError(f'unexpected search result while waiting for {command}')
            # Ignore unknown commands as required by Hub v2.

    def start(self, parameters=None, *, timeout=10, cancel_event=None):
        if self.state != 'new':
            raise HubError('session already started')
        self.cancel_event = cancel_event
        try:
            self._process = subprocess.Popen(
                [self.profile.executable, *self.profile.arguments],
                cwd=self.profile.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            self.state = 'initializing'
            for stream, direction in [(self._process.stdout, 'stdout'),
                                      (self._process.stderr, 'stderr')]:
                thread = threading.Thread(target=self._read, args=(stream, direction), daemon=True)
                self._readers.append(thread)
                thread.start()
            self.send('hub')
            self._wait('wait', timeout)
            selected = parameters(self) if callable(parameters) else parameters
            for name, value in (selected or {}).items():
                self.send('set-param', [('name', name), ('value', value)])
            self.send('init')
            self._wait('ready', timeout)
            self.state = 'ready'
            return self
        except Exception:
            self.close()
            raise

    def begin_search(self, position, *, moves=(), level=(('depth', 4),), mode='think', restrictions=None):
        if self.state != 'ready':
            raise HubError('engine must be ready before a search')
        validate_position(position)
        if mode not in ('think', 'analyze', 'ponder'):
            raise ValueError('invalid search mode')
        # Serialize everything before changing engine state on the wire.
        pairs = [('pos', position)]
        if restrictions is not None:
            pairs.append(('frisian-state', restrictions))
        if moves:
            pairs.append(('moves', ' '.join(moves)))
        serialize('pos', pairs)
        serialize('level', level)
        # Synchronization barrier also exposes unsolicited/stale done messages
        # before the next position is sent. Hub does not carry search IDs.
        self.ping()
        self.send('pos', pairs)
        self.send('level', level)
        self.search_started = time.monotonic()
        self.send('go', [(mode, None)])
        self.state = 'searching'

    def wait_done(self, *, timeout=10, on_info=None):
        if self.state != 'searching':
            raise HubError('no active search')
        result = self._pending_done
        self._pending_done = None
        if result is None:
            result = self._wait('done', timeout, on_info)
        self.state = 'ready'
        return result

    def stop(self, *, timeout=5, on_info=None):
        if self.state != 'searching':
            raise HubError('no active search')
        self.send('stop')
        return self.wait_done(timeout=timeout, on_info=on_info)

    def ping(self, *, timeout=5):
        if self.state not in ('ready', 'searching'):
            raise HubError('engine is not initialized')
        self.send('ping')
        return self._wait('pong', timeout)

    def close(self):
        process = self._process
        if process is None or self.state == 'closed':
            self.state = 'closed'
            return
        try:
            if process.poll() is None:
                try:
                    self.send('quit')
                except HubError:
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            self.state = 'closed'
            with suppress(OSError):
                process.stdin.close()
            for reader in self._readers:
                reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
