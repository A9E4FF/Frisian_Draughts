# Frisian Draughts

The optional [unified desktop testbench](docs/desktop-guide.md) provides engine
profiles, live paired matches, analysis, position suites, PDN import/export and
validated replay. Launch with `python -m tools.testbench.gui`; Windows CI also
builds a standalone ZIP containing the matching Rust engine and rules referee.
The desktop stack is based on the integration branch containing stages 2–5.

A Rust Frisian Draughts engine using Scan 3.1 as its rules and search reference.
The terminal opponent uses iterative-deepening alpha-beta with capture quiescence
and a small edge-aware evaluator. No opening books or external weights are used.

## Build and play

Install stable Rust using [rustup](https://rustup.rs), then:

```sh
cargo run --release
```

You play White; Black responds automatically. Men are `w`/`b`, kings `W`/`B`.
Empty dark squares display their standard numbers (1–50).

| Command | Action |
| --- | --- |
| `help` | Show commands |
| `board` | Display the current board |
| `moves` | List legal moves, with full capture identifiers |
| `play 31-26` | Play a quiet move |
| `play 28x19` | Play a capture when endpoints identify it uniquely |
| `go` | Ask the engine to play the side to move |
| `depth 10` | Set search depth (1–64; default 10) |
| `undo` | Undo the last human move and its automatic response, or the last `go` |
| `new` | Start a new game |
| `quit` | Exit (EOF also exits) |

When multiple captures share endpoints, use the exact identifier printed by
`moves`, such as `49x47x7x11x19x30x42`. Numbers after the destination are the
**captured-square set in ascending order**, not the sequence of landing squares.
Ambiguous or illegal input leaves the game unchanged.

Captures are mandatory. The engine generates complete capture sequences, retains
only those allowed by Frisian capture priorities, and searches competing choices.
A sole legal move is played immediately, without a searched score. Quiet positions
are searched too. Legal moves are ordered by source, destination, then captured
squares; search tries the preceding iteration’s principal variation first.

The rules include orthogonal captures, backward man captures, flying kings,
end-of-move promotion, captured-piece blocking, and the king's three-quiet-move
restriction while men remain. Loss is detected when the side to move cannot move;
three occurrences of the same full position produce a draw. This is a Scan-based
rules baseline, not certification of every tournament adjudication rule.

## Library

```rust
use frisian_draughts::{Game, Outcome};
use frisian_draughts::search::{search, SearchLimits};

fn main() -> Result<(), frisian_draughts::Error> {
    let mut game = Game::default();
    let human_move = game.position().parse_move("31-26")?;
    game.play(&human_move)?;
    let result = search(&game, SearchLimits::new(4)?);
    if let Some(reply) = result.best_move {
        game.play(&reply)?;
    }
    assert_eq!(game.outcome(), Outcome::Ongoing);
    Ok(())
}
```

`Position` owns piece masks, side to move, and king restrictions. Its checked
constructor accepts `(Square, Side, Piece)` entries plus restriction states ordered
White/Black. `Position::legal_moves`, `parse_move`, and `apply` enforce legality;
`Game` additionally tracks repetition, game outcome, and undo. `Game::choose_move`
returns `None` when the game is over. These existing `choose_move` methods retain
the original deterministic first-move behavior. Use `search(&game, limits)` for the
new opponent. Search returns a move, side-to-move score, principal variation,
completed depth, total/quiescence node counts, and elapsed time without changing
the game. A sole legal move has no searched score and completed depth zero;
terminal games have no selected move. Positions alone contain no repetition history.
No unsafe Rust is used. The JSON analysis bridge uses Serde and serde_json;
the Python position suite uses the standard library and Tkinter. Bitboards retain Scan's padded
63-index mapping. Man candidates use masked shifts; king moves and captures use
precomputed rays and capture-path masks initialized once. Set-bit iteration and
region population counts avoid scanning empty squares. The coordinate generator
and evaluator remain available only in tests as independent references. See the [initial analysis](docs/scan-rust-analysis.md)
for future search work.

## Search behavior

The default depth is **10 plies** (roughly five moves per side). A complete
multi-capture sequence counts as one ply. At the horizon, all mandatory capture
choices are searched until reaching a quiet position; stand pat is never allowed
instead of a capture. Wins favor shorter lines; losses favor longer lines.
Threefold repetition includes both game history and the current search path,
with king restriction state participating in position identity.

The evaluator starts with men = 100, kings = 300, men on outer side files = +8,
and men on the adjacent files = +4. Tracked king quiet-move counts 1/2/3 cost
2/6/12 points. These are provisional values, not Scan’s learned weights. Tactical
search takes precedence over the edge preference; kings receive no edge bonus.

Search is single-threaded and uses a bounded 16 MiB transposition table per search.
There are no reductions, forward pruning, or hidden time limits. Depth 10 can take noticeable time. For quicker
responses, enter `depth 4` or `depth 6`. `new` and `undo` retain the depth setting;
invalid settings leave it unchanged. Terminal statistics include quiescence nodes
and work from all iterative-deepening passes. An immediate sole-move selection
is explicitly marked as unsearched.

Capture quiescence resolves exchanges beyond the nominal horizon; it does not
promise to see consequences 10–15 full moves away. See the
[benchmark record](docs/search-benchmarks.md) for measured examples and the
[initial analysis](docs/scan-rust-analysis.md) for later search improvements.

## Transposition tables

Each search shares a bounded table across iterative-deepening passes. Keys cover
pieces, side to move, and king restrictions, and full positions are checked to
reject hash collisions. Score reuse is conservative: equal remaining depth and
clean repetition contexts are required. Reversible king-history nodes use cached
moves only for ordering. Terminal-distance scores and replayable PVs are retained.

`SearchLimits::with_tt_enabled(false)` selects the uncached baseline;
`with_tt_megabytes(n)` accepts 1–256 MiB (default 16). Tables are fresh per search.
`search_with_reporter(game, limits, callback)` reports every completed iteration,
including cumulative `tt_probes`, `tt_hits`, and `tt_cutoffs`. The existing `search`
API remains available. See [TT behavior and benchmarks](docs/transposition-tables.md).

```sh
cargo run --release --example tt_bench
```

## Python position suite

Build the engine, then launch the minimal desktop tool from the repository root:

```sh
cargo build --release
python3 -m tools.position_suite
```

The tool imports draughts FEN (for example `W:W31-50:B1-20`), previews the numbered
board, and streams per-depth text logs with scores, PVs, node counts, and TT stats.
Logs export to `.txt`; position collections save/load as versioned JSON. Python
3.10+ and Tkinter are required; some Linux installations need `python3-tk`.

Accepted moves are optional and may contain multiple alternatives. Any listed
legal move can pass; blank lists are analysis-only. Rust validates and normalizes
all accepted moves before search, including ambiguous capture identities.

FEN does not contain king-restriction counters or prior repetition history. The UI
shows this limitation and supports supplemental restrictions and replay moves.
Analysis runs in a subprocess outside Tk's event thread; Cancel stops the process
without recording a success verdict. Existing terminal play is unchanged.

```sh
python3 -m tools.position_suite run tools/position_suite/sample-suite.json --logs position-logs
python3 -m unittest discover -s tools/position_suite/tests -v
```

The CLI runner exports a text log per case and returns nonzero for failed or invalid
cases. See [position suite usage and case format](docs/position-suite.md).

The Rust library also exposes `Position::from_fen` and `to_fen`; the compiled
binary's `--analysis-json` mode provides the line-delimited JSON bridge. This
mode is separate from human terminal output and flushes every completed depth.

## Validation

The headless [Hub testbench foundation](docs/hub-testbench.md) provides a Hub v2
codec, subprocess session, Scan fixtures, and fake-engine compatibility tests.
Launch `frisian-draughts hub` for the Hub v2 adapter. It supports
initialization, board/history loading, depth-limited think/analyze searches,
progressive information and completion output, time/node limits, cooperative
stop, ping during search and pondering with a clock starting on ponder-hit.
Depth remains capped at 64, including infinite analysis (Hub permits early completion).

```sh
python3 -m unittest discover -s tools/testbench/tests -v
```

```sh
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Tests cover capture priority, orthogonal chains, promotion, blocked victims,
return-to-origin captures, ambiguous endpoints, restriction state, undo,
repetition, illegal input, terminal automation, and reproducible playouts. Search
tests compare alpha-beta with exhaustive minimax, replay principal variations,
check quiet sacrifices and forced exchanges, and reject a losing edge move.

An optional differential harness compiles a small adapter against the original
Scan source (requires Python 3 and g++):

```sh
git clone https://github.com/A9E4FF/scan.git /tmp/scan-reference
git -C /tmp/scan-reference checkout 7aae17e7b7bfc47744601afb1ee7655e18983ce5
python3 tools/differential.py /tmp/scan-reference
```

It compares complete resulting positions, king restriction counters, and legal
move sets on curated cases and seeded playouts, with no book, weights, or bitbase
loading. The expanded run matched **5,758 states**, including **1,991 capture
positions** and **526 king-restriction states** (seed 3101). CI runs the same checks. The reference source and binaries are not vendored.

### Bitboard regression and performance comparison

```sh
python3 tools/benchmark_bitboards.py --output /tmp/bitboard-results.json
cargo run --release --example movegen_bench
```

The comparison script builds an isolated archive of the pre-bitboard baseline,
runs both implementations three times, and requires identical moves, scores,
full principal variations, completed depths, and node counts at depths 4/6/8/10.
It also compares a seeded move-generation corpus and checksum. The coordinate
reference, geometry checks, and seeded full-state comparisons run under
`cargo test`; normal builds contain no reference generator or runtime switch.
See [bitboard benchmark results](docs/bitboard-benchmarks.md). The bitboard optimization preserved search policy, evaluation values, and terminal
commands. Historical bitboard comparisons explicitly disable the newer TT.

## Attribution and license

Rule behavior and padded board representation are adapted from **Scan 3.1**,
Copyright (C) 2015–2019 **Fabien Letouzey**, distributed under GNU GPL version 3.
Reference revision: `7aae17e7b7bfc47744601afb1ee7655e18983ce5` in
[A9E4FF/scan](https://github.com/A9E4FF/scan).
The Rust implementation and validation adapters are distributed under **GPL-3.0-only**;
see [license.txt](license.txt). No opening books or evaluation weight files are included.

