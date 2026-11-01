# Reproducible Windows candidate build

Build on 64-bit Windows with 64-bit Python 3.13. Buyers do not need these tools. The compiler/tooling stays in the checkout and is not installed globally.

The public MIT-licensed source project is [owaise-collab/homeboard](https://github.com/owaise-collab/homeboard). Its **Check and build Homeboard** workflow checks pushes and pull requests. To build a review candidate, open **Actions → Check and build Homeboard → Run workflow** with repository access. The manual job verifies the pinned NSIS ZIP hash, compiles and smoke-tests an unsigned candidate, then retains the installer/ZIP/manifests as the `Homeboard-windows-candidate` artifact for 14 days. It does not publish a public release or use code-signing credentials.

```text
python -m pip install --target .build-tools/python -r requirements-build.txt
```

Download the **official portable NSIS 3.13 ZIP** from its [publisher project](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/) and extract its `nsis-3.13` directory under `.build-tools`. This build used the publisher's `nsis-3.13.zip` with SHA-256 `ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8`; that records the downloaded archive, not an independent publisher signature attestation.

```text
python scripts/build_windows.py
```

The builder runs backend/frontend tests, bundles the launcher, server, HTML and timezone data with PyInstaller, collects available runtime license notices, then invokes portable NSIS. Outputs are in `release/artifacts`: a Setup EXE, portable ZIP, SHA-256 file and artifact manifest. Source packaging is separate.

```text
python scripts/smoke_windows.py
python scripts/package_release.py
```

The frozen-app smoke check verifies bundled file hashes and recorded source hashes, starts a fresh isolated profile under ignored `.build/smoke`, checks the first-run API and both page routes, confirms worker reuse, creates a test household in a non-UTC timezone, verifies the recovery response and first backup, then checks initialization survives a graceful restart. It stops only its own worker. Rebuild after source edits; the builder refuses source changes during compilation. The smoke check does not run Setup or change installed app registration. Installer lifecycle checks still need a clean Windows VM. The source archive includes only explicitly listed code, tests, and documentation; it has its own hash manifest.

When the identical source already passed its checks, `--skip-tests` avoids rerunning them. The script can use a different portable compiler with `--nsis ABSOLUTE_PATH`. Do not use arbitrary downloaded compilers or add passwords/tokens to build arguments.

## Signing

The candidate is unsigned by default. Signing requires the owner's real code-signing identity and certificate; neither has been invented or purchased. With a certificate already installed in a protected Windows certificate store, the builder accepts `--signtool PATH --certificate-thumbprint PUBLIC_THUMBPRINT` and an HTTPS timestamp authority via `--timestamp-url`. It signs/verifies the application before packaging and the resulting Setup EXE.

Complete the signing inventory for every shipped executable, including uninstall/runtime components, and validate on a clean Windows machine. A successful build or a matching SHA-256 file is not equivalent to a trusted publisher signature, malware scan or SmartScreen reputation.

## Review before shipping

- Never include `.build-tools`, `.build`, data directories or test databases in a customer source archive.
- Do not copy the personal NAS deployment definition or private setup/recovery material into a release.
- Pin exact tool/base-image inputs for the approved shipping build; capture the runtime SBOM and required license texts.
- Complete the seller checklist. This build is a release candidate, not evidence that the product is cleared for public sale.

## Native macOS and Linux downloads

Build on the target OS/architecture using Python 3.13: `python -m pip install -r requirements-unix-build.txt`, then `python scripts/build_unix.py`. The builder freezes the runtime, preserves symlinks/executable bits, gathers notices and smoke-tests first use, recovery, backup and restart before packaging a DMG or Linux tar.gz. macOS final bundles receive only an ad-hoc integrity signature; trusted Developer ID signing/notarization requires the maintainer's own Apple identity.

**Actions → Build all desktop downloads → Run workflow** builds Windows x64, macOS Intel/Apple Silicon and Linux x64/arm64 on native runners. Only after all jobs pass does its release job publish the free preview and source archive. Standard public GitHub-hosted runners are used; no signing secrets or paid runner service is configured.
