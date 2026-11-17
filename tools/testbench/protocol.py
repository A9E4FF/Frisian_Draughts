"""Hub v2 wire codec, based on Fabien Letouzey's Scan 3.1 protocol.txt.

No shell, GUI, board rules, or search policy belongs in this module. Hub v2 has
quoted strings but no backslash escape convention; do not use shlex or JSON
string escaping here. Unknown commands/arguments are preserved for callers.
"""
from dataclasses import dataclass


class ProtocolError(ValueError):
    """Malformed Hub wire message."""


def _name(value: str) -> bool:
    return bool(value) and all(
        not c.isspace() and not ord(c) < 32 and ord(c) != 127 and c not in '=\"'
        for c in value
    )


@dataclass(frozen=True)
class Message:
    command: str
    pairs: tuple[tuple[str, str], ...] = ()

    def get(self, name: str, default: str | None = None) -> str | None:
        # Scan processes arguments sequentially, so the final occurrence wins.
        return dict(self.pairs).get(name, default)

    def has(self, name: str) -> bool:
        return any(key == name for key, _ in self.pairs)


def parse(line: str) -> Message:
    """Parse one logical line, including optional trailing CRLF."""
    text = line.rstrip('\r\n')
    if any(ord(c) < 32 and c != '\t' for c in text) or '\x7f' in text:
        raise ProtocolError('control character in message')
    offset = 0

    def blank():
        nonlocal offset
        while offset < len(text) and text[offset].isspace():
            offset += 1

    def name():
        nonlocal offset
        blank()
        start = offset
        while offset < len(text) and _name(text[offset]):
            offset += 1
        if start == offset:
            raise ProtocolError('expected command or argument name')
        return text[start:offset]

    command = name()
    pairs = []
    while True:
        blank()
        if offset == len(text):
            break
        key = name()
        blank()
        value = ''
        if offset < len(text) and text[offset] == '=':
            offset += 1
            blank()
            if offset < len(text) and text[offset] == '"':
                offset += 1
                start = offset
                while offset < len(text) and text[offset] != '"':
                    offset += 1
                if offset == len(text):
                    raise ProtocolError('unterminated quoted value')
                value = text[start:offset]
                offset += 1
                if offset < len(text) and not text[offset].isspace():
                    raise ProtocolError('missing separator after quoted value')
            else:
                value = name()
        pairs.append((key, value))
    return Message(command, tuple(pairs))


def serialize(command: str, pairs=()) -> str:
    if not _name(command):
        raise ProtocolError('invalid command')
    result = [command]
    for name, value in pairs:
        if not _name(name):
            raise ProtocolError('invalid argument name')
        if value is None:
            result.append(name)
            continue
        value = str(value)
        if '"' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ProtocolError('Hub v2 cannot encode quotes or control characters')
        result.append(f'{name}={value}' if _name(value) else f'{name}="{value}"')
    return ' '.join(result)


def validate_position(position: str) -> str:
    """Validate Hub's board encoding, not game legality or historical state."""
    if len(position) != 51 or position[0] not in 'WB' or any(
        c not in 'wbWBe' for c in position[1:]
    ):
        raise ProtocolError('position must be side W/B plus 50 squares (wbWBe)')
    return position
