"""The customer source archive must never sweep in developer state or secrets."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_release', ROOT / 'scripts' / 'package_release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary_root = ROOT / 'tests' / '.temporary'
        self.temporary_root.mkdir(parents=True, exist_ok=True)

    def make_source(self, directory):
        root = Path(directory) / 'source'
        for relative in release.ALLOWLIST:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('0.2.0-rc.1\n' if relative == 'VERSION' else 'sample ' + relative, encoding='utf-8')
        for relative in ('data/state.json', '.env', 'compose.zima.yaml', 'DEPLOYMENT.md',
                         '.build-tools/token.txt', 'release/artifacts/old.zip'):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private household secret', encoding='utf-8')
        return root

    def test_only_allowlisted_files_and_verified_manifest_are_archived(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = self.make_source(directory)
            output = Path(directory) / 'candidate.zip'
            release.create_release(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(release.ALLOWLIST) | {'release-manifest.json'})
                manifest = json.loads(archive.read('release-manifest.json'))
                self.assertEqual(manifest['version'], '0.2.0-rc.1')
                for item in manifest['files']:
                    content = archive.read(item['path'])
                    self.assertEqual(item['size'], len(content))
                    self.assertEqual(item['sha256'], hashlib.sha256(content).hexdigest())
                self.assertNotIn(b'private household secret', b''.join(archive.read(name) for name in archive.namelist()))

    def test_personal_deployment_defaults_block_the_customer_release(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = self.make_source(directory)
            (root / 'server.py').write_text('host = "192.168.1.50"', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Personal deployment'):
                release.create_release(root, Path(directory) / 'bad.zip')

    def test_missing_source_fails_instead_of_silently_shipping_partial_release(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = self.make_source(directory)
            (root / 'launcher.py').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing or unsafe'):
                release.create_release(root, Path(directory) / 'bad.zip')


if __name__ == '__main__':
    unittest.main()
