# ScanGraphic / Frisian_Draughts 0.1.0

Extract the entire Windows ZIP and run `ScanGraphic.exe`. Python is bundled.
Keep both engines, `scan.ini`, `data/`, and `_internal/` in the extracted folder.

The **Analysis** tab is the original ScanGraphic interface, including its board,
tactics, pattern heatmaps, evaluation breakdown, evaluation graph and navigation.
The **Matches** tab uses the shared Hub match runner and the bundled Rust referee.
The supplied profiles are **Frisian_Draughts** and **Scan Graphic**.

1. In Matches, select both engines and choose depth, move time or Fischer clock.
2. Under Start positions, use **Add**, **Paste list**, or **Import TXT / FEN**.
   Text files use one FEN per line; blank lines and `#`/`;` comments are allowed.
   The legacy `FEN:` prefix and `start` keyword are accepted.
   **Add original tool list (6)** brings in the six saved positions from the old
   tool's `positions/positions.txt`. These contain extended fields: use **Use as
   fresh setups** explicitly to play their boards with cleared history. The full
   original FEN and conversion note remain in the collection and match reports.
3. Name, edit, reorder and check the entries to run. **Preview** validates the
   selected entry and displays it on the board. **Save collection** writes JSON;
   **Load collection** restores names, IDs, order, check states and history.
4. Each paired round runs both colors at every checked start. The displayed total
   is checked starts × paired rounds × 2 for the selected pair of engines.
5. Select a new report directory, then **Run paired matches**. **Stop matches**
   cancels safely; closing the window waits for cancellation before shutdown.

Reports include `manifest.json`, `games.json`, `results.csv` and `games.pdn`.
They retain start IDs/names, root FEN and replay history. The ply limit counts
newly played moves; `initial_moves` identifies the preceding history in JSON.
The default report location is under the user's `FrisianDraughtsResults` folder.

Use **Import PDN** or **Load games.json** in Matches to load games. Select a game
and **Open game in Analysis** to use the original Scan evaluation graph and ply
navigation. **Export PDN** writes all loaded or completed games. Imported PDN
comments, annotations and variations are retained; moves and branches are checked
with the rules referee before they are accepted. Match captures use Scan's
captured-square notation and explicit identity comments for lossless interchange.

A FEN alone starts with cleared repetition and king-move history. To preserve
history, enter canonical Hub replay moves from a known root. Explicit initial
king restrictions use the existing JSON schema, for example
`{"white":{"square":28,"count":2}}`. They require an engine advertising
`frisian-state-v1`; the supplied Scan build does not support importing these
counters, so use replay from a cleared root for Scan matches. Extended legacy
fields such as `:H0:F6:+0+0` are retained and rejected explicitly until converted.

## Build and validation

Install Rust stable, Python 3.12+ and MinGW g++. Supply the original modified
ScanGraphic source tree containing `src/`, `gui/`, `data/eval_frisian` and GPL
license files. No original local paths or binaries are required by the repository.

```powershell
cargo build --release --locked
python -m pip install -r tools/testbench/requirements-build.txt
python -m tools.testbench.build_scan_graphic --source C:\path\to\scan_31
```

The builder produces `dist/ScanGraphic-0.1.0-Windows-x64.zip`. Both engines,
third-party licenses, exact corresponding sources, evaluation data and checksums
are included. `ScanGraphic-source.zip/BUILD-SOURCE.txt` describes rebuilding from
the shipped source archive. `BUILD.json` records version and SHA-256 hashes.

Run the packaged regression smoke with a new output directory:

```powershell
ScanGraphic.exe --smoke-test --smoke-output C:\temp\scan-smoke
```

It checks original Scan search, evaluation and patterns; sixteen real Scan/Rust games
across white/black starts and all six original saved positions; PDN reimport; and original game analysis/navigation.
The manual GitHub workflow accepts an accessible source-archive URL and SHA-256
to reproduce the package without committing Scan's evaluation data to Git.
