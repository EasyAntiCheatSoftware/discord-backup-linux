# Version 1.6.0

Whole-account estimates before backup, guided backup selection, and an official-bot recovery hub.

## Downloads

- `discord-backup-linux-1.6.0.tar.gz`: full application source, tests, documentation, launchers and build tooling. Requires Python 3.10+, GnuPG 2.4+ and Requests.
- `discord-backup-linux-1.6.0-1-any.pkg.tar.zst`: unsigned Arch package. Install with `sudo pacman -U ./discord-backup-linux-1.6.0-1-any.pkg.tar.zst`, then run `discord-backup`.
- `SHA256SUMS`: verify both artifacts with `sha256sum -c SHA256SUMS`. Checksums verify consistency, not publisher identity.

## What's new

A read-only preparation stage discovers/reuses this account's workload and calibrates encryption in memory. One total-duration estimate is printed before the first normal checkpoint or invitation, followed by an overall heartbeat during the run. Server/group lines have counters only. The initial estimate and actual elapsed time appear in the summary. Unavailable data and forecast overruns are clearly labeled; preparation failures preserve collected data in an encrypted partial file.

Choose main-menu option 2 for a recent-file picker that checks current/default/session locations and accepts a custom folder or direct file path. Unlock once, then use the local export, bot hub, folder restore or GIF-settings restore. Cross-account settings changes require explicit target and apply confirmation.

The private hub uses your own bot in an existing trusted Discord server. It creates a private category and organized channels with saved invites, contact links and warnings. Preview is read-only; apply verifies the destination and channel privacy, disables mentions/embeds, bounds messages and stops on uncertain writes without deleting partial work. Joining servers, adding friends and changing your profile remain manual, as in the original project. This is not a CAPTCHA bypass. See [bot setup and limits](../../docs/RECOVERY_HUB.md).

The lead GIF and PNGs are captured real CLI output with synthetic data and a neutral renderer. Animation playback is slowed for readability. No personal desktop, terminal settings, live account backup or credential appears in these assets. The source archive contains the generator; media are hosted here and are not runtime dependencies.

## Validation

All 107 offline tests passed, including the makepkg test run. The final documentation-only refresh was repackaged after those runtime checks. Source/archive membership and installed package files were compared against reviewed source, private build metadata was removed, all Python source parses with Python 3.10 syntax, and extracted-package version/help/encrypted-export checks passed. The installed package includes the recovery-hub guide. Check GitHub Actions for Python 3.10/3.14 CI results. No live Discord bot/server publication was performed during this update.

See the [unlock guide](../../UNLOCK_BACKUP.md) for the same or another machine, with the app or standalone GnuPG.
