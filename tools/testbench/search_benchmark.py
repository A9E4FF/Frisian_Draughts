"""Serial Rust analysis benchmark. Run with a release executable."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess

from . import start_positions

CORPUS = Path(__file__).with_name("fixtures") / "search"
DEFAULT_CASES = (
    "user-start-01",
    "audit-game-37-ply-8",
    "performance-depth13-game-2-ply-32",
    "benchmark-kings",
)
COUNTERS = ("nodes", "quiescence_nodes", "elapsed_ms", "tt_probes", "tt_hits", "tt_cutoffs")
METRICS = (*COUNTERS, "nps", "quiescence_share")


def corpus():
    result = {}
    for path in sorted(CORPUS.glob("*.json")):
        for item in start_positions.load(path):
            if item["id"] in result:
                raise ValueError(f"Duplicate corpus ID {item['id']}")
            result[item["id"]] = item
    return result


def analyze(engine, item, depth, cap_ms, tt_mib, *, forced_root=True, tt_enabled=True):
    item = start_positions.prepare(item)
    request = {field: item[field] for field in ("fen", "moves", "restrictions")}
    request.update(depth=depth, time_limit_ms=cap_ms, search_forced_root=forced_root,
                   tt_enabled=tt_enabled, tt_megabytes=tt_mib)
    try:
        process = subprocess.run(
            [str(engine), "--analysis-json"], input=json.dumps(request) + "\n",
            capture_output=True, encoding="utf-8", check=True,
            timeout=cap_ms / 1000 + 15,
        )
    except subprocess.TimeoutExpired:
        return [], {"status": "process_timeout", "depth": None}
    events = [json.loads(line) for line in process.stdout.splitlines()]
    if not events or events[-1]["type"] != "result":
        raise RuntimeError(f"{item['id']}: {events}")
    iterations = []
    previous = dict.fromkeys(COUNTERS, 0)
    for event in events:
        if event["type"] != "iteration" or event["status"] != "completed":
            continue
        delta = {key: event[key] - previous[key] for key in COUNTERS}
        event["iteration"] = delta
        for row in (event, delta):
            row["nps"] = row["nodes"] * 1000 / row["elapsed_ms"] if row["elapsed_ms"] else None
            row["quiescence_share"] = row["quiescence_nodes"] / row["nodes"] if row["nodes"] else None
        iterations.append(event)
        previous = event
    return iterations, events[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("engine", type=lambda p: Path(p).resolve())
    ap.add_argument("output", type=Path)
    ap.add_argument("--case", action="append")
    ap.add_argument("--depth", type=int, default=15)
    ap.add_argument("--min-depth", type=int, default=10)
    ap.add_argument("--cap-ms", type=int, default=20000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--tt-mib", type=int, default=16)
    args = ap.parse_args(argv)
    if not 1 <= args.min_depth <= args.depth <= 64 or min(args.cap_ms, args.repeats) < 1:
        ap.error("Require valid depths, positive cap and at least one repeat")
    cases = corpus()
    selected = args.case or DEFAULT_CASES
    if missing := sorted(set(selected) - cases.keys()):
        ap.error(f"Unknown case IDs: {missing}")
    samples = defaultdict(list)
    metadata = dict(engine=str(args.engine), sha256=hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                    cap_ms=args.cap_ms, repeats=args.repeats, tt_mib=args.tt_mib, depth=args.depth)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "runs.jsonl").open("w", encoding="utf-8") as raw:
        raw.write(json.dumps({"metadata": metadata}) + "\n")
        for repeat in range(1, args.repeats + 1):
            for case in selected:
                iterations, result = analyze(args.engine, cases[case], args.depth, args.cap_ms, args.tt_mib)
                raw.write(json.dumps(dict(case=case, repeat=repeat, iterations=iterations, result=result)) + "\n")
                raw.flush()
                for row in iterations:
                    samples[case, row["depth"]].append(row)
                print(case, repeat, result["status"], result["depth"], flush=True)
    def spread(values):
        return dict(median=statistics.median(values), minimum=min(values), maximum=max(values))
    summary = []
    for case in selected:
        for depth in range(args.min_depth, args.depth + 1):
            rows = samples[case, depth]
            entry = dict(case=case, depth=depth, completed=len(rows), requested=args.repeats)
            if rows:
                entry.update(
                    cumulative={key: spread([row[key] for row in rows]) for key in METRICS},
                    iteration={key: spread([row["iteration"][key] for row in rows]) for key in METRICS},
                    tt_capacity=rows[0]["tt_capacity"],
                    tt_storage_budget_bytes=rows[0]["tt_storage_budget_bytes"],
                )
            summary.append(entry)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
