"""Versioned position cases. Frisian move legality belongs to the Rust engine."""
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = ROOT / 'target' / 'release' / ('frisian-draughts.exe' if os.name == 'nt' else 'frisian-draughts')
HISTORY_NOTE = ('Draughts FEN stores pieces and side to move, but not king restriction counters '
                'or repetition history. They start cleared unless supplementary restrictions '
                'and/or replay moves are supplied. Accepted moves apply after replay.')


def validate_case(case):
    if not isinstance(case, dict):
        raise ValueError('Each position must be an object')
    result = dict(case)
    for key in ('name', 'fen', 'notes'):
        value = result.get(key, '' if key == 'notes' else None)
        if not isinstance(value, str) or (key != 'notes' and not value.strip()):
            raise ValueError(f'{key} must be a nonempty string' if key != 'notes' else 'notes must be text')
        result[key] = value.strip() if key != 'notes' else value
    depth = result.get('depth', 10)
    if type(depth) is not int or not 1 <= depth <= 64:
        raise ValueError('depth must be an integer from 1 to 64')
    result['depth'] = depth
    for key in ('accepted_moves', 'moves'):
        value = result.get(key, [])
        if not isinstance(value, list) or any(not isinstance(m, str) or not m.strip() for m in value):
            raise ValueError(f'{key} must be a list of nonempty move strings')
        result[key] = [m.strip() for m in value]
    if 'restrictions' in result and not isinstance(result['restrictions'], dict):
        raise ValueError('restrictions must be an object with white/black entries')
    if 'tt_enabled' in result and type(result['tt_enabled']) is not bool:
        raise ValueError('tt_enabled must be true or false')
    if 'tt_megabytes' in result and (type(result['tt_megabytes']) is not int or not 1 <= result['tt_megabytes'] <= 256):
        raise ValueError('tt_megabytes must be an integer from 1 to 256')
    return result


def validate_suite(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Suite must have version: 1')
    if not isinstance(data.get('positions'), list):
        raise ValueError('Suite must contain a positions list')
    return [validate_case(case) for case in data['positions']]


def load_suite(path):
    with Path(path).open(encoding='utf-8') as source:
        return validate_suite(json.load(source))


def save_suite(path, cases):
    data = {'version': 1, 'positions': [validate_case(case) for case in cases]}
    path = Path(path)
    # Replace only after validation and a complete write; preserve a prior suite on error.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def request_for(case, command='analyze'):
    case = validate_case(case)
    if command not in ('inspect', 'analyze'):
        raise ValueError('Unknown engine command')
    allowed = ('fen', 'depth', 'accepted_moves', 'restrictions', 'moves', 'tt_enabled', 'tt_megabytes')
    return {'command': command, **{key: case[key] for key in allowed if key in case}}
