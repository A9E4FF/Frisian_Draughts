# Python position suite

This local desktop tool imports **draughts FEN**, previews the position, streams
Rust search logs, and saves reusable analysis/regression cases. Python does not
implement move legality or search; the compiled Rust engine validates positions
and every accepted move.

## Start

From the repository root:

```sh
cargo build --release
python3 -m tools.position_suite
```

Requires Python 3.10+ and Tkinter. Tkinter normally ships with Python installers;
some Linux distributions package it separately as `python3-tk`. On Windows use
`python` instead of `python3`. The GUI can browse to another engine executable;
its default is the repository's `target/release/frisian-draughts` (`.exe` on Windows).
No pip packages or web server are needed.

## Analyze a position

1. Paste a FEN such as `W:W31-50:B1-20` or `W:WK28:B23`. `W`/`B` before the first
   colon indicates the side to move; `K` marks kings, and ranges are supported.
2. Enter a name, notes, and depth (1–64). TT can be disabled or assigned 1–256 MiB. Leave accepted moves blank for analysis,
   or enter several alternatives separated by commas or spaces.
3. Use **Import / Preview** to validate and display the numbered board, canonical
   accepted moves, legal choices, and warnings. Use **Analyze** to run search.
4. Logs arrive after each completed iteration: depth, side-to-move score, best
   move, principal variation, total/quiescence nodes, elapsed time, and TT counters.
   A sole legal move may be returned immediately with no searched score.
5. **Cancel** stops the child process without recording a successful test verdict.
   **Export log** writes the currently displayed complete text to a `.txt` file.

An expected-move test passes when the final selected move matches **any** supplied
alternative. Empty alternatives mean **analysis only**, not an automatic pass.
Illegal or ambiguous alternatives are errors before search begins. For ambiguous
captures, use the full legal identifier including captured squares displayed by
the engine, rather than guessing which path endpoints mean.

Standard draughts FEN omits king-restriction counters and repetition history.
Imports start with cleared counters/history unless supplementary state is supplied.
The optional restriction JSON field accepts, for example:

```json
{"white": {"square": 28, "count": 2}, "black": null}
```

The starting FEN must actually contain the tracked king and a man of that side.
Optional replay moves are applied after this initial state to reconstruct history.
Accepted moves apply to the **resulting position after replay**, not the initial FEN.
The board/log show the resulting position. Rust validates all of these details.

## Save and run cases

Use **Add / Update case** to store the form in the in-memory list, then **Save suite**
to write a version-1 JSON file. Merely editing a form does not update a saved case.
**Load suite** opens an existing file; select a case and preview/analyze it.
The bundled `tools/position_suite/sample-suite.json` demonstrates analysis-only,
forced-capture, edge-trap, and multiple-accepted-landing cases.

```sh
python3 -m tools.position_suite run tools/position_suite/sample-suite.json \
  --logs /tmp/frisian-position-logs --verbose
```

The headless runner writes one readable text log per case and prints the verdicts.
Use `--engine PATH`, `--depth 4`, or `--no-tt` to select the binary, override depths,
or compare without transposition tables. Exit code 0 means no failed/error cases;
1 means an unexpected move or engine error; 2 means a suite/logging configuration
error; Ctrl-C returns 130. Analysis-only cases are reported separately.

```json
{
  "version": 1,
  "positions": [
    {
      "name": "My combination",
      "fen": "W:WK28:B23",
      "depth": 10,
      "accepted_moves": ["28x19", "28x14", "28x10", "28x5"],
      "notes": "Any listed winning landing is accepted.",
      "moves": [],
      "restrictions": {},
      "tt_enabled": true,
      "tt_megabytes": 16
    }
  ]
}
```

Supplementary `moves`, `restrictions`, and TT settings are optional. Suite loading
validates file structure; use preview/analyze or the runner to validate game rules.
Depth and expected moves belong to each case so regression runs are reproducible.

## Engine interface and tests

The existing JSON backend remains the default. To use a Hub v2 engine:

```sh
python3 -m tools.position_suite run tools/position_suite/sample-suite.json --protocol hub --engine /path/to/scan --engine-cwd /path/to/scan-data --referee target/release/frisian-draughts --logs hub-position-logs
```

The separate Rust referee validates imported states, accepted alternatives,
selected moves and the final PV. Existing version-1 cases load unchanged.
Analysis-only remains distinct from pass; cancellation never produces a verdict.
Hub scores in men are normalized to the JSON backend's 100-points-per-man scale.
TT counters absent from a generic engine are not available in this backend.

Imported nonzero king restrictions need the advertised `frisian-state-v1`
extension (implemented by Rust). Unsupported engines report an explicit error
instead of silently clearing counters. Replay from a known cleared position
works over ordinary Hub. Explicit TT-disable/memory requests also error when
the selected engine does not advertise the required parameter.

`tools/testbench/examples/regression-suite.json` adds a known quiet sacrifice,
orthogonal trap, promotion-row capture, alternative king captures, restriction
state, threefold replay and an analysis-only promotion race. Exploratory cases
are not assigned unverified expected moves.

The client starts `ENGINE --analysis-json`, writes a single JSON request line,
closes stdin, and reads JSON events through EOF. `loaded` events provide the board
and canonical accepted moves, `iteration` streams progress, `result` carries the
final selection, and `error` is a failed import/analysis even if the process exits
zero. Nonzero exits, malformed output, and missing results are errors. stderr is
captured separately, so diagnostics cannot corrupt the JSON stream.

```sh
python3 -m unittest discover -s tools/position_suite/tests -v
```

The model/client/runner tests run without a display or Tkinter initialization. They cover suite
validation/round-trips, multiple alternatives, no-expectation analysis, engine errors,
streamed logs, cancellation, and runner exit codes. Real-engine checks additionally
exercise the bundled suite after building the Rust binary. An optional Tk widget
smoke test runs when `DISPLAY` is set; it tests preview, live analysis, alternative
answers, suite save/load, log export, cancellation, and recovery. Set
`FRISIAN_TEST_ENGINE` to choose the binary for this test (default: the debug binary).

