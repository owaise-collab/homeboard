## Free, open-source Homeboard for your home

Homeboard is free under the MIT license. No payment, vendor account or activation is required.

### Choose your download

| Computer | Download | Start here |
| --- | --- | --- |
| Windows 10/11 x64 | Setup EXE | Run Setup and open Homeboard. |
| macOS 15+ Apple Silicon | macos-arm64 DMG | Open the disk image, drag Homeboard into Applications, then open it. |
| macOS 15+ Intel | macos-x64 DMG | Open the disk image, drag Homeboard into Applications, then open it. |
| Linux x64 | linux-x64 tar.gz | Extract it and run `sh install.sh`. |
| Linux arm64 | linux-arm64 tar.gz | Extract it and run `sh install.sh`. |

Linux targets Ubuntu 22.04 or compatible glibc 2.35+ desktop systems. Phones and TVs use the browser dashboard; they do not install a server package. Other systems can use the source or Docker instructions.

Every native package includes Python and the timezone database. The first launch starts your local server and opens the guided household setup. Keep the host computer awake and signed in for other devices to connect.

These are unsigned community previews. macOS packages are not Apple-notarized; operating-system security controls may require manual review or block launching. No instruction asks you to turn off Gatekeeper, antivirus or your firewall. See the installation guide for the source/Docker alternative.

The release workflow builds on each native platform and tests the actual frozen executable: first use, recovery-code creation, automatic backup, duplicate launch, graceful stop and restart. It does not certify every Linux distribution, TV browser or clean-machine installer path.

[Installation and platform requirements](https://github.com/owaise-collab/homeboard/blob/main/release/README.md) · [Everyday guide](https://github.com/owaise-collab/homeboard/blob/main/docs/EVERYDAY.md)
