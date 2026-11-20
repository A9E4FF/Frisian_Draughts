# ScanGraphic companion release and Hub launch fixes

The reported Scan crash was reproduced with a profile that omitted its working
directory. Scan exited with `unable to open file "scan.ini"`. Hub launch now
defaults to the executable directory, or its parent when a development `src/`
build has `scan.ini` one level above. An explicit working directory takes
precedence. Startup errors retain stderr, exit code and effective directory.
Profile browsing fills in the inferred directory so the setting is visible.

FEN import is under **Analysis → Paste / import FEN** or **Load FEN file**.
Editing Starting FEN and pressing Preview remains supported. Import clears the
previous setup's history/counters/expected moves and validates through the rules
referee before updating the board.

## Companion graphical Scan

`build_scan_graphic` builds a separate ScanGraphic Windows application from an
explicitly supplied source tree. No Scan binaries or pattern weights are added
to this Rust repository. It compiles the copied C++ sources, packages the
provided analysis GUI, and includes `scan.ini`, the required Frisian evaluation
data, GPL license, build hashes and a corresponding source archive. The legacy
GUI's asynchronous startup handshake is corrected in the staged copy; original
source folders are not changed.

```powershell
python -m tools.testbench.build_scan_graphic --source C:\path\to\ScanGraphic\scan_31
```

Extract the complete ScanGraphic ZIP and run **ScanGraphic.exe**. For the unified
testbench, choose **Add engine**, select the companion **scan.exe**, keep
arguments `["hub"]`, and enable ScanGraphic diagnostics if desired. Its engine
is Frisian-only in this distribution, one thread, book and bitbases disabled;
the original pattern evaluator is included. This does not change Rust's
evaluation or add weights to Rust.

Validation: 58 local testbench tests with Qt and real engines (optional external
parser check skipped), including Scan without explicit cwd, stderr diagnostics,
FEN reset/import, plus the earlier corpus. The rebuilt Scan passed Hub search.
The standalone ScanGraphic smoke reported ready, progressive search information,
evaluation decomposition, pattern data and a legal selected move.
