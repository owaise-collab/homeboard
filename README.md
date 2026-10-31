# Homeboard

A shared family dashboard for a kitchen screen, phones, and a home PC. The working product name and visual identity are provisional until the seller completes trademark and asset review.

Version **0.2.0-rc.1** is a Windows release candidate. The current build is unsigned and has not passed the public-sale security and distribution checks.

## Install on Windows

1. Download the Windows x64 Setup EXE from the seller's verified release location.
2. Open Setup and choose the optional startup and desktop shortcuts.
3. Open Homeboard. Follow the household setup, create the owner account, and save the recovery kit.

Python, Docker, and a terminal are not needed on the buyer's PC. Application files install for the current Windows account; data is kept separately under `%LOCALAPPDATA%\Homeboard`. The PC must remain powered, signed in, and awake to serve other devices. Automatic startup runs after that account signs in.

The initial compatibility target is Windows 10/11 x64 and current Chrome, Edge, Firefox, Android Chrome, or iPhone Safari. Windows 10 is a compatibility target, not a promise of operating-system security support. TV browsers need device testing; browser engines and certificate handling vary. Clean-machine installation, upgrade, rollback, and uninstall are release gates, not yet a certified support matrix.

See [the buyer guide](release/README.md), [quick start](release/Quickstart.txt), and [backup, updates, and networking](release/OPERATIONS.md).

## Build and review

The backend uses the Python standard library and SQLite. The browser interface is a single HTML file with no CDN dependency. The Windows launcher bundles the runtime with PyInstaller; the per-user Setup EXE is built with NSIS.

See [Windows build instructions](release/BUILDING.md), [third-party notices](THIRD_PARTY_NOTICES.md), and [the seller release checklist](release/SELLER-CHECKLIST.md). Build tooling and artifacts stay in ignored local folders. `python scripts/package_release.py` creates a source ZIP from an explicit allowlist and includes a SHA-256 manifest; it excludes runtime data, credentials, and personal deployment files.

The private development project is [owaise-collab/homeboard](https://github.com/owaise-collab/homeboard). Repository access is required. Its Windows workflow checks pushes and pull requests; a candidate installer build starts manually from **Actions → Check and build Homeboard → Run workflow**. It produces review artifacts rather than publishing a public release.

For advanced source-only use: `python server.py`, then open the address shown by the server. The optional Compose definition binds port 8080 to loopback by default. Configure a deliberate private-network/TLS boundary before accessing it from other devices. The Python HTTP server is a candidate architecture and must receive serving-layer and security review before commercial production use; do not expose it directly to the internet.

## Commercial status

No new product license, publisher identity, ownership assignment, or commercial legal terms are supplied. The owner must decide those before public distribution or sale. Public releases also require code signing, a complete bundled-runtime notice audit, independent security review, tested recovery/upgrade paths, and published support terms. See the seller checklist for the remaining concrete gates.
