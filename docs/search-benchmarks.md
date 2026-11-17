# Initial search benchmarks

Measured in a Linux x86_64 cloud workspace on an AMD EPYC 9V74 host using Rust
1.100.0, `cargo run --release --example search_bench`, and one search thread.
These are single-run wall-clock observations on a shared host, not timing guarantees.
Node totals include quiescence and all iterative-deepening passes; no book,
external weights, bitbases, or transposition table are loaded.

## Results

| Position | Depth | Nodes | Quiescence nodes | Seconds | Score | Move |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| opening | 4 | 2791 | 2561 | 0.003685 | 0 | 34-30 |
| opening | 6 | 22175 | 19742 | 0.028147 | 0 | 34-30 |
| opening | 8 | 167301 | 143286 | 0.220199 | 0 | 32-27 |
| opening | 10 | 1366303 | 1164086 | 1.758173 | 0 | 32-27 |
| tactical | 4 | 1705 | 1490 | 0.001843 | -508 | 14-20 |
| tactical | 6 | 10357 | 8744 | 0.011149 | -504 | 14-20 |
| tactical | 8 | 115850 | 98225 | 0.119695 | -504 | 14-20 |
| tactical | 10 | 1836397 | 1567413 | 1.959397 | -508 | 14-20 |
| kings | 4 | 3420 | 2879 | 0.003993 | -2 | 1-7 |
| kings | 6 | 37678 | 31287 | 0.031017 | -6 | 1-29 |
| kings | 8 | 93023 | 65750 | 0.106556 | -8 | 1-29 |
| kings | 10 | 540357 | 381221 | 0.746875 | -4 | 1-29 |

## Reproduction and interpretation

```sh
cargo run --release --example search_bench
# Run only one fixture:
cargo run --release --example search_bench -- tactical
```

Fixtures are defined in the benchmark example: the standard opening, a 29-man
middlegame featuring a quiet sacrifice and forced exchanges (Black to move), and
a four-piece king/man position retaining the Frisian king restriction. Each depth
starts a fresh search and includes all iterations from depth 1. There is no time
cutoff. Exact moves and node counts should reproduce on this revision; elapsed
time depends on the machine and load.

The example also includes `capture-combination`, an ambiguous-endpoint capture
fixture that resolves into a forced loss after two plies. It visited only 70 nodes
at requested depth 10 (10 quiescence nodes, approximately 0.000027 seconds).
That early terminal result is a rules/tactics check, not evidence of deep search
performance. Full-state fixture definitions are kept in source for reproduction.

Depth 10 covers roughly five moves by each side, plus mandatory capture tails.
These measurements neither establish playing strength nor demonstrate detection
of positional errors 10–15 full moves ahead. More varied king positions may be much
more expensive. The evaluator's edge bonuses remain experimental; the regression
suite includes an edge move that loses to an orthogonal capture and is rejected.
