# Version 1.6.1

Input validation fixes for interactive menus and confirmations.

- Yes/no questions accept y/yes or n/no, ignoring case. An unrecognized answer prints an error and repeats the same question.
- Enter uses a displayed default. On exact-word restore confirmations, Enter cancels.
- Account and recovery-server selectors reject invalid numbers and identifiers before continuing.
- DIFFERENT, APPLY and PUBLISH stay case sensitive; misspelled confirmations retry without taking action.

## Downloads

- `discord-backup-linux-1.6.1.tar.gz`: complete application source, tests, documentation, launchers and build tools. Requires Python 3.10+, GnuPG 2.4+ and Requests.
- `discord-backup-linux-1.6.1-1-any.pkg.tar.zst`: unsigned Arch package. Install with `sudo pacman -U ./discord-backup-linux-1.6.1-1-any.pkg.tar.zst`, then run `discord-backup`.
- `SHA256SUMS`: verify both downloads with `sha256sum -c SHA256SUMS`. Checksums verify consistency, not publisher identity.

## Validation

All 116 offline tests passed during the makepkg check, including nine new input-validation regressions. The source archive contains exactly the reviewed manifest, and the normalized Arch package matches the reviewed installed files. Normalization removes private build identity, paths and host package inventory. All Python source parses with Python 3.10 grammar; GitHub Actions checks Python 3.10 and 3.14. Tests use synthetic data and transports, with no live account backup or bot publication.

The [README demo](../v1.6.0/screenshots/demo.gif) still illustrates the unchanged whole-account backup estimate. See the [unlock guide](../../UNLOCK_BACKUP.md) and [guided recovery/bot setup](../../docs/RECOVERY_HUB.md).

