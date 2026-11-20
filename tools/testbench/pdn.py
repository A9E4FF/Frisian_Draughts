"""PDN documents and referee-backed Frisian replay, without a second rules engine.

Annotations and variation tokens are retained. Standard capture landing paths
are resolved against legal captured-square sets. Scan's captured-square dialect
is accepted only when it identifies the same unique legal move. An explicit
[%hub ...] comment disambiguates project exports without losing original text.
"""
from dataclasses import dataclass, field
import re

START = 'W:W31-50:B1-20'
RESULTS = {'1-0', '0-1', '1/2-1/2', '*', '2-0', '0-2', '1-1'}
TOKEN = re.compile(r'\{[^}]*\}|;[^\n]*|\([^)]*\)|\(|\)|\$\d+|\d+\.(?:\.\.)?|1/2-1/2|\S+')
LEX = re.compile(r'\{[^}]*\}|;[^\n]*|[()]|\$\d+|\d+\.(?:\.\.)?|[^\s(){};]+')
TAG = re.compile(r'\[([A-Za-z][\w-]*)\s+"((?:\\.|[^"\\])*)"\s*\]')
MOVE = re.compile(r'^\d+(?:[-xX:]\d+)+(?:[!?]+)?$')


@dataclass
class Game:
    tags: list[tuple[str, str]] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    moves: list[str] = field(default_factory=list)

    def tag(self, name, default=None):
        return next((v for k, v in reversed(self.tags) if k.lower() == name.lower()), default)

    @property
    def fen(self):
        return self.tag('FEN', START)


def loads(text):
    """Recover at the next header block; one malformed game cannot hide others."""
    chunks = re.split(r'(?m)(?=^\s*\[\w+\s+")', text.lstrip('\ufeff'))
    games = []
    current = Game()
    in_moves = False
    for chunk in chunks:
        if not chunk.strip():
            continue
        offset = 0
        match = TAG.match(chunk.lstrip())
        if match:
            if in_moves:
                games.append(current); current = Game(); in_moves = False
            leading = len(chunk) - len(chunk.lstrip())
            current.tags.append((match[1], re.sub(r'\\([\\"])', r'\1', match[2])))
            offset = leading + match.end()
        elif chunk.lstrip().startswith('['):
            current.errors.append('Malformed tag')
            offset = chunk.find('\n') + 1
        body = chunk[offset:]
        if body.strip():
            in_moves = True
            pos = 0
            for token in LEX.finditer(body):
                if body[pos:token.start()].strip():
                    current.errors.append('Unclosed comment or malformed token')
                current.tokens.append(token.group()); pos = token.end()
            if body[pos:].strip():
                current.errors.append('Unclosed comment')
    if current.tags or current.tokens or current.errors:
        games.append(current)
    return games


def dumps(games):
    def escape(value):
        return value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
    blocks = []
    for game in games:
        tags = '\n'.join(f'[{k} "{escape(v)}"]' for k, v in game.tags)
        # Semicolon comments require a newline; all other token boundaries can
        # be whitespace without changing annotation or variation semantics.
        body = ''.join(t + ('\n' if t.startswith(';') else ' ') for t in game.tokens).strip()
        blocks.append(tags + '\n\n' + body)
    return '\n\n'.join(blocks) + '\n'


def coordinates(square):
    row, col = divmod(square - 1, 5)
    return row, 2 * col + (1 if row % 2 == 0 else 0)


def captured_by_path(path, state):
    pieces = {p['square']: p for p in state['pieces']}
    pieces.pop(path[0], None)
    captures = []
    for source, target in zip(path, path[1:]):
        a, b = coordinates(source), coordinates(target)
        dr, dc = b[0] - a[0], b[1] - a[1]
        if not (dr == 0 or dc == 0 or abs(dr) == abs(dc)) or a == b:
            return None
        between = []
        for sq in pieces:
            r, c = coordinates(sq)
            if sq in (source, target):
                continue
            if (dr == 0 and r == a[0] and min(a[1], b[1]) < c < max(a[1], b[1])) or (
                dc == 0 and c == a[1] and min(a[0], b[0]) < r < max(a[0], b[0])) or (
                dr and dc and abs(r-a[0]) == abs(c-a[1]) and min(a[0], b[0]) < r < max(a[0], b[0]) and min(a[1], b[1]) < c < max(a[1], b[1])):
                between.append(sq)
        if len(between) != 1 or between[0] in captures or pieces[between[0]]['side'] == state['turn'] or target in pieces:
            return None
        captures.extend(between)
    return sorted(captures)


def resolve(text, state, explicit=None):
    legal = state['legal_moves']
    if explicit:
        if explicit not in legal:
            raise ValueError(f'illegal explicit capture identifier {explicit}')
        endpoint = re.split(r'[-xX:]', text.rstrip('!?'))
        full = re.split(r'[-x]', explicit)
        scan_identity = len(endpoint) > 2 and endpoint[:2] == full[:2] and sorted(endpoint[2:], key=int) == sorted(full[2:], key=int)
        if endpoint[0] != full[0] or (endpoint[-1] != full[1] and not scan_identity):
            raise ValueError('PDN endpoints disagree with explicit capture identifier')
        return explicit
    text = text.rstrip('!?').replace('X', 'x').replace(':', 'x')
    if '-' in text:
        candidates = [text] if text in legal else []
    else:
        values = [int(s) for s in text.split('x')]
        if any(not 1 <= n <= 50 for n in values):
            raise ValueError('square outside 1–50')
        candidates = []
        for move in legal:
            if 'x' not in move:
                continue
            canonical = [int(s) for s in move.split('x')]
            if canonical[:2] == values[:2] and (len(values) == 2 or sorted(values[2:]) == sorted(canonical[2:])):
                candidates.append(move)
            if len(values) > 2 and canonical[0] == values[0] and canonical[1] == values[-1] and captured_by_path(values, state) == sorted(canonical[2:]):
                candidates.append(move)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError(('ambiguous' if candidates else 'illegal') + f' move {text}')
    return candidates[0]


