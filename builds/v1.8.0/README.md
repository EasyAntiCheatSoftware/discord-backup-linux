# Version 1.8.0

The main menu now has Back up, Recover and Exit. Recovery contains the export, bot hub, folder restore and GIF restore options. Scheduling, credential setup, listing and diagnostics are available via `--help`. Backups still include the same data and support standalone decryption.

The terminal updates the ETA on one line. The summary shows the first three warnings and points to `inspect` or the recovery page for the full list. The shorter README links the full usage guide.

## Build an Arch package

From the source checkout, run:

```sh
sudo pacman -S --needed base-devel python gnupg python-requests
./build-arch.sh
sudo pacman -U dist/arch/discord-backup-linux-1.8.0-1-any.pkg.tar.zst
```

The build generates a source archive and runs the test suite. Run `python3 tools/release.py` to create only the source archive. [Historical downloads](../)

[Setup and recovery](../../README.md) · [All commands and backup contents](../../docs/USAGE.md) · [Portable unlock guide](../../UNLOCK_BACKUP.md) · [Release history](../../CHANGELOG.md)
