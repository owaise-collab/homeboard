"""Check a frozen Homeboard bundle in a new isolated storage profile."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def smoke(bundle: Path) -> dict:
    bundle = bundle.resolve()
    executable = bundle / 'Homeboard.exe'
    profile = ROOT / '.build' / 'smoke' / uuid.uuid4().hex
    profile.mkdir(parents=True)
    if sys.platform != 'win32':
        raise RuntimeError('The Windows bundle smoke check requires Windows.')
    manifest = json.loads((bundle / 'build-manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest.get('sources', {}).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, 'Rebuild changed source: ' + name
    for item in manifest['files']:
        path = (bundle / item['path']).resolve()
        if not path.is_relative_to(bundle) or not path.is_file():
            raise AssertionError('Missing or unsafe manifest member')
        assert path.stat().st_size == item['size'], item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
    command = [str(executable), '--background', '--app-dir', str(profile)]
    run_options = {'check': True, 'timeout': 45, 'creationflags': subprocess.CREATE_NO_WINDOW}
    try:
        subprocess.run(command, **run_options)
        config = json.loads((profile / 'launcher.json').read_text(encoding='utf-8'))

        def get(path):
            connection = http.client.HTTPConnection('127.0.0.1', config['port'], timeout=5)
            try:
                connection.request('GET', path)
                response = connection.getresponse()
                body = response.read()
                assert response.status == 200, (path, response.status)
                return body
            finally:
                connection.close()

        health = json.loads(get('/api/health'))
        assert health['ok'] and health['product'] == 'homeboard'
        assert health['version'] == manifest['version']
        assert health['instance_id'] == config['instance_id']
        product = json.loads(get('/api/product'))
        assert product['version'] == manifest['version']
        assert product['setupRequired'] is True and product['localSetupAvailable'] is True
        expected_html = (bundle / '_internal' / 'index.html').read_bytes()
        assert get('/') == expected_html
        assert get('/display') == expected_html
        subprocess.run(command, **run_options)
        assert json.loads((profile / 'launcher.json').read_text()) == config
        assert json.loads(get('/api/health'))['instance_id'] == config['instance_id']
        setup_key = json.loads(get('/api/setup/local'))['setupKey']
        connection = http.client.HTTPConnection('127.0.0.1', config['port'], timeout=10)
        try:
            connection.request('POST', '/api/setup', body=json.dumps({
                'setupKey': setup_key, 'name': 'Test owner', 'username': 'smoke_owner',
                'password': secrets.token_urlsafe(30),
                'household': {'name': 'Packaging smoke household', 'timezone': 'America/New_York',
                              'hour24': False, 'theme': 'premium'},
                'members': [{'name': 'Test member', 'color': 'sage'}],
            }), headers={'Content-Type': 'application/json', 'Origin': f"http://127.0.0.1:{config['port']}"})
            response = connection.getresponse()
            result = json.loads(response.read())
            assert response.status == 201, 'Frozen first-run setup failed'
            assert result['authenticated'] is True and result['recoveryCode']
            assert result['backupCreated'] is True
        finally:
            connection.close()
        assert json.loads(get('/api/product'))['setupRequired'] is False
        subprocess.run([str(executable), '--stop', '--app-dir', str(profile)], **run_options)
        subprocess.run(command, **run_options)
        product = json.loads(get('/api/product'))
        assert product['setupRequired'] is False and product['localSetupAvailable'] is False
        assert (profile / 'data' / 'family.sqlite3').is_file()
        assert list((profile / 'data' / 'backups').glob('family-backup-*.sqlite3'))
        assert (bundle / '_internal' / 'tzdata' / 'zoneinfo' / 'America' / 'New_York').is_file()
        assert not (bundle / 'data').exists()
        return {'version': manifest['version'], 'verifiedFiles': len(manifest['files']),
                'freshSetup': True, 'pageMatchesBundle': True, 'workerReuse': True,
                'onboardingAndBackup': True, 'setupSurvivesRestart': True,
                'dataOutsideApplication': True, 'gracefulStop': True}
    finally:
        subprocess.run([str(executable), '--stop', '--app-dir', str(profile)], **run_options)
        # Leave the isolated profile in ignored .build/smoke for diagnostics.
        # No customer data or installed Windows account state is touched.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / '.build' / 'windows' / 'bundle' / 'Homeboard')
    args = parser.parse_args()
    print(json.dumps(smoke(args.bundle), indent=2))


if __name__ == '__main__':
    main()
