# Unified desktop delivery

Base: `feature/hub-stage-2-adapter`, containing the merged stages 2–5. The new
stack has five review steps: shared orchestration/PDN, profiles and controls,
worker lifecycle, analysis/cases/replay/PDN workflows, and Windows packaging.
Do not merge the stack directly onto an older main without its prerequisites.

The CLI and desktop use `run_tournament` and `play_game`. Progress events contain
game identity, board snapshots, thinking/search information and final results.
Cancellation yields unfinished games and preserves reports. Fixed-depth response
watchdogs are configurable separately from clocks.

PDN documents retain tags, comments, NAGs and nested variations. Validation
replays every branch through the referee. Individual malformed games remain in
the document with errors; later games are still accessible. Both standard landing
paths and unambiguous Scan capture identities are accepted. Project exports
include `[%hub ...]` comments to preserve exact capture identities. Importers
which ignore these comments may still need capture disambiguation. Ordinary PDN
cannot reconstruct arbitrary initial restriction counters; use canonical JSON
for such states. Never silently reset counters on PDN export/import.

## PDN and replay workspace

Import PDN lists every game, including malformed games labeled `[ERROR]`.
Choose a game and use the replay slider; mainline annotations and variations
remain visible. Analyze this position reconstructs the selected ply's history.
Export game/all preserves imported annotations and notation. Newly generated
games can export standard landing paths or Scan's captured-square dialect.
Choose Scan notation for the supplied ScanGraphic GUI. Standard paths are
reconstructed from a referee-validated move, not by treating captured squares
as intermediate landings. Explicit capture comments remain for exact identity.

Export analysis PDN adds a clearly labeled engine comment at the analyzed ply,
retaining original annotations and variations when the game was imported.
Scores specify men and side-to-move perspective. Arbitrary initial king counters
cannot be exported faithfully in ordinary PDN; keep the versioned JSON case.
Position-suite load/edit/save preserves TT fields and other case metadata.
