"""Create an allowlisted source release, without household data or developer files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = (
    'VERSION', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md', 'README.md',
    'index.html', 'server.py', 'launcher.py', 'Dockerfile', 'compose.yaml',
    '.dockerignore', '.gitignore', 'requirements-build.txt',
    '.github/workflows/windows.yml',
    'installer/Homeboard.nsi', 'installer/make_icon.py',
    'scripts/build_windows.py', 'scripts/package_release.py', 'scripts/smoke_windows.py',
    'release/README.md', 'release/Quickstart.txt', 'release/BUILDING.md',
    'release/OPERATIONS.md', 'release/SELLER-CHECKLIST.md',
    'tests/test_server.py', 'tests/test_launcher.py', 'tests/test_release.py',
    'tests/test_dates.cjs', 'tests/test_frontend.cjs', 'tests/test_startup.cjs', 'tests/test_onboarding.cjs',
    'docs/EVERYDAY.md', 'docs/assets/homeboard.svg',
    'docs/screenshots/display.jpg', 'docs/screenshots/today.jpg',
    'docs/screenshots/calendar.jpg', 'docs/screenshots/shopping.jpg',
    'docs/screenshots/tasks.jpg', 'docs/screenshots/phone.jpg',
    'docs/screenshots/setup.jpg', 'docs/screenshots/night.jpg',
)


def create_release(root: Path, output: Path) -> dict:
    root = root.resolve()
    version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', version):
        raise ValueError('Unsafe release version')
    items = []
    payload = []
    for relative in ALLOWLIST:
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or unsafe allowlisted source: ' + relative)
        content = path.read_bytes()
        if relative in ('index.html', 'server.py', 'launcher.py', 'README.md'):
            addresses = re.findall(rb'192\.168\.\d{1,3}\.\d{1,3}', content)
            # The RFC1918 network boundary is code, not a customer's host.
            if any(address != b'192.168.0.0' for address in addresses):
                raise ValueError('Personal deployment information in customer source: ' + relative)
        items.append({'path': relative, 'size': len(content),
                      'sha256': hashlib.sha256(content).hexdigest()})
        payload.append((relative, content))
    manifest = {'product': 'Homeboard', 'version': version, 'format': 'source',
                'releaseStatus': 'release-candidate', 'files': items}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative, content in payload:
            archive.writestr(relative, content)
        archive.writestr('release-manifest.json', json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    output = args.output or ROOT / 'release' / 'artifacts' / f'Homeboard-{version}-source.zip'
    manifest = create_release(ROOT, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps({'file': str(output), 'version': manifest['version'],
                      'files': len(manifest['files']), 'sha256': digest}, indent=2))


if __name__ == '__main__':
    main()
