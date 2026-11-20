"""Small UI model helpers; usable without Qt."""
import json
from pathlib import Path


def board_fen(pieces, turn):
    sides = []
    for side in ('W', 'B'):
        fields = [f"{'K' if piece.isupper() else ''}{square}" for square, piece in sorted(pieces.items())
                  if piece.upper() == side]
        sides.append(side + ','.join(fields))
    return ':'.join([turn, *sides])


def move_tuple(move):
    capture = 'x' in move
    values = [int(x) for x in move.split('x' if capture else '-')]
    return values[0], values[1], tuple(values[2:]), 'capture' if capture else 'quiet'


def load_replay(path):
    games = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(games, list) or not all(isinstance(g, dict) and isinstance(g.get('fen'), str)
        and isinstance(g.get('moves'), list) and all(isinstance(m, str) for m in g['moves']) for g in games):
        raise ValueError('expected a testbench games.json report with FEN and canonical moves')
    return games
