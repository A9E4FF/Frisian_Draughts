"""Runtime discovery for engines whose configuration/data are relative files."""
import os
from pathlib import Path
import shutil


def executable_path(executable):
    expanded = os.path.expandvars(os.path.expanduser(str(executable)))
    return os.path.abspath(expanded if Path(expanded).is_file() else shutil.which(expanded) or expanded)


def working_directory(executable, explicit=None):
    if explicit:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(str(explicit))))
    parent = Path(executable_path(executable)).parent
    # Scan development builds also commonly live in src/ next to scan.ini's
    # parent. Explicit user choices always take precedence.
    for directory in [parent, parent.parent]:
        if (directory/'scan.ini').is_file(): return str(directory)
    return str(parent)
