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
