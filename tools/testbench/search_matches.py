"""Serial, color-swapped search milestone matches over the maintained user starts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from . import start_positions
from .matches import Entrant, MatchLimits, run_tournament
from .referee import Referee
from .search_benchmark import CORPUS
from .session import EngineProfile


def main(argv=None):
    path = lambda p: Path(p).resolve(strict=True)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidate", type=path)
    ap.add_argument("previous", type=path)
    ap.add_argument("r0", type=path)
    ap.add_argument("scan", type=path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--move-ms", type=int, choices=(100, 1000), action="append")
    ap.add_argument("--case", action="append", help="Limit to specified opening IDs for smoke testing")
    args = ap.parse_args(argv)
    starts = start_positions.load(CORPUS / "user-starts.json")
    if args.case:
        starts = [s for s in starts if s["id"] in args.case]
        if {s["id"] for s in starts} != set(args.case):
            ap.error("Unknown user start ID")

    def hash_binary(binary):
        return hashlib.sha256(binary.read_bytes()).hexdigest()

    def entrant(name, binary, tt_size):
        return Entrant(name, EngineProfile(str(binary), cwd=str(binary.parent)), {"tt-size": tt_size})

    args.output.mkdir(parents=True, exist_ok=False)
    candidate = entrant("candidate", args.candidate, 16)
    referee = Referee(str(args.r0))
    seen = {hash_binary(args.candidate)}
    for name, binary, size in (("previous", args.previous, 16), ("r0", args.r0, 16), ("scan", args.scan, 20)):
        digest = hash_binary(binary)
        if digest in seen:
            print(f"Skip duplicate {name} ({digest})", flush=True)
            continue
        seen.add(digest)
        opponent = entrant(name, binary, size)
        for ms in args.move_ms or (100, 1000):
            run = args.output / f"{name}-{ms}ms"
            run.mkdir()
            tally = Counter()
            causes = Counter()
            with (run / "checkpoint.jsonl").open("w", encoding="utf-8") as stream:
                def progress(event):
                    if event["type"] != "game-finished":
                        return
                    game = event["record"]
                    stream.write(json.dumps(game) + "\n")
                    stream.flush()
                    causes[game["termination"]] += 1
                    result = game["result"]
                    if result in ("1-0", "0-1"):
                        winner = game["white" if result == "1-0" else "black"]
                        tally["win" if winner == "candidate" else "loss"] += 1
                    else:
                        tally["draw" if result == "1/2-1/2" else "unfinished"] += 1
                    print(name, ms, event["game"], event["total"], result, game["termination"], flush=True)
                run_tournament([candidate, opponent], referee, MatchLimits(move_time=ms / 1000),
                               positions=starts, parallel=1, output=run / "reports", on_event=progress)
            summary = dict(results=tally, terminations=causes)
            (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
