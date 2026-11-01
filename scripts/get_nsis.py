"""Fetch the pinned vendor NSIS ZIP from a checksum-verified registry envelope."""
from pathlib import Path
import hashlib
import io
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ZIP_SHA = 'ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8'
PACKAGE_SHA = 'c3597a5bbb40521bad9e762b3175b8bcde4768fb8a51376471a3d8293a2e86f2'
URL = 'https://community.chocolatey.org/api/v2/package/nsis.portable/3.13.0'

def main():
    tools = ROOT / '.build-tools'
    tools.mkdir(exist_ok=True)
    archive = tools / 'nsis-3.13.zip'
    content = archive.read_bytes() if archive.is_file() else b''
    if hashlib.sha256(content).hexdigest() != ZIP_SHA:
        with urllib.request.urlopen(URL, timeout=45) as response:
            package = response.read(10 * 1024 * 1024 + 1)
        if len(package) > 10 * 1024 * 1024 or hashlib.sha256(package).hexdigest() != PACKAGE_SHA:
            raise RuntimeError('NSIS registry envelope checksum mismatch.')
        # Do not execute the registry's installation script. Its embedded ZIP
        # must independently match the publisher's original SourceForge hash.
        with zipfile.ZipFile(io.BytesIO(package)) as envelope:
            content = envelope.read('tools/nsis-3.13.zip')
        if hashlib.sha256(content).hexdigest() != ZIP_SHA:
            raise RuntimeError('Original vendor NSIS ZIP checksum mismatch.')
        archive.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        for item in bundle.infolist():
            if not (tools / item.filename).resolve().is_relative_to(tools.resolve()):
                raise RuntimeError('Unsafe compiler archive path.')
        bundle.extractall(tools)
    if not (tools / 'nsis-3.13/makensis.exe').is_file():
        raise RuntimeError('Verified compiler archive is incomplete.')
    print('Verified official NSIS 3.13 compiler ZIP: ' + ZIP_SHA)

if __name__ == '__main__':
    main()
