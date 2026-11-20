"""Build a self-contained Windows folder with the matching Rust rules engine."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    engine = root/'target/release/frisian-draughts.exe'
    if not engine.is_file(): raise SystemExit('Build the release Rust engine first: cargo build --release --locked')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed',
        '--name', 'FrisianDraughtsTestbench', '--paths', str(root),
        '--distpath', str(root/'dist'), '--workpath', str(root/'build/desktop'),
        '--specpath', str(root/'build'), str(root/'tools/testbench/desktop.py')], cwd=root, check=True)
    destination = root/'dist/FrisianDraughtsTestbench'
    # Qt uses Windows' ICU API. On developer machines PyInstaller can resolve
    # the same DLL name from Git/other PATH tools, with incompatible exports.
    # Do not redistribute that substitute for an OS library.
    system_icu_substitute = destination/'_internal/icuuc.dll'
    if system_icu_substitute.is_file(): system_icu_substitute.unlink()
    (destination/'engines').mkdir(exist_ok=True)
    shutil.copy2(engine, destination/'engines/frisian-draughts.exe')
    shutil.copy2(root/'license.txt', destination)
    shutil.copy2(root/'docs/desktop-guide.md', destination/'README.md')
    shutil.copy2(root/'tools/testbench/gui/NOTICE.md', destination)
    from importlib.metadata import distribution
    for name in ['PySide6', 'PySide6_Essentials', 'shiboken6', 'pyinstaller']:
        package = distribution(name)
        for file in package.files or []:
            if 'licenses' in file.parts and package.locate_file(file).is_file():
                target = destination/'THIRD_PARTY_LICENSES'/name/Path(*file.parts[file.parts.index('licenses')+1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package.locate_file(file), target)
    shutil.copytree(root/'tools/testbench/examples', destination/'examples', dirs_exist_ok=True)
    # Source examples resolve against the checkout; distribution examples must
    # resolve against the extracted folder instead.
    bundled_profiles = {'version': 1, 'engines': [
        {'name': name, 'executable': '../engines/frisian-draughts.exe'}
        for name in ['Rust A (smoke test)', 'Rust B (same build)']]}
    (destination/'examples/engines.json').write_text(json.dumps(bundled_profiles, indent=2), encoding='utf-8')
    from PySide6 import __version__ as qt_version
    import PyInstaller
    revision = os.environ.get('GITHUB_SHA', 'local development build')
    metadata = {'source_revision': revision, 'python': sys.version,
                'PySide6': qt_version, 'PyInstaller': PyInstaller.__version__}
    (destination/'BUILD.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    source = f'https://github.com/A9E4FF/Frisian_Draughts/tree/{revision}' if len(revision) == 40 else revision
    (destination/'SOURCE.txt').write_text(source + '\n', encoding='utf-8')
    hashes = []
    for relative in ['FrisianDraughtsTestbench.exe', 'engines/frisian-draughts.exe']:
        hashes.append(hashlib.sha256((destination/relative).read_bytes()).hexdigest() + '  ' + relative)
    (destination/'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')


if __name__ == '__main__': main()
