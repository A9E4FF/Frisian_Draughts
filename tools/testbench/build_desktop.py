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
    (destination/'engines').mkdir(exist_ok=True)
    shutil.copy2(engine, destination/'engines/frisian-draughts.exe')
    shutil.copy2(root/'license.txt', destination)
    shutil.copy2(root/'docs/desktop-guide.md', destination/'README.md')
    shutil.copy2(root/'tools/testbench/gui/NOTICE.md', destination)
    shutil.copytree(root/'tools/testbench/examples', destination/'examples', dirs_exist_ok=True)
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
