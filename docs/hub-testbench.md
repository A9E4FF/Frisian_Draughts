# Hub testbench

The new `tools.testbench` package establishes a GUI-independent Hub v2 contract
before changing the engine. Existing terminal play, Rust search, and
`--analysis-json` remain unchanged. Stage 2 adds `frisian-draughts hub` with
depth-only synchronous searches. Until stage 3, do not use time/node controls,
infinite analysis, pondering or expect stop/ping to interrupt an active search.
Unsupported limit/search modes produce explicit protocol errors. `pos start` is
accepted for compatibility with the supplied GUI in addition to standard boards.

## Run

Python 3.10+; no third-party packages, GUI, or engine needed for unit tests:

```sh
python -m unittest discover -s tools/testbench/tests -v
```

Probe an external Hub engine (executable paths with spaces are supported):

```powershell
python -m tools.testbench 'C:\Engines\Scan\scan.exe' --cwd 'C:\Engines\Scan' --depth 2 --output scan-probe.json
```

The probe launches `ENGINE hub`, initializes Frisian mode with book/bitbases
disabled and one thread, searches the starting position, checks for a move and
ping response, then quits. Exit status is 0 on protocol success, 1 on failure.
It writes a diagnostic JSON transcript and executable SHA-256. This checks the
conversation, **not move legality, playing strength, or full Hub compliance**.
`--arg` can be repeated to replace the default `hub` launch argument.

The Python API exposes `EngineProfile` and `HubSession`: `start`, `begin_search`,
`wait_done`, `stop`, `ping`, and `close`. Use a context manager or `finally` to
close sessions. The API is single-owner; background readers only drain output.
Timeouts leave an active search available for explicit `stop` recovery.

## Wire contract

Reference: Fabien Letouzey, **Hub protocol for draughts, version 2**, 2019-07-06,
distributed with Scan 3.1 as `protocol.txt`; also inspect Scan's `hub.cpp` and
`main.cpp`. The local ScanGraphic build adds commands outside that contract.

| Area | Contract |
| --- | --- |
| Transport | UTF-8 text, one command per line, flushed output; stdout is protocol, stderr diagnostics |
| Syntax | Command followed by `name=value` pairs or bare flags; quote empty values, spaces and equals signs |
| Quoting | Double quotes delimit values; the reference defines no backslash escaping |
| Compatibility | Ignore unknown commands/arguments; recognize commands exactly, not by substring |
| Initialization | `hub` → `id`/`param`/`wait`; `set-param`; `init` → `ready` |
| Positions | `pos pos=<side + 50 squares> moves="..."`; `W/B` side, `w/b/W/B/e` squares |
| Capture notation | Source, destination, captured squares; **not** intermediate landing squares |
| Limits | `level depth`, `nodes`, `move-time`, `time` with optional `moves/inc`, or `infinite` |
| Search | `go think`, `go analyze`, `go ponder`; progressive `info`, one final `done` |
| During search | Respond to `ping` with `pong`; `stop` must still yield `done`; support `ponder-hit` when pondering |
| Lifecycle | `new-game` clears reusable search state; `quit`/stdin EOF exit |
| Units | Seconds; score in men, from side to move; Scan's `nps` is millions of nodes/second |
| Clocks | Hub adds the increment before each move |

The codec validates syntax and board encoding only. A bare `done` is retained
as a message; it must never be interpreted as a loss without a referee checking
the position. Crashes, deadline expiry, malformed output, engine errors and
terminal positions are distinct conditions. Unsupported commands must not be
used to infer support for Scan-specific evaluation or tactics panels.

Board encoding carries neither restriction counters nor repetition history.
Preserve a known initial full state plus replay moves; starting from a midgame
snapshot resets unavailable history. The later suite migration must preserve the
existing position cases' explicit restriction metadata and report cases that
cannot be represented faithfully for an external Hub engine.

## Fixtures and failure coverage

`fixtures/scan-handshake.json` and `scan-depth2.json` are actual local ScanGraphic
Scan 3.1 conversations captured on 2026-11-17. They include the executable hash;
timings and node counts are observations, not benchmark thresholds. The build
can contain custom extensions and is not the pinned differential rules oracle.
No executable, book, evaluation weights or original source tree is vendored.

The synthetic peer tests exact handshake recognition, quoted PVs, fragmented
CRLF messages, stderr pipe saturation, early completion before pong, stale
duplicate results, bounded diagnostic logs/line length, stop/restart, timeout
recovery, malformed messages, engine errors, crashes, no-move messages and
uncooperative shutdown. Search boundaries use a ping barrier to prevent stale
results from silently becoming the next search's answer. Always drain stderr.

Transcripts are bounded diagnostic snapshots (default 2,000 entries), not an
archival match format. Complete per-game records and referee validation belong
to stage 4. Engine-profile capability negotiation and a Qt adapter belong to
the GUI integration stage.

## Staged delivery

Each stage gets a separate pull request and retains the earlier interfaces:

1. **Protocol foundation (this stage):** codec, subprocess session, real Scan
   fixtures, fake-engine tests, optional probe, Linux/Windows Python CI.
2. **Rust Hub mode:** initialization, board/history codec, depth searches and
   search reporting; document limitations before interruptible search exists.
3. **Search control:** time/node limits, cancellation, stop/ping responsiveness,
   clock allocation, completed-iteration fallback and aborted-TT safeguards.
4. **Headless matches:** engine profiles, rules referee, paired schedules,
   clock enforcement, distinct termination reasons and replayable reports.
5. **Position suite migration:** Hub backend while preserving version-1 cases,
   accepted alternatives, analysis-only cases, restrictions and history.
6. **Desktop integration:** PySide6 analysis/positions/matches/replay, with
   Scan-only panels gated by capabilities, then standalone Windows packaging.

Initially the testbench lives in this repository so its first PR has a concrete
review destination and runs with existing CI. It imports no engine or GUI code;
move it into `Frisian_Draughts_Testbench` once the shared interfaces stabilize.
Rust and Scan engine sources remain separate test subjects. The code here uses
this repository's GPL-3.0-only license. Review attribution/licensing before
copying code from the legacy match tools.
