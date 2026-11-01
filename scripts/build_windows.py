"""Build a self-contained Windows app, portable ZIP, and per-user installer.

Only build tooling is installed on the developer machine. The generated buyer
installer includes Python and the app; it never includes the developer's data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '.build-tools' / 'python'
BUILD = ROOT / '.build' / 'windows'
OUT = ROOT / 'release' / 'artifacts'


def run(command, **kwargs):
    subprocess.run([str(value) for value in command], cwd=ROOT, check=True, **kwargs)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_notices(bundle):
    notices = bundle / '_internal' / 'licenses'
    notices.mkdir(parents=True, exist_ok=True)
    (notices / 'RUNTIME-NOTICES.md').write_text(
        'See THIRD_PARTY_NOTICES.md in the application folder. These are available build-package license texts; '
        'the seller must complete the exact runtime/SBOM notice audit before public sale.\n', encoding='utf-8')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('The Python runtime license is required for this binary distribution.')
    shutil.copy2(python_license, notices / 'PYTHON-LICENSE.txt')
    for package in ('PyInstaller', 'tzdata', 'pyinstaller-hooks-contrib'):
        dist = importlib.metadata.distribution(package)
        for item in dist.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in Path(str(item)).parts):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = notices / package / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nsis', type=Path, default=ROOT / '.build-tools' / 'nsis-3.13' / 'makensis.exe')
    parser.add_argument('--skip-tests', action='store_true', help='Use only after the same source passed its tests.')
    parser.add_argument('--signtool', type=Path)
    parser.add_argument('--certificate-thumbprint', help='Public identifier of a certificate already in your Windows store.')
    parser.add_argument('--timestamp-url', default='https://timestamp.digicert.com')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize <= 2 ** 32:
        parser.error('Build this x64 installer using 64-bit Python on Windows.')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', version):
        parser.error('VERSION must be a safe semantic version.')
    if not (ROOT / 'launcher.py').is_file():
        parser.error('launcher.py is required before building.')
    if not args.nsis.is_file():
        parser.error('Portable NSIS compiler not found. See release/BUILDING.md.')
    if args.signtool and (not args.certificate_thumbprint or not re.fullmatch(r'[a-fA-F0-9]{40}', args.certificate_thumbprint)):
        parser.error('Signing needs the public SHA-1 thumbprint of an installed certificate.')
    if args.certificate_thumbprint and not args.signtool:
        parser.error('Pass the path to signtool with a signing certificate.')
    if not args.timestamp_url.startswith('https://'):
        parser.error('Use an HTTPS timestamp authority URL.')
    if TOOLS.is_dir():
        sys.path.insert(0, str(TOOLS))
        os.environ['PYTHONPATH'] = str(TOOLS) + os.pathsep + os.environ.get('PYTHONPATH', '')
    try:
        import PyInstaller.__main__
        import tzdata  # noqa: F401 — requires a bundled timezone database on Windows.
    except ImportError:
        parser.error('Install requirements-build.txt into .build-tools/python first.')
    if not args.skip_tests:
        run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
        node = shutil.which('node') or r'C:\Program Files\nodejs\node.exe'
        if not Path(node).is_file():
            parser.error('Node is required for frontend build checks, not for the buyer application.')
        run([node, '--test', *sorted((ROOT / 'tests').glob('*.cjs'))])
    source_names = ('index.html', 'server.py', 'launcher.py', 'VERSION',
                    'installer/Homeboard.nsi', 'installer/make_icon.py', 'scripts/build_windows.py',
                    'requirements-build.txt', 'release/Quickstart.txt', 'THIRD_PARTY_NOTICES.md')
    source_hashes = {name: sha(ROOT / name) for name in source_names}
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    run([sys.executable, ROOT / 'installer' / 'make_icon.py'])
    icon = ROOT / 'installer' / 'homeboard.ico'
    major, minor, patch = map(int, version.split('-')[0].split('.'))
    candidate = re.search(r'(\d+)$', version.split('-', 1)[1]) if '-' in version else None
    quad = (major, minor, patch, int(candidate.group(1)) if candidate else 0)
    if any(value > 65535 for value in quad):
        parser.error('Windows version components must fit 16 bits.')
    version_file = BUILD / 'version_info.txt'
    version_file.write_text('VSVersionInfo(ffi=FixedFileInfo(filevers=' + repr(quad) + ',prodvers=' + repr(quad)
        + ',mask=0x3f,flags=0x2,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=['
        + "StringFileInfo([StringTable('040904B0',[StringStruct('ProductName','Homeboard'),"
        + "StringStruct('FileDescription','Homeboard family command center'),"
        + "StringStruct('ProductVersion'," + repr(version) + "),StringStruct('FileVersion'," + repr('.'.join(map(str, quad)))
        + "),StringStruct('OriginalFilename','Homeboard.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])\n",
        encoding='utf-8')
    PyInstaller.__main__.run([
        '--noconfirm', '--onedir', '--windowed', '--noupx', '--name', 'Homeboard',
        '--distpath', str(BUILD / 'bundle'), '--workpath', str(BUILD / 'work'),
        '--specpath', str(BUILD / 'spec'), '--paths', str(ROOT),
        '--hidden-import', 'server', '--collect-data', 'tzdata',
        '--add-data', str(ROOT / 'index.html') + os.pathsep + '.',
        '--add-data', str(ROOT / 'VERSION') + os.pathsep + '.',
        '--icon', str(icon), '--version-file', str(version_file), str(ROOT / 'launcher.py')])
    bundle = BUILD / 'bundle' / 'Homeboard'
    for src, dest in [('release/Quickstart.txt', 'Quickstart.txt'),
                      ('THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md')]:
        shutil.copy2(ROOT / src, bundle / dest)
    (bundle / 'RELEASE_STATUS.txt').write_text('Homeboard ' + version + '\nRelease candidate; not cleared for public sale.\n'
        + ('Publisher signing requested; verify signatures and complete seller checklist.\n' if args.signtool else 'Unsigned build.\n'), encoding='utf-8')
    collect_notices(bundle)
    nsis_copying = args.nsis.parent / 'COPYING'
    if nsis_copying.is_file():
        shutil.copy2(nsis_copying, bundle / '_internal' / 'licenses' / 'NSIS-COPYING.txt')

    def sign(artifact):
        if args.signtool:
            run([args.signtool, 'sign', '/sha1', args.certificate_thumbprint, '/fd', 'SHA256',
                 '/tr', args.timestamp_url, '/td', 'SHA256', artifact])
            run([args.signtool, 'verify', '/pa', '/v', artifact])

    sign(bundle / 'Homeboard.exe')
    if any(sha(ROOT / name) != digest for name, digest in source_hashes.items()):
        raise RuntimeError('Source changed during the build. Rebuild once all source edits are complete.')
    manifest = {'product':'Homeboard', 'version':version, 'target':'windows-x64',
        'releaseStatus':'release-candidate', 'signedByBuild':bool(args.signtool),
        'sources':source_hashes,
        'tools':{'python':sys.version.split()[0], 'PyInstaller':importlib.metadata.version('PyInstaller'),
                 'tzdata':importlib.metadata.version('tzdata'), 'NSIS':'3.13'},
        'files':[{'path':f.relative_to(bundle).as_posix(),'size':f.stat().st_size,'sha256':sha(f)}
                 for f in sorted(bundle.rglob('*')) if f.is_file()]}
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    installer = OUT / f'Homeboard-Setup-{version}-windows-x64.exe'
    run([args.nsis, '/V2', '/INPUTCHARSET', 'UTF8', f'/DAPP_VERSION={version}', '/DAPP_VERSION_QUAD=' + '.'.join(map(str,quad)),
         f'/DBUNDLE_DIR={bundle}', f'/DOUTPUT_FILE={installer}', f'/DAPP_ICON={icon}', ROOT / 'installer' / 'Homeboard.nsi'])
    sign(installer)
    portable = OUT / f'Homeboard-Portable-{version}-windows-x64.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED) as archive:
        for f in sorted(bundle.rglob('*')):
            if f.is_file(): archive.write(f,'Homeboard/'+f.relative_to(bundle).as_posix())
    artifacts = {'product':'Homeboard','version':version,'target':'windows-x64','releaseStatus':'release-candidate',
                 'signedByBuild':bool(args.signtool),
                 'sources':source_hashes,
                 'artifacts':[{'file':f.name,'size':f.stat().st_size,'sha256':sha(f)} for f in (installer,portable)]}
    (OUT / f'Homeboard-{version}-windows-x64.manifest.json').write_text(json.dumps(artifacts,indent=2)+'\n',encoding='utf-8')
    (OUT / f'Homeboard-{version}-windows-x64.sha256').write_text(
        ''.join(sha(f)+'  '+f.name+'\n' for f in (installer,portable)),encoding='ascii')
    print(json.dumps(artifacts,indent=2))


if __name__ == '__main__':
    main()
