# Homeboard operations

## Availability and network

The Windows edition starts for the current user after login when its optional Startup shortcut is enabled. It runs the server in the background; closing the browser does not stop it. It is not an always-on Windows service. The PC must stay awake and have a stable home-network address for other devices to use it.

Allow access only from the intended private household network. Do not forward the application port through an internet router. Do not offer universal remote access as an included feature. Guest Wi-Fi and client isolation can prevent devices from connecting even when the host works locally.

Phone home-screen installation, service workers and browser capabilities may need trusted HTTPS. A local certificate authority requires trust installation on every client, including the TV if it supports it. The Caddy [automatic HTTPS guide](https://caddyserver.com/docs/automatic-https) explains the distinction between locally issued certificates and public certificates. Do not ask customers to bypass certificate warnings.

The current backend uses Python `http.server`. Its [official warning](https://docs.python.org/3/library/http.server.html) requires production-serving review: replace the serving layer or complete a documented production security design/review before representing the product as production hardened. A Windows installer does not itself solve that issue.

## Backups

The application makes consistent local SQLite snapshots. Keep a second copy on another physical device; a backup on the failed PC cannot recover a disk loss. Include the whole customer data directory in your normal protected backup process. It contains account/session information and must be treated as private.

An owner can export a household JSON backup for records. It does not replace the full SQLite snapshot for accounts. Save recovery codes separately from the hosting PC. Support must never ask for customer passwords or recovery codes.

## Restore a SQLite snapshot

Use an isolated test copy first. A full restore also restores the snapshot's historical accounts and sessions; revoke accounts or sessions that should no longer have access.

1. Use **Stop Homeboard** in the Start menu, then leave its browser tab closed. Do not copy over a running database.
2. In File Explorer, open `%LOCALAPPDATA%\Homeboard`. Copy this entire folder to a separate recovery location before changing anything.
3. In its `data` folder, move the current `family.sqlite3` and any `family.sqlite3-wal` / `family.sqlite3-shm` files together into a separate recovery folder. Preserve them rather than deleting them.
4. Copy the chosen `data\backups\family-backup-YYYY-MM-DD.sqlite3` snapshot into `data` and name the copy `family.sqlite3`. Keep the original snapshot untouched. The current Windows account must be able to write the restored file.
5. Open Homeboard. Check owner access, family members, recurrence, shopping, tasks, and another device before returning it to daily use.

For replacement-PC recovery, install the same supported Homeboard version, stop it, and restore the preserved profile into that Windows account's `%LOCALAPPDATA%\Homeboard`. The restored `launcher.json` may contain a port that conflicts on the replacement PC; the launcher checks available ports on startup. New machine addresses and firewall/TLS settings require separate verification. This procedure must be tested for the exact version before it is promised as supported customer recovery.

## Update and rollback

1. Confirm a recent snapshot exists and copy it outside the PC.
2. Record the installed version and retain its installer.
3. Run the new installer. It gracefully stops its own worker before replacing files; it does not kill unrelated processes.
4. Open the dashboard, verify accounts, recurrence, shopping and another device's updates.
5. If rollback is necessary, stop Homeboard, preserve the current data separately, and test the old version with the pre-update snapshot in an isolated copy. Do not overwrite the only copy of current data.

Database/schema backward compatibility is not assumed. Maintainers must test each supported upgrade path and document whether a snapshot restore is required to return to the older version.

## Uninstall

Uninstall removes the application and its current-user shortcuts/registration. It deliberately leaves `%LOCALAPPDATA%\Homeboard` untouched. A future factory-reset function needs an explicit owner-confirmed data-erasure flow. Do not add automatic recursive data deletion to the uninstaller.

## Support information

Ask for product version, Windows edition/build, browser/device model and a description of the failed action. Prefer redacted diagnostics. Do not collect full databases, family calendars, passwords, setup keys, recovery codes or entire log folders by default.

No support address, service-level agreement, refund terms or company identity has been invented. The owner must supply and approve those before launch.

## macOS and Linux profiles

The same database and backup layout is used under `~/Library/Application Support/Homeboard` on macOS and `$XDG_DATA_HOME/homeboard` (normally `~/.local/share/homeboard`) on Linux. Stop the appropriate installed executable with `--stop` before replacing/restoring database files. Use `--enable-startup` or `--disable-startup` for optional per-user login startup. There is no always-on system service. The Windows restore procedure above applies to database filenames, but use the correct profile folder for your OS and preserve the entire original profile first.

macOS: replace the stopped application without deleting its separate data directory. Linux: the installer copies verified, versioned bundles, safely stops the owned worker and atomically switches a current link; application-menu and startup paths follow that link. Never use an older binary with newer household data without testing a copied snapshot first.
