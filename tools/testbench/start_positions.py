"""Named match starts, including replay history and explicit king restrictions."""
import copy
import json
from pathlib import Path
import re
import uuid

START = 'W:W31-50:B1-20'


def position(name='Standard start', fen=START, **fields):
    return {'id': uuid.uuid4().hex, 'name': name, 'fen': fen, 'enabled': True,
            'moves': [], 'restrictions': {}, **fields}


def check(item):
    item = copy.deepcopy(item)
    if not isinstance(item, dict): raise ValueError('Each start must be an object')
    for key in ('id', 'name', 'fen'):
        if not isinstance(item.get(key), str) or not item[key].strip(): raise ValueError(f'Start needs {key}')
    if type(item.get('enabled')) is not bool: raise ValueError('enabled must be true or false')
    if not isinstance(item.get('moves'), list) or not all(isinstance(m, str) for m in item['moves']): raise ValueError('moves must be a list of Hub moves')
    if not isinstance(item.get('restrictions'), dict): raise ValueError('restrictions must be an object')
    return item


def parse_text(text):
    """Legacy one-FEN-per-line format. Preserve extended FENs for explicit review."""
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(('#', ';')): continue
        line = re.sub(r'^FEN\s*:?\s*', '', line, flags=re.I)
        tokens = line.split()
        candidates = [token for token in tokens if token.lower() == 'start' or re.match(r'^[WB]:', token, re.I)
                      or re.fullmatch(r'[WB][wWbBeE.]{50}', token)]
        if len(candidates) != 1: raise ValueError(f'Line {number}: expected one FEN, found {len(candidates)}')
        fen = candidates[0]
        result.append(position(f'Imported line {number}', START if fen.lower() == 'start' else fen))
    if not result: raise ValueError('No positions found')
    return result


def save(path, positions):
    checked = [check(item) for item in positions]
    if len({p['id'] for p in checked}) != len(checked): raise ValueError('Duplicate position IDs')
    Path(path).write_text(json.dumps({'version': 1, 'positions': checked}, indent=2) + '\n', encoding='utf-8')


def load(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('positions'), list): raise ValueError('Expected version-1 start collection')
    items = [check(item) for item in data['positions']]
    if len({p['id'] for p in items}) != len(items): raise ValueError('Duplicate position IDs')
    return items


def prepare(item):
    """Accept the old tool's zero-state, men-only opening format losslessly.

    The supplied openings contain only men and H0/Fn/+0+0 suffixes. They
    need no imported king state. Keep the complete source and each suffix
    in the report while passing the board to the shared rules referee.
    Other extensions still need explicit conversion or a state-aware import.
    """
    item = check(item)
    parts = item['fen'].split(':')
    if len(parts) > 3:
        known = re.fullmatch(r'H0:F[1-9][0-9]*:\+0\+0', ':'.join(parts[3:]))
        if not known or 'K' in ':'.join(parts[1:3]).upper():
            raise ValueError(f"{item['name']}: extended FEN contains unsupported state; original retained. Supply replay history/restrictions or use fresh setup conversion")
        item['original_fen'] = item['fen']
        item['legacy_fields'] = parts[3:]
        item['fen'] = ':'.join(parts[:3])
        item['import_note'] = 'Original tool zero-state men-only opening; complete source FEN and legacy fields retained.'
    return item


def validate(item, referee):
    item = prepare(item)
    return referee.inspect(item['fen'], item['moves'], item['restrictions'])


def original_tool_positions():
    from .legacy_starts import LEGACY_FENS
    return [position(f'Original tool {i:02}', fen, source='Original Engine Match tool: positions/positions.txt') for i, fen in enumerate(LEGACY_FENS, 1)]


def fresh_setups(positions):
    """Explicit user conversion: keep the full original FEN and clear history."""
    result = copy.deepcopy(positions)
    for item in result:
        if ':' in item['fen'] and len(item['fen'].split(':')) > 3:
            item.setdefault('original_fen', item['fen'])
            item['fen'] = ':'.join(item['fen'].split(':')[:3])
            item['moves'] = []; item['restrictions'] = {}
            item['conversion_note'] = 'Explicit fresh setup: extended fields and previous history are not applied; original FEN retained.'
    return result
