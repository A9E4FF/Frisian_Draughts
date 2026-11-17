#!/usr/bin/env python3
"""Compare this checkout with the pre-bitboard baseline, including exact PVs.
Usage: python3 tools/benchmark_bitboards.py [--repeats 3] [--output /tmp/report.json]
Requires cargo and git. Builds an isolated archive; never checks out over user files.
"""
import argparse
import csv
import io
import json
import pathlib
import statistics
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'a5e74a24885518e8e355aab31d845ec68a2737c3'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repeats', type=int, default=3)
parser.add_argument('--output', type=pathlib.Path)
args = parser.parse_args()
if args.repeats < 1:
    parser.error('--repeats must be positive')


def run(checkout, example):
    result = subprocess.run(['cargo', 'run', '--release', '--example', example],
                            cwd=checkout, check=True, text=True, stdout=subprocess.PIPE)
    return list(csv.DictReader(io.StringIO(result.stdout)))


with tempfile.TemporaryDirectory(prefix='frisian-bitboard-') as tmp:
    baseline = pathlib.Path(tmp)
    # git archive also works from the PR branch, with main left untouched.
    archive = subprocess.Popen(['git', 'archive', BASE], cwd=ROOT, stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', str(baseline)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    if archive.wait() != 0:
        raise RuntimeError('failed to archive baseline')
    candidate = baseline / 'candidate'
    # Benchmark a snapshot to avoid rewriting drivers in the active checkout.
    import shutil
    shutil.copytree(ROOT, candidate, ignore=shutil.ignore_patterns('.git', 'target', '__pycache__'))
    for example in ['search_bench.rs', 'movegen_bench.rs']:
        driver = (ROOT / 'examples' / example).read_text()
        (baseline / 'examples' / example).write_text(driver)
        if example == 'search_bench.rs':
            driver = driver.replace('SearchLimits::new(depth).unwrap()',
                                    'SearchLimits::new(depth).unwrap().with_tt_enabled(false)')
        (candidate / 'examples' / example).write_text(driver)
    samples = {'before': [], 'after': []}
    for _ in range(args.repeats):
        for name, checkout in [('before', baseline), ('after', candidate)]:
            samples[name].append({'search': run(checkout, 'search_bench'),
                                  'movegen': run(checkout, 'movegen_bench')[0]})
    canonical = samples['before'][0]
    for runs in samples.values():
        for sample in runs:
            # Timing alone may differ. Include depth, both node counts, score,
            # selected move, and the complete principal variation in equality.
            normalized = lambda rows: [{k: v for k, v in r.items() if k != 'seconds'} for r in rows]
            if normalized(sample['search']) != normalized(canonical['search']):
                raise AssertionError('search behavior changed')
            if normalized([sample['movegen']]) != normalized([canonical['movegen']]):
                raise AssertionError('move generation corpus/checksum changed')
    medians = {}
    for name, runs in samples.items():
        medians[name] = {
            'search': [{**row, 'seconds': statistics.median(float(s['search'][i]['seconds']) for s in runs)}
                       for i, row in enumerate(runs[0]['search'])],
            'movegen': {**runs[0]['movegen'], 'seconds': statistics.median(float(s['movegen']['seconds']) for s in runs)},
        }
    report = {'baseline': BASE, 'repeats': args.repeats, 'behavior_matches': True,
              'medians': medians, 'samples': samples}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'behavior_matches': True, 'medians': medians}, indent=2))
