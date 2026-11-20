"""Build a companion ScanGraphic release from an explicitly supplied source tree.

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
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = args.source.absolute(); stage = root/'build/scan-graphic-source'
    for required in ['src/main.cpp', 'gui/main.py', 'gui/engine.py', 'data/eval_frisian', 'license.txt']:
        if not (source/required).is_file(): raise SystemExit(f'Missing ScanGraphic source file: {required}')
    for directory, patterns in [('src', ['*.cpp', '*.hpp', '*.h', 'Makefile']), ('gui', ['*.py'])]:
        (stage/directory).mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for file in (source/directory).glob(pattern):
                if 'Kopie' not in file.name: shutil.copy2(file, stage/directory/file.name)
    for name in ['license.txt', 'readme.txt', 'protocol.txt']:
        shutil.copy2(source/name, stage/name)
    # QProcess.start is asynchronous: the initial hub message must be sent only
    # once the process is Running, otherwise the legacy wrapper drops it.
    engine_py = stage/'gui/engine.py'; code = engine_py.read_text(encoding='utf-8')
    old = 'self._process.start()\n\n        # Send hub handshake (engine needs this to start the protocol)\n        self.send_command("hub")'
    new = 'self._process.started.connect(lambda: self.send_command("hub"))\n        self._process.start()'
    if old not in code: raise SystemExit('ScanGraphic Hub startup source changed; review the compatibility patch')
    engine_py.write_text(code.replace(old,new), encoding='utf-8')
    ini = 'variant = frisian\nbook = false\nthreads = 1\ntt-size = 20\nbb-size = 0\n'
    (stage/'scan.ini').write_text(ini, encoding='utf-8')
    (stage/'data').mkdir(exist_ok=True); shutil.copy2(source/'data/eval_frisian', stage/'data/eval_frisian')
    command = [args.compiler, '-std=c++14', '-fno-rtti', '-O2', '-mpopcnt', '-DNDEBUG', '-pthread',
        '-static', '-static-libgcc', '-static-libstdc++', '-o', str(stage/'scan.exe'),
        *map(str, sorted((stage/'src').glob('*.cpp'))), '-lws2_32']
    subprocess.run(command, check=True, cwd=stage)
    shutil.copy2(root/'tools/testbench/scan_graphic_entry.py', stage/'scan_graphic_entry.py')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed',
        '--name', 'ScanGraphic', '--paths', str(stage), '--distpath', str(root/'dist'),
        '--workpath', str(root/'build/scan-graphic'), '--specpath', str(root/'build'),
        str(stage/'scan_graphic_entry.py')], check=True, cwd=stage)
    destination = root/'dist/ScanGraphic'
    substitute = destination/'_internal/icuuc.dll'
    if substitute.is_file(): substitute.unlink()
    for name in ['scan.exe', 'scan.ini', 'license.txt', 'readme.txt', 'protocol.txt']:
        shutil.copy2(stage/name, destination/name)
    shutil.copytree(stage/'data', destination/'data', dirs_exist_ok=True)
    source_zip = destination/'ScanGraphic-source.zip'
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in stage.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.exe','.pyc'):
                archive.write(file, file.relative_to(stage))
    (destination/'README-release.txt').write_text(
        'Extract the entire folder and run ScanGraphic.exe. Keep scan.ini and data/ beside scan.exe.\n'
        'For the unified testbench select scan.exe with arguments ["hub"]. The working directory is this folder.\n'
        'Frisian mode; one thread; book and bitbases disabled. The original pattern evaluation is included.\n'
        'Scan 3.1 by Fabien Letouzey, GPLv3. Corresponding modified sources and evaluation data are in ScanGraphic-source.zip.\n'
        'The engine is rebuilt from the supplied sources. See BUILD.json for the build command and hashes.\n', encoding='utf-8')
    from importlib.metadata import distribution
    for name in ['PySide6', 'PySide6_Essentials', 'shiboken6', 'pyinstaller']:
        package = distribution(name)
        for file in package.files or []:
            if 'licenses' in file.parts and package.locate_file(file).is_file():
                target=destination/'THIRD_PARTY_LICENSES'/name/Path(*file.parts[file.parts.index('licenses')+1:])
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(package.locate_file(file),target)
    metadata = {'compiler_command': command[:10] + ['src/*.cpp', '-lws2_32'],
        'engine_sha256': hashlib.sha256((destination/'scan.exe').read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(source_zip.read_bytes()).hexdigest(),
        'data_sha256': hashlib.sha256((destination/'data/eval_frisian').read_bytes()).hexdigest()}
    (destination/'BUILD.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (destination/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256((destination/name).read_bytes()).hexdigest()+'  '+name
        for name in ['ScanGraphic.exe','scan.exe','ScanGraphic-source.zip','data/eval_frisian'])+'\n',encoding='utf-8')


if __name__ == '__main__': main()
