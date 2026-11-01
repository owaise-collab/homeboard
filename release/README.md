# Install Homeboard — free desktop preview

Homeboard is free, open source and licensed under MIT. Native desktop downloads contain their own Python runtime. Download from [Homeboard releases](https://github.com/owaise-collab/homeboard/releases); no account or payment is required for public downloads.

## Windows 10/11 x64

Run the Setup EXE. Choose optional desktop/login shortcuts and open Homeboard. Application files install under `%LOCALAPPDATA%\Programs\Homeboard`. Login startup begins after that Windows account signs in; it is not a system service.

## macOS 15 or later

Choose the **arm64** DMG for Apple Silicon (M-series) or **x64** for an Intel Mac. Open the DMG, drag Homeboard.app into Applications (or your own `~/Applications` folder), then open it.

The preview is ad-hoc signed for bundle integrity but is **not Developer ID signed or Apple-notarized**. Gatekeeper or managed-device policy may block it. Do not turn off Gatekeeper. Use the source/Docker alternative if your Mac requires a trusted publisher signature. First launch may also ask for local-network permission so other household devices can reach the server.

Optional automatic startup after login can be enabled from Terminal after installation:

```sh
"/Applications/Homeboard.app/Contents/MacOS/Homeboard" --enable-startup
```

Use `--disable-startup` to remove that login agent or `--stop` to save and stop the server. If installed under your own Applications folder, use that path instead. Updating the app keeps household data separately; stop it before replacing the application.

## Linux x64 or arm64

Choose the archive matching `uname -m`: **x64** for x86_64, **arm64** for aarch64/arm64. The build baseline is Ubuntu 22.04, glibc 2.35+. It needs a desktop browser to open automatically. Musl-based distributions and older glibc systems should use a compatible container or source build.

Extract the archive, open a terminal in its extracted directory, and run:

```sh
sh install.sh
```

The installer verifies bundled file hashes, installs for your user under `~/.local/opt/homeboard`, adds Homeboard to the application menu and opens it. It asks whether to start after login. No sudo, Python installation or Docker is needed. Updates keep versioned application folders and switch the current link after a safe server stop.

To stop:

```sh
"$HOME/.local/opt/homeboard/current/Homeboard" --stop
```

Use `--enable-startup` or `--disable-startup` with that executable to change login startup. No system-wide service or firewall rule is silently installed.

## Your first launch

Open Homeboard on the hosting computer. Follow the welcome flow for household name, time zone, owner account, family profiles and appearance. Save the recovery kit. Then use **Help → Connect your devices** for the LAN address, and give phones adult accounts and the TV a read-only Display account.

The host must stay on, awake and signed in. Phones/TVs need network access to it; allow private home-network access when the operating system asks. A guest Wi-Fi network may isolate clients. HTTPS and remote access need separate configuration; never forward the app port directly to the internet.

## Your data

| Host | Data, configuration, logs and backups |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Homeboard` |
| macOS | `~/Library/Application Support/Homeboard` |
| Linux | `$XDG_DATA_HOME/homeboard`, normally `~/.local/share/homeboard` |

The database is `data/family.sqlite3`; snapshots are in `data/backups`. These folders are separate from application binaries. Keep recovery codes and backups private, and copy backups to another physical drive.

Windows uninstall keeps the data folder. On macOS, disable login startup, stop Homeboard and remove the app; the separate data folder remains. On Linux, disable login startup, stop Homeboard and remove its application-menu entry and versioned app folder only; retain the data folder. Never delete the only copy of a household to repair an installation.

## Run from source or Docker

On a supported Python 3.13 system, extract or clone the source, install timezone data, and launch:

```sh
python -m pip install tzdata==2026.6
python launcher.py
```

The launcher opens local setup without a manual setup key. On Linux use `python3` if that is the Python 3 command. No native desktop integration is installed by this source command.

For experienced server operators, `docker compose up -d --build` builds the provided Compose app. Its starting configuration binds to loopback for safety. For a direct `python server.py` or Docker deployment, read `data/setup-key.txt` on that server and enter it in first-time setup; desktop localhost auto-claim is not enabled by default for those deployments. Configure a deliberate LAN/TLS boundary before connecting remote clients.

## Preview limits

These native build targets are tested in CI; that does not certify every desktop distribution, installer upgrade path or TV model. No closed-app reminders, disconnected editing, external calendar synchronization or built-in remote access is provided. See [operations](OPERATIONS.md), [everyday use](../docs/EVERYDAY.md) and [release checks](SELLER-CHECKLIST.md).
