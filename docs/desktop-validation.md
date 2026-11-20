# Desktop validation

Local Windows checks on 2026-11-20:

- 54 testbench tests, including Qt controls/lifecycle, real engine/referee tests,
  PDN syntax and annotation round trips, standard/Scan capture dialects, replay,
  analysis comments, metadata preservation and cancellation. The optional
  original Scan GUI parser test also passed when its source path was supplied.
- Original position-suite tests: 17 tests, one display-only Tk test skipped.
- Two depth-12 Rust–Scan games driven through the Qt desktop, colors swapped,
  one game at a time, 80 plies each, 300 s watchdog. Both ended at the explicit
  adjudication cap. Total elapsed about 210 s. All moves replayed through the
  referee; this is integration evidence, not a strength estimate.
- Visual inspection of the offscreen Windows UI. Added a fallback for offscreen
  systems with an empty font database, loading installed Windows fonts without
  redistributing them.

Local tests use the existing release executable. CI rebuilds Rust from the
committed lockfile, retains the independent Scan differential tests, runs Qt
tests on Windows/Linux, builds the standalone Windows application and performs
a packaged two-game/PDN smoke test. Its artifact contains build versions, source
revision and executable checksums. CI results are the release gate.
