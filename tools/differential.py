#!/usr/bin/env python3
"""Compare complete states and legal moves against a pinned Scan oracle.
Usage: python3 tools/differential.py /path/to/scan-checkout
Requires g++, cargo, and an unmodified Scan 3.1 checkout at the pinned revision.
"""
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCAN = pathlib.Path(sys.argv[1]).resolve()
REV = '7aae17e7b7bfc47744601afb1ee7655e18983ce5'
assert subprocess.check_output(['git', '-C', str(SCAN), 'rev-parse', 'HEAD'], text=True).strip() == REV
subprocess.run(['cargo', 'build', '--example', 'rules_oracle'], cwd=ROOT, check=True)
rng = random.Random(3101)

def board(pieces, turn='W'):
    cells = ['e'] * 50
    for sq, pc in pieces:
        cells[sq - 1] = pc
    return turn + ''.join(cells)

with tempfile.TemporaryDirectory() as tmp:
    oracle = pathlib.Path(tmp) / 'scan-oracle'
    sources = [str(p) for p in sorted((SCAN / 'src').glob('*.cpp')) if p.name != 'main.cpp']
    subprocess.run(['g++', '-std=c++14', '-O2', '-pthread', '-I' + str(SCAN / 'src'),
                    str(ROOT / 'tools/scan_oracle.cpp'), *sources, '-o', str(oracle)], check=True)
    processes = [subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1)
                 for exe in [oracle, ROOT / 'target/debug/examples/rules_oracle']]
    checked = captures = restrictions = 0

    def compare(command):
        global checked, captures, restrictions
        outputs = []
        for p in processes:
            p.stdin.write(command + '\n')
            p.stdin.flush()
            line = p.stdout.readline().strip()
            assert line, f'oracle exited for {command}'
            state, moves = line.split('|')
            outputs.append((state, sorted(moves.split())))
        assert outputs[0] == outputs[1], (command, outputs)
        checked += 1
        state, moves = outputs[0]
        captures += bool(moves and 'x' in moves[0])
        restrictions += ',1:' in state or ',2:' in state or ',3:' in state
        return moves

    try:
        fixtures = [board([(n, 'b') for n in range(1,21)] + [(n, 'w') for n in range(31,51)])]
        fixtures += [board(p) for p in [
            [(28,'w'),(23,'b')], [(28,'w'),(27,'b')],
            [(28,'W'),(23,'b'),(12,'B'),(45,'w')],
            [(32,'W'),(27,'b'),(17,'b'),(19,'B'),(29,'b'),(46,'w')],
            [(28,'W'),(46,'w'),(5,'B'),(1,'b')],
            [(28,'w'),(27,'b'),(16,'b'),(23,'B')],
            [(11,'w'),(7,'b'),(8,'b')],
            [(45,'W'),(8,'B'),(44,'B'),(12,'B'),(33,'B'),(18,'B'),(40,'B')],
            [(49,'W'),(25,'B'),(7,'b'),(30,'b'),(19,'b'),(46,'B'),(35,'b'),(11,'b'),(42,'B'),(15,'b'),(34,'b')],
        ]]
        # Sparse mixed-piece positions stress king rays and capture priorities.
        for _ in range(300):
            count = rng.randrange(4,17)
            chosen = rng.sample(range(1,51),count)
            pcs = []
            for i, sq in enumerate(chosen):
                side = 'w' if i % 2 == 0 else 'b'
                pc = side.upper() if rng.randrange(2) or (side == 'w' and sq <= 5) or (side == 'b' and sq >= 46) else side
                pcs.append((sq,pc))
            fixtures.append(board(pcs, rng.choice('WB')))
        # Every possible king origin, including all board boundaries, and the
        # mixed king/man search fixture. Position-only adapters permit replay
        # past repetition, intentionally exercising ray geometry for 100 plies.
        fixtures += [board([(n, 'W'), (51-n, 'B')]) for n in range(1,51)]
        fixtures += [board([(1,'W'),(46,'w'),(5,'B'),(20,'b')])]
        fixtures += [fixtures[0]] * 40
        for fixture in fixtures:
            moves = compare('new ' + fixture)
            for _ in range(100):
                if not moves:
                    break
                moves = compare('play ' + rng.choice(moves))
        print(f'Matched {checked} states, including {captures} capture positions and {restrictions} king-restriction states (seed 3101).')
    finally:
        for p in processes:
            p.stdin.close()
            p.wait(timeout=10)
