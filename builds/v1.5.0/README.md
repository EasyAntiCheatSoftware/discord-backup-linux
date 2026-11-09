# Version 1.5.0

Account-specific time estimates, detailed warning summaries, a same-machine/cross-machine unlock guide, and isolated terminal screenshots.

## Download

- `discord-backup-linux-1.5.0.tar.gz`: full application source, tests, launchers, documentation and Arch build tooling. Extract and run `./run.sh` with Python 3.10+, GnuPG 2.4+ and Requests installed.
- `discord-backup-linux-1.5.0-1-any.pkg.tar.zst`: unsigned Arch package. Install with `sudo pacman -U ./discord-backup-linux-1.5.0-1-any.pkg.tar.zst`, then run `discord-backup`.
- `SHA256SUMS`: SHA-256 digests for both artifacts. Download them into one directory and run `sha256sum -c SHA256SUMS`. Checksums verify consistency, not publisher identity.

The source archive contains the complete runtime and screenshot generator. The generated PNG documentation assets are in this directory's `screenshots` folder and in the repository; they are not required to run the app.

## Changes

The ETA uses the selected account's memberships and the current run's HTTP/encryption timings. It updates for remaining work, known invitation waits and serial-mode changes, without extra API calls or a persistent account-history cache. Unknown future limits or slow responses can change the guess. A failed membership lookup explicitly disables a numeric estimate.

Final summaries list every warning and affected/unattempted section, including interrupted backups. Invite warnings explain that collected membership/contact data remains available. Completed data stays encrypted; missing data requires a new backup.

See [the complete unlock guide](../../UNLOCK_BACKUP.md) for the menu/CLI on the same or another Linux machine, or GnuPG without the app on Linux/macOS/Windows. No Discord token is needed to unlock/export.

The three PNGs show real CLI output using synthetic transports inside isolated pseudo-terminals and a fixed neutral renderer. They capture no personal desktop, terminal preferences or account data. Demo backups and credentials are temporary and are removed after capture.

## Validation

All 91 offline tests passed locally and during makepkg. The source archive matches its 45-file publication manifest, every Python file parses with Python 3.10 syntax, the Arch build passed source checksum validation, and the extracted package passed version and encrypted-export smoke checks. Check the repository's GitHub Actions for Python 3.10/3.14 CI results. Live Discord behavior and the Windows PowerShell instructions were not exercised during this Linux update.

The public package's installed files were compared against reviewed source, private builder identity/paths and host package inventory were removed, and `.MTREE` regenerated. Source/archive metadata uses normalized ownership, modes and timestamps. The reduced `.BUILDINFO` is not a complete reproducible-build environment record.
