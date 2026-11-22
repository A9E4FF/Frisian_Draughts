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

## Recorded Windows validation

Three serial repeats per build, capped at 4 seconds per position and repeat.
Entries give the median cumulative milliseconds and nodes from the completed
iteration. The JSONL and summary files preserve min/max and iteration counters.

| Position and depth | Corpus build | Compact TT | Move ordering | PVS |
| --- | ---: | ---: | ---: | ---: |
| Opening D12 | 1705.1 / 5,650,098 | 641.3 / 2,252,232 | 256.3 / 1,081,241 | 240.4 / 1,017,918 |
| Tactical D12 | 2568.9 / 7,641,997 | 1440.7 / 4,469,471 | 919.9 / 3,381,834 | 622.7 / 2,357,205 |
| Closed D10 | 362.3 / 1,186,419 | 98.3 / 319,336 | 37.2 / 136,459 | 36.2 / 132,976 |
| Kings D12 | 182.4 / 756,010 | 58.7 / 286,645 | 69.5 / 394,080 | 35.2 / 170,978 |
| Opening D15 | capped | capped | 3000.9 / 12,395,192 | 2248.5 / 9,492,901 |
| Closed D15 | capped | capped | 2722.0 / 9,730,713 | 2486.7 / 9,526,809 |
| Kings D15 | capped | 738.9 / 3,388,452 | 360.9 / 1,888,507 | 268.7 / 1,284,224 |

The tactical fixture reached D14 with PVS and capped before D15 in all
builds. PVS increased closed-position D12 work from 636,137 to 705,737
nodes and the median from 171.8 to 186.7 ms, then lowered both at D15.
At opening D12 cost per million nodes was about 302, 285, 237 and 236 ms
across the four builds. Most of the measured gain came from fewer nodes.

| Build | Source commit or PR | Executable SHA-256 |
| --- | --- | --- |
| Corpus | b5190adb941fc8c687d0d9cc536667eda146a6b0 | 52805eff1b35a998c4b3cb48bd2e4cc7fa543bfce2770707cbc470d04d052a06 |
| Compact TT | 66e22c474a956b741c3452b54efe311a38f7b34b | 18360d88bf0a2f50c4184d1764d4f02d55ca34e11c8755ffd68b6352a5381b52 |
| Move ordering | 6940a74a69c468596b24eb42736cab6eea4508a4 | 827e875e0481ad1f4ad2dd6a9f10887585e55d4f84d113a2e65af52c368703a4 |
| PVS | Final milestone PR | 10805a88536d4a90c13955af624fa3015ee4ad52fc4e7b3372557dafb35fb671 |

The four builds agreed with their preceding baseline on shallow scores across
40 fixtures and their PVs replayed with root history. The instrumentation
build also matched frozen R0 move, PV, and counters there. Each build passed
the Rust suite, the two Python/Qt suites (three optional skips combined), and
the retained ScanGraphic GUI's 16-game smoke with PDN replay. The separate
pinned C++ differential job runs in GitHub CI.

Historical Scan matches with frozen R0 yielded 3/3/42 W/D/L at fixed
depth 10 and 0/0/48 at 100 ms. Those are baseline investigations. The
new serial match matrix is recorded independently with its own manifests
and game checkpoints. Keep timed match strength conclusions provisional.

## Milestone 2

Retain this corpus and the four binaries. Use the three tactical audits and
six endgame candidates to validate bounded quiet-threat or sacrifice
extensions and phase-aware positional/endgame evaluation. Keep extensions
and evaluation separate, and treat the correlated endgames accordingly.
Run late-move reductions as a later isolated experiment.
