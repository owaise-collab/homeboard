"""Desktop integration stays within its explicit per-user locations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shlex
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('homeboard_desktop_install', ROOT / 'desktop_install.py')
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)

class DesktopInstallCase(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'tests' / '.temporary'
        base.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=base)
        self.home = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_mac_login_agent_uses_structured_arguments_and_can_be_removed(self):
        binary = self.home / 'Applications' / 'A home.app' / 'Contents' / 'MacOS' / 'Homeboard'
        path = desktop.configure_startup(binary, True, 'darwin', self.home)
        value = plistlib.loads(path.read_bytes())
        self.assertEqual(value['ProgramArguments'], [str(binary.resolve()), '--background'])
        self.assertTrue(value['RunAtLoad'])
        self.assertEqual(path.parent, self.home / 'Library' / 'LaunchAgents')
        desktop.configure_startup(binary, False, 'darwin', self.home)
        self.assertFalse(path.exists())

    def test_linux_autostart_quotes_paths_and_preserves_the_update_link(self):
        binary = self.home / 'Home with space' / 'Homeboard'
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')}):
            path = desktop.configure_startup(binary, True, 'linux', self.home)
            text = path.read_text()
            command = next(line[5:] for line in text.splitlines() if line.startswith('Exec='))
            self.assertEqual(shlex.split(command), [str(binary.resolve()), '--background'])
            self.assertIn('Terminal=false', text)
            desktop.configure_startup(binary, False, 'linux', self.home)
            self.assertFalse(path.exists())

    @unittest.skipIf(os.name == 'nt', 'Native Unix links are tested on Linux and macOS runners')
    def test_linux_install_verifies_hashes_and_preserves_household_data_on_upgrade(self):
        source = self.home / 'download'
        source.mkdir()
        executable = source / 'Homeboard'
        executable.write_bytes(b'fake frozen executable')
        manifest = {'product': 'Homeboard', 'version': '0.3.0-rc.1', 'files': [
            {'path': 'Homeboard', 'sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}]}
        (source / 'build-manifest.json').write_text(json.dumps(manifest))
        sentinel = self.home / '.local/share/homeboard/data/family.sqlite3'
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b'family data stays')
        stop = Mock()
        with patch.object(desktop.Path, 'home', return_value=self.home), patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home / '.local/share')}):
            installed = desktop.install_linux(executable, object(), stop)
            self.assertEqual(installed.read_bytes(), executable.read_bytes())
            self.assertTrue((installed.parent).is_symlink())
            self.assertTrue((self.home / '.local/share/applications/homeboard.desktop').is_file())
            desktop.install_linux(executable, object(), stop)
            self.assertEqual(sentinel.read_bytes(), b'family data stays')
            executable.write_bytes(b'changed download')
            with self.assertRaisesRegex(ValueError, 'changed'):
                desktop.install_linux(executable, object(), stop)
        self.assertEqual(stop.call_count, 2)

if __name__ == '__main__':
    unittest.main()
