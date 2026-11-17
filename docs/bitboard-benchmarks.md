# Bitboard optimization benchmarks

## Method

Baseline: merged search revision `a5e74a24885518e8e355aab31d845ec68a2737c3`.
Candidate: the Scan-style bitboard implementation in this change. Both use the
same benchmark programs, search policy, evaluator values, and compiler profile.
Linux x86_64, AMD EPYC 9V74 shared host, Rust 1.100.0, one search thread.
Times below are medians of three runs with `cargo run --release`.
They are observations on this host, not response-time guarantees.

The comparison script checks all 16 position/depth combinations at depths
4, 6, 8, and 10. Selected moves, integer scores, completed depths, full principal
variations, total nodes, and quiescence nodes were identical in every run.
The speedup comes from cheaper operations per node, not a smaller search tree.

## Search measurements

| Position | Depth | Nodes (unchanged) | Before (s) | After (s) | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: |
| opening | 4 | 2,791 | 0.003543 | 0.000883 | 4.01× |
| opening | 6 | 22,175 | 0.029203 | 0.007001 | 4.17× |
| opening | 8 | 167,301 | 0.222856 | 0.060980 | 3.65× |
| opening | 10 | 1,366,303 | 1.835962 | 0.445144 | 4.12× |
| tactical | 4 | 1,705 | 0.002162 | 0.000543 | 3.98× |
| tactical | 6 | 10,357 | 0.012690 | 0.003580 | 3.54× |
| tactical | 8 | 115,850 | 0.143700 | 0.038056 | 3.78× |
| tactical | 10 | 1,836,397 | 2.210584 | 0.592745 | 3.73× |
| kings | 4 | 3,420 | 0.004613 | 0.001004 | 4.59× |
| kings | 6 | 37,678 | 0.034817 | 0.007226 | 4.82× |
| kings | 8 | 93,023 | 0.104331 | 0.019650 | 5.31× |
| kings | 10 | 540,357 | 0.791435 | 0.122571 | 6.46× |

The small `capture-combination` fixture also matched exactly. It terminates after
two plies and visits only 70 nodes at requested depth 10; microsecond timings
are too small to use as evidence of sustained performance.

## Move generation

The seeded corpus contains **1316 positions**, including opening-to-endgame
playouts and king fixtures. Each run makes **131,600 calls** and produces
**912,800 moves** with both implementations.

| Before (s) | After (s) | Speedup |
| ---: | ---: | ---: |
| 0.167778 | 0.036483 | 4.60× |

## Staged diagnostics

Local intermediate source variants isolated the main steps: set-bit iteration
plus mask-based evaluation (coordinate move traversal retained), then shift/table
man generation (coordinate king traversal retained), then the full ray-based king
generator. Every variant matched all benchmark outputs and corpus checksums.
These diagnostic timings are single runs, not the three-run medians above;
intermediate variants are not exposed as production options.

| Variant | Movegen (s) | Opening depth 10 (s) | Tactical depth 10 (s) | Kings depth 10 (s) |
| --- | ---: | ---: | ---: | ---: |
| Set-bit iteration + evaluation masks | 0.084770 | 1.080764 | 0.972434 | 0.175034 |
| Also optimize men | 0.032540 | 0.435462 | 0.577812 | 0.191104 |

## Reproduce and validate

```sh
python3 tools/benchmark_bitboards.py --repeats 3 --output /tmp/bitboard-results.json
cargo run --release --example movegen_bench
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
python3 tools/differential.py /path/to/pinned/scan
```

The benchmark script archives the pinned baseline in a temporary directory and
copies in the same benchmark drivers. It leaves the working checkout untouched
apart from Cargo build artifacts and writes individual samples when `--output`
is supplied. Both implementations use the default release profile. Search timing
includes any first-use geometry initialization; the movegen corpus warms geometry
before its timed loop. Geometry is initialized once through `OnceLock`.

The expanded Scan differential suite matched **5,758 complete states**, including
**1,991 capture positions** and **526 king-restriction states** (seed 3101).
All **40 Rust tests** pass. Test-only coordinate code checks ordered legal moves,
resulting states, evaluation, and search results; exhaustive geometry tests cover
all squares and directions. No square weights, search algorithms, move ordering,
or public API behavior were changed.
