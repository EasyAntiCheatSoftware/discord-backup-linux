# Version 1.7.0

Quieter rate-limit output, portable partial recovery and better whole-account forecasts.

## Downloads

- `discord-backup-linux-1.7.0.tar.gz`: complete source, tests, guides, launchers and build tooling. Requires Python 3.10+, GnuPG 2.4+ and Requests.
- `discord-backup-linux-1.7.0-1-any.pkg.tar.zst`: unsigned Arch package. Install with `sudo pacman -U ./discord-backup-linux-1.7.0-1-any.pkg.tar.zst`, then run `discord-backup`.
- `SHA256SUMS`: check both downloads with `sha256sum -c SHA256SUMS`. Checksums verify consistency, not publisher identity.

## Changes

Repeated HTTP 429 and ordinary budget-wait notices share a 30-second reporting window across workers. Backoff, deadlines, retry limits and serial-invite fallback are unchanged. The final summary retains response counts, grouped-notice counts and wait time.

Collection files keep a `-partial.bkup` suffix until the final encrypted complete save succeeds. Interruption preserves collected data and successful unconsumed worker results. Partial state is visible in the picker, after unlock, in recovery HTML and in the authenticated JSON. The OpenPGP message embeds the name `backup-partial.json` for partial data; standalone GnuPG can expose it. Updated Linux/macOS/Windows instructions show status, sections and warnings without this app. A hard kill or disk/encryption failure preserves at most the last successful checkpoint.

The estimate remains for the whole account before the main backup. It now adapts to observed invitation throughput, periodic encryption costs and new cooldowns. Up to five recent private numeric samples improve later predictions for the same account and worker/invite options. The cache contains no account name, raw ID, credential, invitation or backup contents. Interrupted runs and speed tests are excluded. A first-run estimate is rough because future Discord throttles are unknown.

The shorter [README](../../README.md) retains the GIF and main recovery/setup details; [advanced usage](../../docs/USAGE.md) holds scanning, storage, scheduling and restore specifics. The existing v1.6.0 GIF remains an illustration of the whole-account backup flow.

## Validation

All 132 offline tests passed during makepkg, including rate-notice concurrency/backoff, interrupted-result salvage, readable checkpoints after later save failure, standalone real-GnuPG partial decryption and timing-history isolation. Source/archive membership and installed package payload were verified against reviewed source. Package normalization removes local build identity, paths and host inventory. All Python source parses with Python 3.10 grammar; extracted-package version and bundled guides were checked. GitHub Actions checks Python 3.10 and 3.14.

Tests use synthetic data/transports and temporary files. No live account backup or bot publication was performed. See [unlocking](../../UNLOCK_BACKUP.md) and [bot setup](../../docs/RECOVERY_HUB.md).

