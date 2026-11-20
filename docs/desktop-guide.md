# Frisian Draughts Testbench

## Windows quick start

Extract the entire desktop ZIP into a writable folder. Keep the executable,
`_internal` directory and `engines` directory together. Double-click
`FrisianDraughtsTestbench.exe`. Python and Rust are not required on the target
computer. The included Rust engine is also the rules referee. Scan is selected
separately; its weights, books, bitbases and executable are not redistributed.

1. Choose **Add engine**, name it Scan and browse to `scan.exe`.
2. Keep arguments `["hub"]`. Set the working directory to Scan's folder, so its
   data files can be found. Parameters are an optional JSON object.
3. **Test Hub** verifies initialization. Save profiles to reuse the setup.
4. In **Matches**, select Rust and Scan. Depth defaults to **12**, one paired
   round and one simultaneous game. A paired round plays both colors.
5. Set a new report directory. Existing directories are never overwritten.
6. Start the matches. The board, thinking engine, completed depth/score/PV and
   results update live. Cancel stops active work and records unfinished games.

The 300-second GUI response watchdog is separate from a playing clock and can
be changed. The CLI retains its 60-second default. Choose Move time or Fischer
clock for time-based comparisons. Engine parameters are applied after default
Frisian mode, one thread, book off and bitbases off; inspect overrides carefully.
Nominal depth is not equivalent playing effort across different search engines.
Repeated rounds from a deterministic starting position may repeat games.

## Analysis and position cases

Preview/import a FEN, set depth and analyze. Replay moves and explicit initial
restriction JSON preserve state unavailable in FEN alone. Setup editing starts
a new position and clears history. Legal moves can be selected explicitly;
ambiguous endpoint drags are refused. Import/save version-1 suites and run a
selected case or all cases. Blank expected moves mean analysis-only, not pass.
Unsupported restriction/TT settings are reported, never silently dropped.

## PDN and replay

Open `games.json` for exact canonical match replay, or **Import PDN** to load a
multi-game collection. Select a game using players/event/result. Bad games stay
visible with errors; other games remain usable. The slider replays full history
through the referee. Comments, NAGs and variations are preserved and shown.
**Analyze this position** analyzes the selected ply with its earlier history.

Export one/all games. Imported documents preserve their original annotations
and notation. Generated games offer standard capture landing paths or **Scan
captured squares**, the dialect used by the supplied ScanGraphic GUI. Exports
retain exact identities in `[%hub ...]` comments; third-party readers may ignore
these, so select their appropriate dialect. Match `games.pdn` uses Scan notation.
Analysis export inserts a clearly labeled engine comment while preserving the
original imported annotations. Arbitrary initial king counters cannot be stored
in ordinary PDN: retain the JSON position case or canonical report instead.

Reports include JSON, CSV, PDN and executable hashes/configuration. A move cap is
an adjudicated draw, not a rules proof. Timeout/crash/illegal move are separately
identified forfeits. Referee failures/cancellation are unfinished `*` results.
Raw transcripts are bounded diagnostics; canonical move history is complete.

## Development

```powershell
python -m pip install -r tools/testbench/requirements-build.txt
cargo build --release --locked
python -m tools.testbench.gui
python -m tools.testbench.build_desktop
```

Qt tests use `QT_QPA_PLATFORM=offscreen`, `FRISIAN_QT_TESTS=1`, and
`FRISIAN_TEST_ENGINE` pointing at the built engine. CI tests the packaged program
with `--smoke-test --smoke-output NEW_DIRECTORY`, including real paired matches
and PDN replay. Existing CLI, Tk position suite and engine modes remain available.
See `BUILD.json`, `SOURCE.txt`, `SHA256SUMS.txt`, `NOTICE.md` and `license.txt` for
the build provenance and attribution. The new PR stack merges in order 1–5.
