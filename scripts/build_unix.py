"""Build native macOS or Linux self-contained Homeboard preview downloads."""
from __future__ import annotations
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'release' / 'artifacts'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(*arguments):
    subprocess.run([str(x) for x in arguments], check=True, cwd=ROOT)

def main():
    if sys.platform not in ('darwin', 'linux'):
        raise SystemExit('Build on the target macOS or Linux machine, not by cross-compiling.')
    version = (ROOT / 'VERSION').read_text().strip()
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('arm64', 'aarch64') else 'x64' if machine in ('x86_64', 'amd64') else None
    if arch is None:
        raise SystemExit('This preview builds x64 and arm64 packages only.')
    target = ('macos' if sys.platform == 'darwin' else 'linux') + '-' + arch
    build = ROOT / '.build' / target
    build.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('homeboard_icon', ROOT / 'installer/make_icon.py')
    icon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(icon)
    png = build / 'homeboard.png'
    png.write_bytes(icon.png(icon.pixels(256)))
    sources = ('index.html', 'server.py', 'launcher.py', 'desktop_install.py', 'VERSION', 'LICENSE',
               'scripts/build_unix.py', 'requirements-unix-build.txt', 'release/Quickstart.txt', 'THIRD_PARTY_NOTICES.md')
    source_hashes = {name: sha(ROOT / name) for name in sources}
    arguments = ['--noconfirm', '--onedir', '--noupx', '--name', 'Homeboard',
        '--distpath', str(build / 'dist'), '--workpath', str(build / 'work'), '--specpath', str(build / 'spec'),
        '--paths', str(ROOT), '--hidden-import', 'server', '--hidden-import', 'desktop_install', '--collect-data', 'tzdata',
        '--add-data', str(ROOT / 'index.html') + ':.', '--add-data', str(ROOT / 'VERSION') + ':.',
        '--add-data', str(png) + ':.']
    if sys.platform == 'darwin':
        icns = build / 'homeboard.icns'
        chunk = b'ic08' + struct.pack('>I', len(png.read_bytes()) + 8) + png.read_bytes()
        icns.write_bytes(b'icns' + struct.pack('>I', len(chunk) + 8) + chunk)
        arguments += ['--windowed', '--icon', str(icns), '--osx-bundle-identifier', 'io.github.owaise-collab.homeboard']
    import PyInstaller.__main__
    PyInstaller.__main__.run(arguments + [str(ROOT / 'launcher.py')])
    bundle = build / 'dist' / ('Homeboard.app' if sys.platform == 'darwin' else 'Homeboard')
    if sys.platform == 'darwin':
        info_path = bundle / 'Contents' / 'Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['LSUIElement'] = True
        info['NSLocalNetworkUsageDescription'] = 'Homeboard shares your family dashboard with devices on your home network.'
        info_path.write_bytes(plistlib.dumps(info))
    resource = bundle / 'Contents' / 'Resources' if sys.platform == 'darwin' else bundle
    for relative, name in [('LICENSE', 'LICENSE'), ('THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md'), ('release/Quickstart.txt', 'Quickstart.txt')]:
        shutil.copy2(ROOT / relative, resource / name)
    notices = resource / 'licenses'
    notices.mkdir(exist_ok=True)
    candidates = [Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE',
                  Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt']
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license:
        shutil.copy2(python_license, notices / 'PYTHON-LICENSE.txt')
    else:
        url = 'https://raw.githubusercontent.com/python/cpython/v' + platform.python_version() + '/LICENSE'
        with urllib.request.urlopen(url, timeout=30) as response:
            (notices / 'PYTHON-LICENSE.txt').write_bytes(response.read())
    for package in ('PyInstaller', 'tzdata', 'pyinstaller-hooks-contrib'):
        distribution = importlib.metadata.distribution(package)
        for item in distribution.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in Path(str(item)).parts):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    destination = notices / package / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    if sys.platform == 'darwin':
        # Ad-hoc signing keeps the native bundle internally consistent. It is
        # not a trusted Developer ID signature or Apple notarization.
        run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', bundle)
    if any(sha(ROOT / name) != digest for name, digest in source_hashes.items()):
        raise RuntimeError('Source changed during the build. Rebuild stable source.')
    manifest = {'product': 'Homeboard', 'version': version, 'target': target, 'releaseStatus': 'release-candidate',
        'trustedPublisherSignature': False, 'sources': source_hashes,
        'tools': {'python': platform.python_version(), 'PyInstaller': importlib.metadata.version('PyInstaller'),
                  'tzdata': importlib.metadata.version('tzdata')},
        'files': [{'path': path.relative_to(bundle).as_posix(), 'size': path.stat().st_size, 'sha256': sha(path)}
                  for path in sorted(bundle.rglob('*')) if path.is_file()]}
    manifest_path = build / 'build-manifest.json' if sys.platform == 'darwin' else bundle / 'build-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    run(sys.executable, ROOT / 'scripts/smoke_desktop.py', '--bundle', bundle, '--manifest', manifest_path)
    if sys.platform == 'darwin':
        disk = build / 'disk'
        disk.mkdir(exist_ok=True)
        # ditto retains bundle symlinks and executable bits.
        run('/usr/bin/ditto', bundle, disk / 'Homeboard.app')
        link = disk / 'Applications'
        if not link.exists():
            link.symlink_to('/Applications', target_is_directory=True)
        shutil.copy2(ROOT / 'release/Quickstart.txt', disk / 'Quickstart.txt')
        archive = OUT / f'Homeboard-{version}-{target}.dmg'
        run('/usr/bin/hdiutil', 'create', '-volname', 'Homeboard', '-srcfolder', disk, '-ov', '-format', 'UDZO', archive)
    else:
        archive = OUT / f'Homeboard-{version}-{target}.tar.gz'
        installer = build / 'install.sh'
        installer.write_bytes((ROOT / 'installer/install-linux.sh').read_bytes())
        installer.chmod(0o755)
        with tarfile.open(archive, 'w:gz') as output:
            output.add(bundle, arcname='Homeboard')
            output.add(installer, arcname='install.sh')
            output.add(ROOT / 'release/Quickstart.txt', arcname='Quickstart.txt')
    final_manifest = OUT / f'Homeboard-{version}-{target}.manifest.json'
    final_manifest.write_text(json.dumps(manifest | {'artifact': {'file': archive.name, 'size': archive.stat().st_size,
        'sha256': sha(archive)}}, indent=2) + '\n', encoding='utf-8')
    archive.with_suffix(archive.suffix + '.sha256').write_text(sha(archive) + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'target': target, 'artifact': archive.name, 'sha256': sha(archive)}))

if __name__ == '__main__':
    main()
