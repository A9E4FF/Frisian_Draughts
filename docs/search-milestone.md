# Search efficiency milestone

Base: PR #22 head 01d96b3303561301a13730d5a060f9e24736948a. Every source
file was verified against GitHub tree a96670d27c242c2c5d7d146825eace934e28f1ea.
PRs #17–21 merged within their feature stack. Main was at
98ec5ce7143b8106ab46463a20652a8ef6f7528d and PR #22 remained open.

## Frozen baselines

| File | SHA-256 |
| --- | --- |
| R0, shipped Frisian_Draughts.exe | 297206e0061d7c1ac3c29a28fc0941b4dcfdc2816fd2a0a861404196c41ee328 |
| Scan, shipped scan.exe | b995170a238b6bea47453a6038c53c4f2751ed78f2193162105e9a0bbc234bca |
| ScanGraphic 0.1.1 source archive | 4415091b6b7760db6473dcdeacf39842fc61537908019b6ce20e8fef08988307 |
| Original 24-start TXT | dc96c22be94367747a61ca8b973db6e1dc1138dd3c14d1f695a72c3a8cd1ce27 |

R0 source is supplied inside ScanGraphic-source.zip. The precise build
commit and compiler for the historical R0 binary are absent from BUILD.json.
Use the frozen binary for comparisons. Candidate builds use rustc 1.99.1
(58cf8f9c3, LLVM 23.1.1), cargo 1.99.1, x86_64-pc-windows-msvc and
`cargo build --release --offline --locked` with the default release profile.
Scan build flags and data digest are in the supplied BUILD.json.

## Corpus and runs

The version-1 GUI collections below tools/testbench/fixtures/search
preserve source FENs, ordered replay and explicit root king restrictions.
The six endgame candidates use Scan static evaluation for selection. Games
26 and 28 have correlated boards and are not independent samples. Scan's
tactical alternatives are diagnostic references only.

Run on a quiet machine, with one suite at a time:

```
cargo test --offline --locked
cargo build --release --offline --locked
python -m tools.testbench.search_benchmark ENGINE.exe NEW_BENCH_DIR --cap-ms 4000 --repeats 3
python -m tools.testbench.search_matches ENGINE.exe PREVIOUS.exe R0.exe SCAN.exe NEW_MATCH_DIR
```

The benchmark searches to depth 15 in one iterative run per repeat and
reports depths 10–15. A capped run only contributes iterations that
finished. Raw results retain the stop status and partial-work totals.
Opt-in analysis via `search_forced_root` reports completed scores even
when only one move is legal. Hub playing retains the fast shortcut.

The match runner uses the unchanged rules referee and verified shipped
Scan evaluation data. Keep Scan's scan.ini and data/ beside its EXE.
The fixed TT settings are 16 MiB for Rust and exponent 20 for Scan
(2^20 slots at 16 bytes each). The existing runner sets one thread,
disables books and bitbases, gives 50 ms Hub response margin, and
adjudicates at 200 plies. Results include W/D/L and a separate termination
tally. Each completed game is checkpointed before aggregate reporting.
