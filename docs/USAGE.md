# Advanced usage

See the [README](../README.md) for installation and everyday recovery.

## Back up

Choose **1 · Back up account**, scan your local Discord caches or enter a token in a hidden prompt, then choose and confirm a passphrase of at least 12 characters. Browser-profile scanning requires opt-in. Interactive use does not save credentials.

Keep the passphrase separately: there is no reset or recovery key. Backups normally go to `~/.local/share/discord-backup-linux/backups`; use `--output` for another folder.

| Saved data | Recovery |
| --- | --- |
| Server/group membership and optional invitations | Follow saved invitations manually |
| Friends, blocked users, requests and open-DM contacts | Open profiles and manage relationships manually |
| Profile images and bio | Export files, then apply them in Discord |
| Server folders | Preview/apply for servers you have rejoined |
| Favourite GIF/frecency settings | Optional replacement of the entire opaque settings block |

Message contents and server contents are not collected. The original project's plaintext JSON backups can also be opened.

### Progress and interruptions

One **whole-account estimate** appears after read-only preparation and before the main backup. The overall ETA adjusts to observed invite throughput, encryption and Discord waits. Future estimates use up to five recent private timing samples for that account and the same worker/invite options. The cache contains numeric timings, no tokens or backup contents; see [storage details](#timing-history). A first run cannot know future Discord throttles and is labeled accordingly.

Interactive terminals update the ETA on a single line. The final summary shows elapsed time, the initial estimate, total Discord waits and the number of rate-limit responses. It shows up to three warnings and identifies affected sections. The recovery page and `inspect` show every saved warning, and `inspect` includes per-stage timings and grouped-notice counts.

An unfinished file keeps **`-partial.bkup`** in its name. Completed collection removes that suffix only after the final encrypted save. Partial backups remain usable: the app, recovery page and decrypted JSON identify missing/pending sections. Ordinary interruption forces a save and preserves successful in-flight invite results. A forced kill, power loss or disk/encryption failure can preserve only the last successful checkpoint. Missing data needs a new backup; files cannot be resumed.

## Recover — here or on another machine

Choose **2 · Recover a backup**. The picker checks current/default folders and the last folder used in this session; you can also enter a custom folder or file. Unlock once, then choose a local recovery page, private bot hub or settings restore.

- **With the app:** the local recovery page contains saved links, profile files, section status and warnings. Its output is decrypted personal data; keep the folder private.
- **Without the app:** use GnuPG 2.4+ and the same passphrase. [The unlock guide](../UNLOCK_BACKUP.md) includes Linux/macOS and Windows commands that show partial status after decryption. No Discord token or original computer is needed.
- **Bot recovery:** your own bot organizes links and contacts in private channels in an existing trusted server. Review the destination before typing `PUBLISH`. Server owners/admins can read uploaded data. [Setup and limits](RECOVERY_HUB.md).

Server joins, friend requests and profile changes remain manual, as in the original project. The bot is not a universal CAPTCHA-free account restore.

Settings restores preview first and save an encrypted rollback before writing. Folder restore keeps current-only memberships; GIF restore replaces the whole frecency block, including other preferences stored there. A different account requires explicit confirmation. See [restore details](#settings-restores).

## Commands

The main menu focuses on backing up and recovering. Use `--help` to see all commands, including listing, scheduling, credential setup and speed tests.

Use `discord-backup` instead of `./run.sh` after installing the Arch package.

```sh
./run.sh backup --no-invites       # Read-only backup; default backup mode also creates invites
./run.sh backup --manual          # Hidden manual token entry
./run.sh backup --output "$HOME/Backups/Discord"
./run.sh recover                  # Recent-file picker and recovery menu
./run.sh recover /path/to/backups # Browse a custom folder
./run.sh inspect /path/to/file.bkup
./run.sh export /path/to/file.bkup --output "$HOME/discord-recovery"
./run.sh --help
```

Invalid choices repeat the prompt. Yes/no accepts `y`/`yes` or `n`/`no`; Enter uses the displayed default. Restore confirmations require the exact uppercase word, or Enter to cancel.

## Settings restores

`inspect` and `export` work offline. They ask for the backup passphrase, never a Discord token. Export requires a new output directory and creates a local HTML page, bio text, and recognized image files. It contains **decrypted personal data**. The page has no JavaScript or remotely loaded images; links open Discord when followed. Invalid legacy image data produces a warning.

Restore commands preview by default. `--apply`, or typing `APPLY` in the menu, authorizes the write. Before writing, the app checks the live account and saves a separate encrypted rollback snapshot. It reads settings back before reporting a verified restore. Folder restoration retains currently joined servers absent from the backup and omits servers you have not rejoined. The menu stops if its displayed folder plan changes before applying. Concurrent changes during the final request can still race; avoid editing the same settings elsewhere during restoration.

A different account requires `--allow-different-account`. To reverse a restore, preview the corresponding restore command with its `rollback-*.bkup` file. GIF restoration replaces the **whole opaque frecency block**, including other preferences stored there. A changed or normalized server response is reported as unconfirmed rather than silently declared successful.

`encrypt` writes a separate encrypted copy of a plaintext legacy file. The original remains plaintext until you remove it yourself.

### Account scanning

Scanning reads current-user native/Flatpak Discord-family LevelDB caches, including supported Vesktop, ArmCord, and Legcord locations. It skips symlinks and files owned by another user, bounds individual reads and total input to 256 MiB, and validates at most 50 unique candidate tokens. Duplicate accounts are combined. Candidate validation uses `/users/@me`; the UI prints account/client labels, never token values.

Chrome, Chromium, Brave, and Edge caches require `--scan-browsers` or **Scan Discord apps and browsers** in the account prompt. Additional LevelDB directories can be selected with repeatable `--scan-path` options. The scanner recognizes ordinary and legacy MFA tokens, but cannot read every compressed or OS-keyring-encrypted record. It does not unlock keyrings. Use manual entry when scanning finds no valid account.

### Colors

Colors are automatic on a terminal and off for redirected output, `TERM=dumb`, or `NO_COLOR`. Use `--color always` or `--color never` before the command to override detection. The desktop launcher enables colors. `inspect` prints a partial-data notice when applicable, followed by the JSON summary.

## Encryption and storage

Backups normally live in `~/.local/share/discord-backup-linux/backups`; an absolute `$XDG_DATA_HOME` changes the data root. Names contain a UTC timestamp and random suffix. Unfinished files end in `-partial.bkup`; only a successfully finalized complete backup loses that marker. The authenticated JSON also records `status`, `recovery_notice`, `sections` and interruption warnings. A filename is a convenience; trust the decrypted status when inspecting older or renamed files. New directories use mode `0700`; new backup/export files use `0600`. Existing parent permissions are unchanged.

The file format is an eight-byte `DBLENC1\n` header followed by a binary password-encrypted OpenPGP message. GnuPG uses AES-256/OCB authenticated encryption, salted iterated SHA-512 passphrase derivation, and an S2K count of 65,011,712. See the [GnuPG OpenPGP options](https://www.gnupg.org/documentation/manuals/gnupg/OpenPGP-Options.html). The passphrase travels through a private inherited pipe, not command arguments or environment variables. GnuPG uses an isolated temporary home and no symmetric-key cache.

Plaintext JSON exists in process memory. Backup and rollback writes encrypt before writing to an atomic temporary file; encryption failure never falls back to plaintext. Decryption must complete with authenticated status checks before the app accepts its output. This does not isolate data from other processes already running as your user or prevent the OS from swapping memory.

**You can unlock a backup on another machine without this app.** Keep [UNLOCK_BACKUP.md](../UNLOCK_BACKUP.md) with the encrypted file and retain its passphrase separately. It covers GnuPG on Linux/macOS and Windows. No Discord token or original computer is required.

### Timing history

The `timings` folder beside the default `backups` directory stores up to five numeric samples from the last 30 days per account. Filenames use a hash of the account ID; records do not contain the ID, account name, credentials, invites or backup contents. Files use mode `0600`. The estimate selects runs with matching worker/invite options and measures actual invite wall time, including throttling, separately from encryption. New cooldowns extend the pending-work forecast, and periodic checkpoints are included. The cache is advisory: missing, stale, invalid or unwritable history does not prevent a backup. Delete the `timings` folder to reset learning. Speed tests and offline benchmark tools do not save timing history.

### Unattended backups

Interactive use does not save either credential. The following commands explicitly save plaintext credentials protected by filesystem permissions:

```sh
./run.sh save-token
./run.sh save-passphrase
./run.sh backup --token-file "$HOME/.config/discord-backup-linux/token" \
  --passphrase-file "$HOME/.config/discord-backup-linux/backup-passphrase" --no-invites
./run.sh schedule
# Review the generated units, then enable:
systemctl --user daemon-reload
systemctl --user enable --now discord-backup.timer
systemctl --user list-timers discord-backup.timer
```

Defaults respect an absolute `$XDG_CONFIG_HOME`. Both files must be regular files owned by you without group/other permission bits; final-component symlinks are rejected. Save commands refuse to replace existing files. Keep the passphrase file separate when copying backups off the machine.

The timer runs after user-manager startup and daily with jitter, while the user manager is available. Scheduled backups are read-only unless generated with `schedule --create-invites`. Units bind absolute paths; regenerate them after moving a source installation. The app does not enable the timer automatically. Disable with `systemctl --user disable --now discord-backup.timer`. There is no automatic backup retention or cleanup.

## Rate limits, errors, and speed

Repeated rate-limit notices share a 30-second reporting window across all workers, including normal budget exhaustion. This changes output only: all deadlines, retry bounds and serial-invite fallback stay in place. The final summary shows HTTP 429 counts and total Discord wait time. The grouped-notice count is available through `inspect`. The five-second account ETA remains visible during waits; final authentication, CAPTCHA, persistent-limit and missing-data errors are not suppressed.

Each worker reuses its own HTTPS connection pool. Three workers process independent invitation tasks by default; `--workers` accepts 1–4. A shared coordinator reserves known request budgets, separates major resources, handles global limits and fractional reset deadlines, and follows [Discord's rate-limit headers](https://docs.discord.com/developers/topics/rate-limits). A local guard caps request starts at 25 per second; it is not a claim about the rate Discord allows.

An invitation 429 pauses the invite route across channels, reduces it to one in-flight request, and adds exponential backoff. Longer server retry delays take precedence. Queued work stops on invalid credentials, CAPTCHA requirements, five persistent 429 responses for a request, or a required cooldown above 120 seconds. Requests already in flight may finish. GETs have bounded server-error retries; invite POSTs are not repeated after ambiguous network/server failures. The app does not bypass limits or solve CAPTCHAs.

If you see `Discord rate limit persisted`, let the cooldown expire, then try `backup --workers 1` or `backup --no-invites`. The reported partial file remains encrypted and can be inspected/exported normally. Rerunning creates a new backup; it does not resume an old one. Unsupported optional endpoints create warnings and a partial result.

Encrypted checkpoints occur at section boundaries and approximately every five seconds during invitations, rather than after every invitation. Ordinary cancellation and handled request errors force a final save. A forced process kill, power loss, or disk/encryption failure can preserve only the last successful checkpoint. Timings exclude the final checkpoint's own write and include summed worker HTTP time, which can exceed elapsed time.

```sh
./run.sh speed-test --no-invites   # Real account, temporary local ciphertext
./run.sh speed-test               # Also creates invitations where allowed
python3 tools/benchmark_network.py --latency 0.12  # Synthetic, offline, 1 vs 3 workers
python3 tools/benchmark.py         # Synthetic encrypted-checkpoint workload
```

`speed-test` deletes its own local test files on success, exceptions, and ordinary cancellation. It does not remove invitations created on Discord or touch existing backups. Forced termination may leave unreadable temporary ciphertext. The offline benchmark uses fixture data, simulated latency and real encryption; it does not establish live performance or speed relative to the original Windows tool.

Exit codes: `0` success, `1` error or interrupted backup, `2` partial backup/export warnings, `130` cancellation outside the backup collection flow. A partial scheduled result appears as a failed service while retaining its encrypted file.

