<div align="center">

<img src="docs/assets/homeboard.svg" width="76" height="76" alt="Homeboard app icon">

# Homeboard

### A little more together.

Your family’s plans, groceries, chores and dinner ideas.<br>
One shared home, on the kitchen screen and in everyone’s pocket.

**Self-hosted** &nbsp; · &nbsp; **Windows app** &nbsp; · &nbsp; **Android + iPhone browsers**

[Get the Windows preview](https://github.com/owaise-collab/homeboard/releases/tag/v0.2.0-rc.1) · [Set up your home](#your-first-five-minutes) · [Everyday guide](docs/EVERYDAY.md) · [Screenshots](#a-place-for-every-part-of-the-day)

![Homeboard kitchen display with a large clock, today's plans, shopping and family tasks](docs/screenshots/display.jpg)

*An ordinary Sunday at the fictional Maple House. Real screens from the app; sample family data.*

</div>

## Less “what’s the plan?” More being home.

The school run. The milk you just ran out of. The library books by the door. Homeboard gives the little things a place where everyone can find them.

Leave it open in the kitchen for a quick glance. Add a plan from your phone. Keep a shared list for the next grocery run. Changes appear on your connected devices over your home network.

| A clearer day | A lighter shared load | A home of your own |
| --- | --- | --- |
| A big clock, today’s plans and the week ahead. | Groceries, assigned chores, notes and dinners in one place. | Your own PC hosts the app and stores the household database. |

## A place for every part of the day

### The morning glance

Open **Today** and see what needs your attention: family plans, the shopping shortlist and tasks due today. Each person has a color, and the next seven days sit below the daily view.

![Homeboard Today view with plans, groceries, tasks and the coming week](docs/screenshots/today.jpg)

### A week everyone can follow

Switch between **Day**, **Week** and **Month**. Add the school run once, select Monday to Friday, and let it repeat. When plans change, the visible **Edit** action lets you update one occurrence or the entire series.

![Color-coded weekly calendar showing school runs, lessons, training and family plans](docs/screenshots/calendar.jpg)

### A grocery list everyone can find

Add “oat milk, 2 cartons” when you notice it’s running low. Open the same list on your phone at home, check what is already in the cupboard, and plan the next shop together. Use categories, separate lists and quick staples; recently bought items stay handy for seven days.

Phone editing requires a connection to the home PC. Using it from the supermarket would require a separately configured secure remote connection; this preview does not provide that connection.

| The full list at home | The same home on a phone |
| --- | --- |
| ![Shopping organized by category, with quantities and recently bought items](docs/screenshots/shopping.jpg) | <img src="docs/screenshots/phone.jpg" width="280" alt="Homeboard shopping list in a phone-size browser with bottom navigation"> |

### Small jobs, shared fairly

Assign a task to a family member and give it a due date. Daily and weekly chores can repeat: completing one creates the next scheduled occurrence and keeps the completed one in history.

![Family tasks with owners, due dates and repeating schedules](docs/screenshots/tasks.jpg)

**And the little extras:** leave a family note, decide what’s for dinner, choose Clear, Warm or Night, and keep sensitive event titles off the kitchen display with **Show only “Busy” on the TV**.

<details>
<summary>Prefer a darker kitchen screen? Take a look at Night.</summary>

![The Night theme on the kitchen display](docs/screenshots/night.jpg)

</details>

## Your first five minutes

1. **Install.** Open [the Windows preview release](https://github.com/owaise-collab/homeboard/releases/tag/v0.2.0-rc.1) and download `Homeboard-Setup-0.2.0-rc.1-windows-x64.exe`. Run Setup and choose your shortcut/startup options.
2. **Make it yours.** Open Homeboard on that PC. The welcome flow asks for a household name, time zone, owner account, family profiles and starting style. Save the recovery kit when it appears.
3. **Add something real.** A school run, tomorrow’s appointment and a few groceries are a good start. Nothing comes prefilled with someone else’s family data.
4. **Bring your phones.** Open **Help → Connect your devices**. On the same home Wi-Fi, enter the address shown there in your Android or iPhone browser. Create separate adult sign-ins under **Settings → Household access**.
5. **Put it in the kitchen.** Create a **Display** account in Settings, open the same address with `/display` on the TV, and sign in with that account. It has read-only access; adults keep editing from their phones.

<div align="center">
<img src="docs/screenshots/setup.jpg" width="720" alt="Homeboard's first-run welcome screen with a five-step setup flow">
</div>

**No Python, Docker or terminal needed on the buyer’s PC.** The Windows package includes its runtime and creates its data folders automatically. The optional startup shortcut runs after your Windows account signs in.

The hosting PC needs to stay **on, signed in and awake**. Your other devices need to be able to reach it on the home network. If Windows asks about network access, use your private home network. See the [connection checklist](release/OPERATIONS.md) if a device cannot connect.

> **Current build: 0.2.0-rc.1, Windows x64 preview.** The installer is unsigned and intended for controlled household testing. See [release status](#release-status) before distributing it or taking payments.

## Built for your own home

| You want to… | Homeboard provides |
| --- | --- |
| Keep everyone looking at the same plan | A shared SQLite database, sign-in accounts and live updates between open devices. |
| Use a spare kitchen screen | A dedicated display route, large clock and server-enforced read-only Display accounts. |
| Keep ordinary plans out of the cloud | Local storage and core use over your home network without internet access. |
| Get started without a home-lab project | A Windows installer with a bundled runtime and guided first use. |
| Keep your household when updating | Data stored separately from application files, automatic database backups and a manual backup action. |
| Recover a forgotten owner password | A saved, single-use recovery code that rotates after use. |

Family **profiles** give calendar entries and chores a name and color. **Sign-in accounts** control access. You can have a profile for a child without giving them a sign-in.

## A few useful answers

**Does everyone need to install an app?** Only the hosting Windows PC. Phones and the kitchen screen use their browsers.

**Can I use a TV’s built-in browser?** Yes, when its browser engine supports the app. TV compatibility varies; if yours is too old, a small HDMI browser player is an alternative. Test your actual TV during the preview.

**Does it work without internet?** Core household features work while devices can reach the hosting PC on the local network. This edition does not save edits made while a device is disconnected.

**Will it remind me when the browser is closed?** Reminders are shown while the page is open. Background push notifications are not included.

**Can I use it away from home or connect Google/Apple Calendar?** Remote access and external calendar synchronization are not included in this preview. Do not forward the app’s port directly to the internet. See [networking and HTTPS](release/OPERATIONS.md).

**Where does my data live?** `%LOCALAPPDATA%\Homeboard`. Application files live separately in `%LOCALAPPDATA%\Programs\Homeboard`. Ordinary uninstall retains your data; make a backup before updates.

## Go a little deeper

| For your family | For building and maintaining Homeboard |
| --- | --- |
| [Everyday walkthrough](docs/EVERYDAY.md) | [Windows build instructions](release/BUILDING.md) |
| [Buyer installation guide](release/README.md) | [Backup, restore and update operations](release/OPERATIONS.md) |
| [Printable quick start](release/Quickstart.txt) | [Changes in this version](CHANGELOG.md) |
| [Connection and recovery help](release/OPERATIONS.md) | [Third-party notices](THIRD_PARTY_NOTICES.md) |

The interface is one self-contained HTML file with no CDN dependency. The server uses Python and SQLite. The Windows package bundles the runtime using PyInstaller and a per-user NSIS installer. Docker Compose is also provided for experienced self-hosters; its safe starting configuration binds to loopback.

The [Windows workflow](.github/workflows/windows.yml) runs checks on pushes and pull requests. Maintainers can run **Actions → Check and build Homeboard → Run workflow** to produce candidate installer artifacts. [Source packaging](scripts/package_release.py) uses an explicit allowlist and SHA-256 manifest to exclude household data and personal deployment files.

## Release status

Homeboard is a working release candidate, not a certified public-sale release. The packaged app has passed 54 Python tests, 51 JavaScript tests, and frozen-app checks for first-use setup, recovery-code creation, backup, worker reuse and restart. These checks do not replace testing Setup, upgrades and uninstall on a clean Windows machine.

Before a paid general release, complete publisher signing, production serving and independent security review, trusted HTTPS/device testing, runtime license review, seller terms and the [seller checklist](release/SELLER-CHECKLIST.md). The working name and visual identity also need clearance. No commercial license or legal ownership assignment is supplied in this repository.

<div align="center">
<br>
<strong>Your home. Your data. A little more together.</strong>
</div>
