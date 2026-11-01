"""Per-user desktop integration. Called only by explicit installer/startup actions."""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import re
import shutil
import sys
import uuid


def desktop_quote(value):
    value = str(value)
    if any(character in value for character in ('\n', '\r', '\0')):
        raise ValueError('A desktop executable path cannot contain line breaks.')
    return '"' + value.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$') + '"'


def desktop_entry(executable, background=False, icon=None):
    result = '[Desktop Entry]\nType=Application\nName=Homeboard\nComment=A little more together\n'
    result += 'Exec=' + desktop_quote(executable) + (' --background' if background else '') + '\n'
    result += 'Terminal=false\nCategories=Office;Calendar;\n'
    if icon:
        result += 'Icon=' + str(icon).replace('\n', '') + '\n'
    return result


def configure_startup(executable, enabled, platform=None, home=None):
    platform, home = platform or sys.platform, Path(home or Path.home())
    executable = Path(executable).resolve()
    if platform == 'darwin':
        target = home / 'Library' / 'LaunchAgents' / 'io.github.owaise-collab.homeboard.plist'
        content = plistlib.dumps({'Label': 'io.github.owaise-collab.homeboard',
            'ProgramArguments': [str(executable), '--background'], 'RunAtLoad': True,
            'ProcessType': 'Background'})
    elif platform.startswith('linux'):
        current = home / '.local' / 'opt' / 'homeboard' / 'current' / 'Homeboard'
        if current.is_file() and current.resolve() == executable:
            executable = current
        config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
        if not config.is_absolute():
            config = home / '.config'
        target = config / 'autostart' / 'homeboard.desktop'
        content = desktop_entry(executable, True).encode('utf-8')
    else:
        raise ValueError('Use Windows Setup to change its optional login shortcut.')
    if not enabled:
        target.unlink(missing_ok=True)
        return target
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_bytes(content)
    return target


def install_linux(executable, paths, stop_worker):
    """Copy a frozen, manifest-verified bundle without overwriting household data."""
    source = Path(executable).resolve().parent
    manifest_path = source / 'build-manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    version = manifest.get('version', '')
    if manifest.get('product') != 'Homeboard' or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', version):
        raise ValueError('This is not a Homeboard installation bundle.')
    for item in manifest['files']:
        path = (source / item['path']).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError('Unsafe or missing bundle file.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('The downloaded bundle is incomplete or changed: ' + item['path'])
    destination = Path.home() / '.local' / 'opt' / 'homeboard'
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = version + '-' + hashlib.sha256(manifest_bytes).hexdigest()[:12]
    installed = destination / 'versions' / stamp
    if installed.exists():
        if (installed / 'build-manifest.json').read_bytes() != manifest_bytes:
            raise ValueError('The existing installation has changed. Keep its data and use a new package.')
        for item in manifest['files']:
            path = (installed / item['path']).resolve()
            if not path.is_relative_to(installed.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('The existing installation needs repair: ' + item['path'])
    else:
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, installed, symlinks=True)
    current = destination / 'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('The Homeboard current path is not an installation link.')
    stop_worker(paths)
    temporary = destination / ('.current-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(installed, target_is_directory=True)
        os.replace(temporary, current)
    finally:
        temporary.unlink(missing_ok=True)
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    if not data.is_absolute():
        data = Path.home() / '.local' / 'share'
    applications = data / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    (applications / 'homeboard.desktop').write_text(desktop_entry(current / 'Homeboard',
        icon=current / '_internal' / 'homeboard.png'), encoding='utf-8')
    return current / 'Homeboard'
