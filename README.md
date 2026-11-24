<div align="center">

# Discord Backup Linux

Encrypted Discord account backups and guided recovery for Linux.

[![Offline checks](https://github.com/EasyAntiCheatSoftware/discord-backup-linux/actions/workflows/check.yml/badge.svg)](https://github.com/EasyAntiCheatSoftware/discord-backup-linux/actions/workflows/check.yml)
![Linux](https://img.shields.io/badge/Platform-Linux-1793D1?logo=linux&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
[![AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-8b5cf6)](LICENSE)

**[Quick start](#quick-start) · [Arch build](builds/v1.8.0) · [Unlock a backup](UNLOCK_BACKUP.md) · [Usage guide](docs/USAGE.md)**

![Terminal demo showing the whole-account ETA and backup summary](builds/v1.8.0/screenshots/demo.gif)

</div>

Inspired by [ItsChasa's Discord-Backup](https://github.com/itschasa/Discord-Backup).

## Quick start

On Arch Linux, install the dependencies and run the app from source.

```sh
sudo pacman -S --needed python gnupg python-requests
git clone https://github.com/EasyAntiCheatSoftware/discord-backup-linux.git
cd discord-backup-linux
./run.sh
```

Other Linux distributions need Python 3.10+, GnuPG 2.4+ and Requests. Run `python3 tools/install_desktop.py` for a desktop shortcut or `./build-arch.sh` to build an Arch package. [Arch build and install steps](builds/v1.8.0)

[View the terminal menu](builds/v1.8.0/screenshots/menu.png) · [View a partial backup summary](builds/v1.8.0/screenshots/warnings.png)

## Back up

Choose **1 · Back up account**. Scan installed Discord apps, opt in to browser scanning, or enter a token in a hidden prompt. Choose whether to create invitations and set a backup passphrase of at least 12 characters.

> [!IMPORTANT]
> Keep your backup passphrase somewhere safe. It unlocks the file on any machine, and there is no reset.

| What gets saved | How you can use it |
| --- | --- |
| Server and group memberships, with optional invitations | Follow saved invite links |
| Friends, blocked users, requests, and DM contacts | Find profiles and manage relationships |
| Profile images and bio | Export and reapply them |
| Server folders and GIF settings | Preview and apply a settings restore |

The app stores encrypted files in `~/.local/share/discord-backup-linux/backups` by default. It shows a whole-account estimate before the main backup and updates it on one line. A first run gives a rough estimate, which adjusts as Discord responds.

## Recover

Choose **2 · Recover a backup** and pick a recent file or enter a custom file or folder path. After unlocking, you can:

- Export an offline recovery page with saved links, profile files, and warnings.
- Use your own bot to organize links and contacts in private Discord channels. You still join servers and send friend requests yourself. [Bot setup and limits](docs/RECOVERY_HUB.md)
- Preview a folder or GIF settings restore. Applying it saves an encrypted rollback first. [Settings restore details](docs/USAGE.md#settings-restores)

**Partial backups** keep the data collected so far in an encrypted `-partial.bkup` file. The terminal summary shows up to three warnings. The recovery page and `inspect` show the full list.

**Moving to another machine?** Copy the encrypted file and use the same passphrase. You can unlock it with GnuPG 2.4+ on Linux, macOS, or Windows without installing the app. [Standalone unlock instructions](UNLOCK_BACKUP.md)

## Command line

```sh
./run.sh backup --no-invites
./run.sh recover /path/to/backups
./run.sh inspect /path/to/file.bkup
./run.sh --help
```

Use `discord-backup` in place of `./run.sh` if you installed the Arch package. The usage guide covers scheduled backups, account scanning, storage, and diagnostics. [All commands and advanced usage](docs/USAGE.md)

> This unofficial app uses normal account tokens and private endpoints. Discord prohibits normal-account automation and may terminate accounts that use it. [Discord policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Architecture](docs/ARCHITECTURE.md) · [Review notes](docs/REVIEW.md) · [Security](SECURITY.md) · [Attribution](NOTICE)
