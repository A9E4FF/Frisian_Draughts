"""Build the integrated ScanGraphic 0.1.0 release from an explicitly supplied source tree.

No Scan data/binaries are vendored into the Rust repository. Compile copied C++
sources and ship their corresponding source together with the graphical build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--rust-engine', type=Path, help='Built Rust engine; defaults to target/release/frisian-draughts.exe')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = args.source.absolute(); stage = root/'build/scan-graphic-source'
    rust = (args.rust_engine or root/'target/release/frisian-draughts.exe').resolve()
    if not rust.is_file(): raise SystemExit('Build the Rust engine with cargo build --release first')
    for required in ['src/main.cpp', 'gui/main.py', 'gui/engine.py', 'data/eval_frisian', 'license.txt']:
        if not (source/required).is_file(): raise SystemExit(f'Missing ScanGraphic source file: {required}')
    for directory, patterns in [('src', ['*.cpp', '*.hpp', '*.h', 'Makefile']), ('gui', ['*.py'])]:
        (stage/directory).mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for file in (source/directory).glob(pattern):
                if 'Kopie' not in file.name: shutil.copy2(file, stage/directory/file.name)
    for name in ['license.txt', 'readme.txt', 'protocol.txt']:
        shutil.copy2(source/name, stage/name)
    # The versioned tools/scan_graphic engine wrapper includes the Hub startup fix.
    ini = 'variant = frisian\nbook = false\nthreads = 1\ntt-size = 20\nbb-size = 0\n'
    (stage/'scan.ini').write_text(ini, encoding='utf-8')
    (stage/'data').mkdir(exist_ok=True); shutil.copy2(source/'data/eval_frisian', stage/'data/eval_frisian')
    command = [args.compiler, '-std=c++14', '-fno-rtti', '-O2', '-mpopcnt', '-DNDEBUG', '-pthread',
        '-static', '-static-libgcc', '-static-libstdc++', '-o', str(stage/'scan.exe'),
        *map(str, sorted((stage/'src').glob('*.cpp'))), '-lws2_32']
    subprocess.run(command, check=True, cwd=stage)
    shutil.copy2(root/'tools/testbench/scan_graphic_entry.py', stage/'scan_graphic_entry.py')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed',
        '--name', 'ScanGraphic', '--paths', str(root), '--distpath', str(root/'dist'),
        '--workpath', str(root/'build/scan-graphic'), '--specpath', str(root/'build'),
        str(stage/'scan_graphic_entry.py')], check=True, cwd=stage)
    destination = root/'dist/ScanGraphic'
    shutil.copy2(rust, destination/'Frisian_Draughts.exe')
    shutil.copy2(root/'license.txt', destination/'Frisian_Draughts-LICENSE.txt')
    substitute = destination/'_internal/icuuc.dll'
    if substitute.is_file(): substitute.unlink()
    for name in ['scan.exe', 'scan.ini', 'license.txt', 'readme.txt', 'protocol.txt']:
        shutil.copy2(stage/name, destination/name)
    shutil.copytree(stage/'data', destination/'data', dirs_exist_ok=True)
    from tools.testbench import start_positions
    originals = start_positions.original_tool_positions()
    (destination/'examples').mkdir(exist_ok=True)
    (destination/'examples/original-tool-positions.fen').write_text('\n'.join(p['fen'] for p in originals)+'\n', encoding='utf-8')
    start_positions.save(destination/'examples/original-tool-fresh-setups.json', start_positions.fresh_setups(originals))
    source_zip = destination/'ScanGraphic-source.zip'
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in stage.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.exe','.pyc'):
                archive.write(file, file.relative_to(stage))
        for directory in ['src', 'tools', 'docs', '.github/workflows']:
            for file in (root/directory).rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                    archive.write(file, Path('frisian-draughts')/file.relative_to(root))
        for name in ['Cargo.toml', 'Cargo.lock', 'README.md', 'license.txt']:
            archive.write(root/name, Path('frisian-draughts')/name)
        archive.writestr('BUILD-SOURCE.txt', 'Windows build: install Rust stable, MinGW g++, Python 3.12+.\ncd frisian-draughts\ncargo build --release --locked\npython -m pip install -r tools/testbench/requirements-build.txt\npython -m tools.testbench.build_scan_graphic --source ..\nThe root contains the corresponding modified Scan C++ sources and data/eval_frisian.\n')
    (destination/'README-release.txt').write_text(
        'ScanGraphic / Frisian_Draughts 0.1.0 — Windows x64\n'
        'Extract the entire folder and run ScanGraphic.exe. No Python installation is required.\n'
        'Analysis: original Scan board, tactics, heatmaps and evaluation graph.\n'
        'Matches: Scan Graphic and Frisian_Draughts are already configured; choose control and paired rounds.\n'
        'Start positions: Add/Edit, Paste list, Import TXT/FEN, or Load/Save JSON collection. Checked entries run in both colors.\n'
        'Add original tool list (6) loads the original saved starts. Use as fresh setups explicitly clears extensions while retaining original FENs.\n'
        'Preview validates the selected start using the bundled Rust rules referee. Extended unsupported FEN fields are retained and reported.\n'
        'Results are written to a new folder under your user directory; it can be changed before a match.\n'
        'PDN: Import PDN or Load games.json in Matches, select a game, Open game in Analysis. Export PDN saves all loaded/matched games.\n'
        'Keep scan.ini and data/ beside scan.exe. Frisian mode; one thread; book and bitbases disabled.\n'
        'Scan 3.1 by Fabien Letouzey, GPLv3. Both engines, interface, corresponding sources and evaluation data are included.\n'
        'Source: ScanGraphic-source.zip; build and checksums: BUILD.json and SHA256SUMS.txt.\n', encoding='utf-8')
    from importlib.metadata import distribution
    for name in ['PySide6', 'PySide6_Essentials', 'shiboken6', 'pyinstaller']:
        package = distribution(name)
        for file in package.files or []:
            if 'licenses' in file.parts and package.locate_file(file).is_file():
                target=destination/'THIRD_PARTY_LICENSES'/name/Path(*file.parts[file.parts.index('licenses')+1:])
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(package.locate_file(file),target)
    metadata = {'version': '0.1.0', 'rust_engine_sha256': hashlib.sha256(rust.read_bytes()).hexdigest(), 'compiler_command': command[:10] + ['src/*.cpp', '-lws2_32'],
        'engine_sha256': hashlib.sha256((destination/'scan.exe').read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(source_zip.read_bytes()).hexdigest(),
        'data_sha256': hashlib.sha256((destination/'data/eval_frisian').read_bytes()).hexdigest()}
    (destination/'VERSION').write_text('0.1.0\n', encoding='utf-8')
    (destination/'BUILD.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (destination/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256((destination/name).read_bytes()).hexdigest()+'  '+name
        for name in ['ScanGraphic.exe','scan.exe','Frisian_Draughts.exe','ScanGraphic-source.zip','data/eval_frisian'])+'\n',encoding='utf-8')


    archive_path = root/'dist/ScanGraphic-0.1.0-Windows-x64.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in destination.rglob('*'):
            if file.is_file(): archive.write(file, Path('ScanGraphic-0.1.0')/file.relative_to(destination))
    print(archive_path)


if __name__ == '__main__': main()