def validate(game, referee):
    """Validate mainline and every recursive variation, retaining all tokens."""
    if game.errors:
        return game
    if game.tag('FrisianState'):
        game.errors.append('Imported project-specific state needs a canonical JSON report')
        return game
    tokens = game.tokens
    main = []

    def sequence(index, history, variation=False):
        previous = list(history)
        ended = False
        while index < len(tokens):
            text = tokens[index]
            if text == ')':
                if not variation:
                    raise ValueError('unmatched closing variation')
                return index + 1, history
            if text == '(':
                index, _ = sequence(index + 1, list(previous), True)
                continue
            if MOVE.fullmatch(text) and text not in RESULTS:
                if ended:
                    raise ValueError('move after result')
                state = referee.inspect(game.fen, history)
                if state['outcome'] != 'ongoing':
                    raise ValueError('move after terminal position')
                explicit = None
                for annotation in tokens[index+1:]:
                    if not annotation.startswith(('{', ';', '$')):
                        break
                    match = re.search(r'\[%hub\s+([\dx-]+)\]', annotation)
                    if match:
                        explicit = match[1]
                previous = list(history)
                try:
                    history.append(resolve(text, state, explicit))
                except ValueError as exc:
                    raise ValueError(f'ply {len(history)+1}: {exc}') from exc
                if not variation:
                    main[:] = history
            elif text in RESULTS:
                ended = True
                if not variation and game.tag('Result') and game.tag('Result') != text:
                    raise ValueError('Result tag and movetext disagree')
            elif not (text.startswith(('{', ';', '$')) or re.fullmatch(r'\d+\.(?:\.\.)?', text) or re.fullmatch(r'[!?]+', text)):
                raise ValueError(f'unsupported token {text}')
            index += 1
        if variation:
            raise ValueError('unclosed variation')
        return index, history
    try:
        sequence(0, [])
        referee.inspect(game.fen, main)
        game.moves = main
    except (ValueError, RuntimeError) as exc:
        game.errors.append(str(exc))
    return game


def landing_path(move, state):
    """Find a legal move's display path; the referee remains the legality oracle."""
    values = [int(s) for s in move.split('x')]
    source, destination, *victims = values
    pieces = {p['square']: p for p in state['pieces']}
    moving = pieces.pop(source)
    coords = {coordinates(s): s for s in range(1, 51)}
    directions = [(-1,-1),(-1,1),(1,-1),(1,1),(-2,0),(2,0),(0,-2),(0,2)]
    attempts = [0]
    def visit(current, taken, path):
        attempts[0] += 1
        if attempts[0] > 200000:
            raise ValueError('capture path exceeds export work limit; use Scan notation')
        if len(taken) == len(victims):
            return path if current == destination else None
        r,c = coordinates(current)
        for dr,dc in directions:
            victim = None
            for step in range(1, 11):
                target = coords.get((r+dr*step,c+dc*step))
                if target is None: break
                if target in pieces:
                    if victim is not None or target not in victims or target in taken: break
                    victim = target
                elif victim is not None:
                    result = visit(target, taken | {victim}, path+[target])
                    if result: return result
                    if moving['piece'] == 'man': break
                if moving['piece'] == 'man' and step >= 2: break
        return None
    result = visit(source, set(), [source])
    if result is None: raise ValueError(f'cannot reconstruct standard capture path: {move}')
    return 'x'.join(map(str, result))


def from_record(record, referee=None, dialect='standard'):
    """Lossless project export, using an explicit capture identity annotation.

    Endpoint notation stays standard PDN. Importers which ignore comments may
    still need to ask users about ambiguous captures; our importer never guesses.
    """
    tags = [('Event', record.get('event', 'Engine match')), ('White', record.get('white', 'White')),
            ('Black', record.get('black', 'Black')), ('Result', record.get('result', '*')),
            ('GameType', '97'), ('SetUp', '1'), ('FEN', record.get('fen', START)),
            ('Termination', record.get('termination', 'unfinished'))]
    if record.get('restrictions'):
        tags.append(('FrisianState', 'See canonical JSON report'))
    game = Game(tags)
    if dialect not in ('standard', 'scan'): raise ValueError('unknown PDN capture dialect')
    if dialect == 'scan': game.tags.append(('CaptureNotation', 'Scan captured squares'))
    black = game.fen.startswith('B')
    history = []
    for ply, move in enumerate(record['moves']):
        if (ply + black) % 2 == 0:
            game.tokens.append(f'{(ply+black)//2+1}.')
        elif ply == 0:
            game.tokens.append('1...')
        if 'x' in move:
            values = move.split('x')
            notation = move if dialect == 'scan' else landing_path(move, referee.inspect(game.fen, history)) if referee else 'x'.join(values[:2])
            game.tokens.extend([notation, '{[%hub ' + move + ']}'])
        else:
            game.tokens.append(move)
        history.append(move)
    if referee is not None:
        referee.inspect(game.fen, history)
    game.tokens.append(record.get('result', '*'))
    return game
