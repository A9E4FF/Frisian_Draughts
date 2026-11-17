# Initial Analysis: Adapting Scan to Rust for Frisian Draughts

## Scope and conclusion

Reference: A9E4FF/scan, Scan 3.1, commit `7aae17e7b7bfc47744601afb1ee7655e18983ce5`. This is a static source review, not a Rust implementation or a performance measurement. Future implementation belongs in A9E4FF/Frisian_Draughts. This report records the initial planning review; the first implementation intentionally defers search algorithms.

Scan is a strong architectural reference for a Rust engine: iterative deepening, negamax alpha-beta/PVS, capture-aware quiescence, transposition tables, history ordering, selective extensions, and reductions are directly applicable. The greatest correctness risk is the Frisian game-state and move-generation layer beneath search. Start with a deterministic, single-threaded engine and add selective search incrementally. Defer opening books, imported pattern weights, bitbases, and Scan's split-point parallelism.

## Search algorithms observed

| Component | Scan behavior | Rust recommendation |
| --- | --- | --- |
| Iterative deepening | Searches depth 1 onward; updates root ordering and time allocation | Port early; keep the last fully completed iteration as the reliable interrupted-search result |
| PVS | Later PV moves and reduced moves receive a narrow-window search; improvements trigger a full-depth/full-window re-search | First validate plain negamax alpha-beta; add PVS with equivalence tests |
| Aspiration windows | From depth 4, surrounds the preceding evaluation with a margin of 20 for Frisian; doubles the failed side and eventually falls back to a full window | Add after PVS; retune margins for the chosen evaluator's scale |
| Move ordering | TT move index first, then adaptive history indexed by from/to; stable sorting | Start here; do not assume Scan uses killer-move tables |
| Transposition table | Four-entry clusters, 16-byte entries, 32-bit lock, depth/age replacement, lower/upper/exact bounds | Begin with an explicit valid flag and full key; optimize layout after correctness |
| Extensions | One extra ply for a single legal move; singular extension at qualifying PV nodes of depth at least 8 | Add forced-move extension first, with a separate absolute ply limit |
| Late move reductions | Quiet, non-promoting moves at depth at least 2; reduction of 1 or 2 depending on move index and node type | Enable only after tactical tests; captures and promotions must remain exempt |
| Forward pruning | Non-PV nodes at depth at least 3: searches the same position at about 40% depth against beta plus depth times 10 | Treat as a selective reduced-depth verification heuristic, not null-move pruning; defer and measure tactical failures |
| Singular verification | Searches alternatives while excluding the TT candidate, at depth minus 4 and a threshold below its score | Preserve exclusion semantics and separate TT keys; resolve candidate ambiguity before porting |
| Distance scores | Win/loss scores depend on search ply; TT store/probe normalizes them | Port and test independently from ordinary evaluation scores |

Sources: `src/search.cpp:294`, `:953`, `:1028`, `:1239`, `:1299`, `:1406`; `src/sort.cpp`; `src/tt.cpp`; `src/score.cpp`. Source locations refer to the pinned revision.

The forward-pruning code increments its search-ply argument without making a board move. Do not silently equate search ply with game-history length. It also disables the pruning flag in the reduced verification search. Do not import chess null moves: passing is illegal and forced captures and zugzwang make the assumption particularly risky here.

## Quiescence is a priority

Scan generates legal captures first and searches them without stand pat. Only positions without captures receive static evaluation. At the first quiescence level, an opponent capture threat triggers a one-ply full search with forward pruning disabled. At quiet, kingless, non-threat positions it can additionally explore selected sacrifices through `add_sacs`.

For Rust, implement mandatory-capture quiescence first. Then validate threat extension. Defer `add_sacs`: its patterns in `gen.cpp` use diagonal relationships, whereas Frisian captures also use orthogonal relationships. That does not establish a Scan bug, but it makes blind reuse a poor foundation for Frisian-specific tactical coverage. Audit no-legal-move terminals explicitly at the quiescence boundary; “no capture” does not itself mean “nonterminal.”

## Frisian correctness requirements

1. **Eight capture directions, diagonal quiet moves.** `bit.cpp:34` builds diagonal movement tables but adds orthogonal capture directions for Frisian. Men capture backward as well as forward; kings scan rays. Keep a simple coordinate-based generator as an independent test oracle for the optimized bitboards.
2. **Capture priority is legality.** `List::add_capture` ranks sequences with `64 * captured_men + 126 * captured_kings + capturing_king`. Only maximal-ranked captures remain legal. This is not an evaluation term or an ordering preference. Preserve its behavior first, then verify rule wording and composition limits before replacing it with a simplified ratio.
3. **Multi-capture occupancy matters.** The generator removes jumped pieces from the remaining capturable set while leaving them outside the empty-square set during the sequence. Preserve blocking, landing-square choices, duplicate handling, and return-to-origin captures. A move needs the captured set, not just start and destination.
4. **Promotion follows the completed move.** Scan applies promotion from the final destination in `Pos::succ`; capture recursion retains the original moving-piece behavior. Include passing through and finishing on promotion rows in tests.
5. **King restriction state belongs in the position.** Scan tracks each side's last restricted king square (`wolf`) and consecutive quiet-move count while men remain. The fourth quiet move by that king is suppressed, but captures remain eligible. Moving another king, conversion moves, loss of a tracked king, and disappearance of the last man affect state maintenance. Port the exact transitions in `pos.cpp:53` and test them.
6. **Equality and hashing include restriction state.** Scan includes wolf/count in both position equality and its Zobrist key. Identical piece layouts can have different legal moves. A board-only hash is insufficient.
7. **History is separate from board state.** Scan search uses twofold repetition as a draw heuristic, while game termination uses threefold. History scanning resets after a man move or capture. Document this distinction; verify intended competition draw rules separately. Avoid storing path-dependent repetition results as unconditional exact TT values.
8. **Position notation loses history.** Scan's FEN/Hub board parsing reconstructs pieces and side to move, resetting restriction counters. For tests of those counters, replay moves or supply a richer internal fixture containing the full position and history.

