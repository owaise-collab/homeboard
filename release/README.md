# Homeboard for Windows — release candidate

Homeboard keeps family plans, shopping, tasks, notes and dinner plans in one shared local space. This edition targets **64-bit Windows 10/11**, with a self-contained runtime and a guided first-use experience. The working product name and commercial terms are not cleared for public sale yet.

## Install and begin

Run `Homeboard-Setup-0.2.0-rc.1-windows-x64.exe`. Installation is for the current Windows account and does not require Python, Docker or a terminal. The optional startup shortcut starts Homeboard after that account signs in; it is not a system service that runs before login.

Open Homeboard and complete the household setup. Choose a strong owner password and save the recovery kit separately. Keep personal adult accounts separate from the display account used on a kitchen screen.

The packaged runtime does not need internet for core household use after installation. The hosting PC must stay on, signed in and awake. Other devices require network access to it; Windows private-network firewall and trusted HTTPS installation remain part of the supported product setup, not something the UI alone can guarantee.

The optional ZIP can run without Setup, but uses the same per-user data location by default; it is not a USB-contained household database.

## Files and privacy

- Application binaries: `%LOCALAPPDATA%\Programs\Homeboard`
- Database, configuration, logs and backups: `%LOCALAPPDATA%\Homeboard`
- Ordinary uninstall retains customer data and backups.
- No vendor account, mandatory cloud synchronization or online license activation is implemented.
- Customer packages contain no household database, setup key, recovery code, NAS password or personal deployment configuration.

## Update and recover

Back up before updating. Run a newer installer; it requests a graceful stop of the current server, replaces application files and leaves the separate data directory intact. Retain the previous installer and a pre-update database snapshot until the update has passed household testing.

For account recovery, use the recovery kit. For machine/disk recovery, restore a verified database snapshot into an isolated instance first. A state JSON export contains household records; it is not a full account/session backup. See [Operations](OPERATIONS.md).

## Candidate limits

This artifact is unsigned. It does not establish publisher identity or clean-machine approval, and no instruction here asks buyers to disable security protections. The server currently uses Python's standard-library HTTP server; its [official documentation](https://docs.python.org/3/library/http.server.html) says it is not recommended for production. A reverse proxy helps with HTTPS but does not complete a production security review.

The present build is for controlled household pilots. Before a general paid launch, complete [the seller checklist](SELLER-CHECKLIST.md), including signing, production serving, licensing, supported-device validation and a defined support/recovery process.
