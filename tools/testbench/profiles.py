"""Portable profile persistence and launch validation shared by desktop tests."""
import json
from pathlib import Path
from .matches import Entrant
from .session import EngineProfile


def entrant(name, executable, arguments='["hub"]', cwd='', parameters='{}', revision='', capabilities=()):
    args = json.loads(arguments); params = json.loads(parameters)
    if not name.strip() or not executable.strip():
        raise ValueError('name and executable are required')
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError('arguments must be a JSON list of strings')
    if not isinstance(params, dict) or not all(isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in params.items()):
        raise ValueError('parameters must be a JSON object with scalar values')
    return Entrant(name.strip(), EngineProfile(executable, tuple(args), cwd or None), params, revision or None, tuple(capabilities))


def preflight(engine):
    if not Path(engine.profile.executable).is_file():
        raise ValueError(f'{engine.name}: executable not found: {engine.profile.executable}')
    if engine.profile.cwd and not Path(engine.profile.cwd).is_dir():
        raise ValueError(f'{engine.name}: working directory not found')


def save_profiles(path, engines):
    data = {'version': 1, 'engines': [{'name': e.name, 'executable': e.profile.executable,
        'arguments': list(e.profile.arguments), 'cwd': e.profile.cwd, 'parameters': e.parameters,
        'revision': e.revision, 'capabilities': list(e.capabilities)} for e in engines]}
    Path(path).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
