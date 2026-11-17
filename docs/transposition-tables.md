# Transposition tables

The engine now uses a fresh bounded transposition table for each search. The table
is shared across iterative-deepening passes within that search, not across games
or independently loaded FEN positions. The evaluator and legal rules are unchanged.

## Contents and controls

Each entry stores a deterministic Zobrist key, a full `Position` for collision
verification, remaining depth, normalized score, exact/lower/upper bound, generation,
and a complete move line including captured sets. Four-entry clusters replace
older entries first and prefer shallow entries within the same generation.

The default budget is **16 MiB**. `SearchLimits::with_tt_enabled(false)` preserves
the uncached search baseline; `with_tt_megabytes(n)` accepts **1–256 MiB**.
The budget includes worst-case payload reservation for every slot: boxed lines
are capped at 128 moves and slot count is rounded down. Actual allocation is
usually smaller; allocator overhead is outside the nominal payload budget.
Longer lines are not cached. No unsafe code or shared-table threading is involved.

Zobrist keys include every piece, the side to move, and both active king restrictions
(square and count). A hash hit alone never authorizes reuse: full position equality
is checked. Cached moves remain full moves, not ambiguous from/to-only indices.
Scores in the terminal range are converted between root-relative and
position-relative distance before storage/probing. Quiescence is not cached.

## Repetition safety and fixed-depth semantics

A board-only table cannot safely reuse every score because repetition depends
on the game and search path. This version deliberately uses a conservative rule:

- Reuse a score only if **both** stored and current contexts are clean: the initial
  position has no predecessor history, or the immediately preceding move was a
  man move or capture.
- All previous positions before that irreversible conversion are unreachable:
  material cannot be restored, men cannot move backward quietly or demote, and
  a move changes which side is to move. The current position is therefore the
  only relevant predecessor for future repetition detection.
- At reversible king-history nodes, the table is used for move ordering only.
  Threefold repetition is checked before probing, with full restriction state.
- Score reuse requires **equal remaining depth**, rather than allowing a deeper
  result to substitute for shallower fixed-depth minimax. Other depths may still
  supply an ordering move.

This reduces cache opportunities in long king-only lines, but avoids claiming
that a result calculated with different repetition counts is universally exact.
A later implementation could verify and cache complete repetition contexts.

The previous iteration's PV remains first in move ordering; the table move is
next when different. Bound cutoffs return the cached legal line, so reported
principal variations remain replayable. Equal-valued best moves can change when
ordering changes; score equivalence is the correctness target.

## Search reports

`search_with_reporter(game, limits, callback)` reports each completed depth with
cumulative nodes, quiescence nodes, elapsed time, and `tt_probes`, `tt_hits`, and
`tt_cutoffs`. It reports terminal and sole-move fast paths once at depth zero.
A forced move remains immediate and has no fabricated searched score. Existing
`search` delegates to this interface with a no-op callback.

## Validation and measurements

```sh
cargo test
cargo clippy --all-targets -- -D warnings
cargo run --release --example tt_bench
```

The benchmark compares TT on/off scores at depths 4/6/8/10 and replays every
reported PV. Tests additionally cover forced hash collisions, bound conditions,
terminal-distance normalization, memory controls, replacement, same-board/different
histories, callback events, and seeded uncached-score comparisons.

Single-run release observations on the shared Linux x86_64 AMD EPYC 9V74 host,
Rust 1.100.0, default 16 MiB budget:

| Position, depth 10 | Nodes without TT | Nodes with TT | Seconds without | Seconds with | Hits / cutoffs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Opening | 1,366,303 | 719,962 | 0.402720 | 0.247134 | 10,836 / 8,087 |
| Tactical | 1,836,397 | 1,028,711 | 0.551189 | 0.340578 | 19,205 / 15,702 |
| Kings | 540,357 | 115,778 | 0.108743 | 0.026147 | 27,648 / 3,741 |

All paired scores matched. These fixtures show reduced work, not a universal
speedup guarantee. Zobrist recomputation, full-position checks, PV storage, and
conservative history/depth restrictions add overhead. Performance depends on
position, table budget, machine load, and compiler settings. The historical
bitboard comparison must run with TT disabled when checking unchanged node counts.
