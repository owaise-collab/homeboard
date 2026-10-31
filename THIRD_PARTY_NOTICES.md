# Homeboard dependency and asset inventory

This inventory does not grant rights to the Homeboard application or replace the full notices required by each distributed dependency. The seller must approve the application's own license and terms before public sale. A separate MIT license exists at the parent repository root; its intended scope for this new product must be confirmed by the owner, not inferred from folder location.

| Component | Use and provenance |
| --- | --- |
| Python and standard library | Bundled in the Windows edition; the container edition uses the Docker Official Python image. Python license history and applicable notices: https://docs.python.org/3/license.html . Preserve the notices in the chosen runtime distribution. |
| SQLite, OpenSSL and runtime libraries | Included through the selected Python distribution. Their license texts and notices must be included in the distribution inventory/SBOM for the exact built runtime. |
| tzdata | Bundled IANA timezone data for Windows. Upstream package: https://pypi.org/project/tzdata/ ; license and notices are collected from the installed package into the Windows bundle. |
| PyInstaller | Build tool and bundled bootloader. Its commercial-bundle exception is described at https://pyinstaller.org/en/stable/license.html . The build retains available installed license notices. No modification of PyInstaller is claimed. |
| NSIS | Windows installer compiler/stub. Portable official compiler archive: https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/ . The build retains its COPYING file; review notices for the selected compiler/plugins. |
| System fonts | The interface asks the operating system for installed fonts. It does not distribute Apple font files, SF Symbols, Apple logos or other vendor font assets. |
| Icons | The application uses project-authored inline line icons and a project-authored Homeboard house mark. No external JavaScript icon library is shipped by the interface. |
| Optional Caddy | A reverse-proxy configuration example may be used by server operators. Caddy is not bundled in the Windows installer; source/license: https://github.com/caddyserver/caddy/blob/master/LICENSE . |

The unrelated parent YouTube application's dependencies are not part of the customer package. There is no evidence here of trademark clearance, a registered business identity, a completed license audit or vendor endorsement. Complete the seller checklist for the actual shipping artifact.
