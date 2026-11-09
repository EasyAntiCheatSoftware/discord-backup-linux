# Version 1.5.1

ETA visibility fix and an animated README backup demo.

- `discord-backup-linux-1.5.1.tar.gz`: full portable source and build tooling; Python 3.10+, GnuPG 2.4+ and Requests required.
- `discord-backup-linux-1.5.1-1-any.pkg.tar.zst`: unsigned Arch package; install with `sudo pacman -U ./discord-backup-linux-1.5.1-1-any.pkg.tar.zst`, then run `discord-backup`.
- `SHA256SUMS`: verify both downloaded artifacts with `sha256sum -c SHA256SUMS`.

ETA status now starts before the first request. A preliminary numeric estimate appears after server discovery, before the group lookup completes. Each invitation progress line includes an ETA, and a background heartbeat updates during blocked work every five seconds. Incomplete workload estimates are labeled available data only; overruns say recalculating. Reopen an already running menu after updating.

The looping GIF and PNGs in `screenshots` are actual CLI output from isolated synthetic demos, rendered with a neutral palette. GIF playback is slowed for readability; this is not a live-account performance measurement. No real credentials, backups or desktop/terminal settings were captured.

All 95 offline tests passed, including blocked-request heartbeats, early estimates, cooldown updates, reporter shutdown, forecast overruns and existing encryption/restore tests. The Arch build passed its source checksum and test checks; its installed source and cleaned public metadata were verified. Python source parses with the Python 3.10 grammar. Check GitHub Actions for Python 3.10/3.14 CI results.

See [the unlock guide](../../UNLOCK_BACKUP.md) for recovery on the same or a different machine. The source archive contains the screenshot/GIF generator; generated media are hosted here rather than required at runtime.