Sources: `src/gen.cpp`, `src/list.cpp:24`, `src/pos.cpp:53`, `:107`, `:136`, `src/hash.cpp:87`, `src/fen.cpp`.

## Rust architecture

Use modules `board`, `rules/frisian`, `movegen`, `position`, `history`, `hash`, `search`, `tt`, `eval`, and `protocol`. Keep the recursive search independent of terminal I/O and mutable global configuration. A Frisian-only first version avoids repeatedly branching on a runtime variant in hot paths.

- Use `u64` bitboards, initially retaining Scan's padded square mapping (50 playable squares within 63 indices). A dense 0–49 mapping would require different shift and ray logic.
- Represent a position as a small value type containing piece masks, side to move, and both restriction states. Begin with copy-and-apply transitions; benchmark before considering mutable make/unmake.
- Use an explicit move type with source, destination, and captured mask, or a validated packed equivalent. Scan's TT/history index stores only source/destination; distinct captures can share it. Full move matching is preferable for singular exclusion and PV reconstruction.
- Replace parent pointers with a stack/vector of prior states or keys and an irreversible-move boundary. Distinguish search-stack ply, game history, and remaining search depth. Depth must support reductions below zero.
- Own history statistics, PV buffers, and counters in a `SearchContext`; pass mutable context through recursion without retaining borrows into its buffers across recursive calls.
- Start with safe storage and checked move-buffer growth. Scan's fixed list capacity of 128 and sentinel sort should not become an unchecked Rust assumption.
- Use immutable precomputed geometry and portable `count_ones`/`trailing_zeros`. Validate nonzero bitboards before bit extraction and use signed coordinates before checked shift/index conversion.
- Propagate cancellation explicitly and poll node/time limits. An interrupted search is not a valid numeric score and must not publish an exact TT result.

For parallel search, begin later with independent worker state and a synchronized TT, or a carefully designed atomic entry protocol. Scan shares ordinary TT/history storage across workers; a direct translation through `static mut` or unchecked interior mutability is inappropriate. Lazy SMP is a candidate alternative to its pointer-heavy split-point scheduling, but requires benchmarks and is not guaranteed faster.

## Evaluation and deferred assets

A small side-to-move material evaluator is enough to validate search mechanics. Add basic mobility, promotion prospects, and king-restriction penalties only as explicit follow-up features. Do not use the capture-priority formula as the positional value of pieces. Preserve bounded evaluation scores outside the reserved terminal-score range.

Search quality still depends on leaf evaluation: a Rust engine with material-only evaluation cannot be claimed to match Scan's playing strength. Likewise, Scan's aspiration/pruning margins are not portable constants if the score scale changes. Keep books disabled and bitbases absent for baseline comparisons. Pattern weights and their file format can be considered after tactical correctness and search instrumentation.

## Staged implementation and evidence

1. **Rules baseline:** position/move types, complete legal moves, transitions, restriction state, notation/replay, terminal and repetition policies. Gate: curated edge cases plus differential legal-move sets and perft/divide against an instrumented Scan. No perft totals are asserted by this review.
2. **Deterministic search:** single-thread alpha-beta, capture quiescence, simple evaluator, iterative deepening, PV and cancellation. Gate: exhaustive shallow minimax agreement using the same evaluator and terminal rules.
3. **Search efficiency:** Zobrist TT, history ordering, PVS, aspiration. Gate: score equivalence to the baseline at fixed depth with selectivity disabled; valid replayable PVs; terminal-score normalization and TT-bound tests. Best moves may differ when tied.
4. **Selective strength:** forced and singular extensions, LMR, threat extension, then forward pruning and optional sacrifice search individually. Gate: tactical-suite regressions, node counts, re-search rates, and controlled match results. Selective configurations need not match exhaustive fixed-depth scores.
5. **Parallelism and tuning:** worker design, TT concurrency, time management, evaluator refinement. Gate: elapsed-time scaling, memory and cancellation behavior, and statistically meaningful matches.

Include tests for orthogonal chains, priority ties, equal endpoints with different captured sets, captured-piece blocking, king-count reset/preservation, full-state hash differences, repetition histories, and blocked-side terminals. Use property tests for piece disjointness, material changes, incremental-versus-recomputed hashes, and legal move replay.

Measure nodes and wall-clock time together on fixed hardware, compiler profiles, TT size, evaluator, and position corpus. Disable books, random selection, and bitbases. Rust-versus-C++ speed and playing-strength estimates require implementation and measurement; this review establishes neither.

## First milestone

The first useful deliverable in Frisian_Draughts is a safe, single-threaded Rust rules core plus deterministic alpha-beta/capture-quiescence search, a minimal evaluator, and a reproducible differential test harness. Porting all of Scan's selectivity or its trained assets before that baseline would make failures substantially harder to localize. Preserve Scan attribution and review GPLv3 obligations when translating its code.
