# Architecture

All launchers converge on `discord_backup.cli.main`: `run.sh`, `main.py`, `python -m discord_backup`, the source desktop launcher, the Arch command, and generated systemd user services. Paths in source launchers are resolved relative to the application; scheduled units bind absolute paths when generated.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Menu, argument parsing, hidden credential prompts and command dispatch |
| `tokens.py` | Bounded, current-user cache scanning and account validation |
| `api.py` | Per-thread HTTPS sessions, fixed API/CDN origins, retries, cancellation, request statistics and shared rate budgets |
| `backup.py` | Collection order, optional-section warnings, invite workers, in-memory data updates and encrypted checkpoints |
| `encryption.py` | Isolated GnuPG invocation, passphrase pipe and authenticated decrypt checks |
| `storage.py` | XDG paths, private atomic writes, file/schema validation and private credential reads |
| `restore.py` | Escaped local recovery page, folder planning, account checks, encrypted rollback and verified writes |
| `selection.py` | Current/default/session backup discovery and custom file/folder picking |
| `hub.py` | Official bot client, bounded recovery plans, private-channel verification and preview/apply publishing |
| `schedule.py` | Quoted systemd user service/timer generation |
| `progress.py` | Current-account workload and latency estimates without extra requests or saved history |
| `terminal.py` | Colors, terminal control filtering and summaries |
| `tools/release.py` | Source manifest verification, deterministic archive and clean publication staging |
| `tools/package.py` | Installed-file comparison and public Arch metadata normalization |

## Collection flow

Authentication precedes the first checkpoint. The collector analyzes servers, relationships and DM/group contacts in memory, shows a whole-account estimate, then checkpoints the prepared data, collects profile/settings and performs invitation work. Optional endpoint failures become warnings; credential rejection, CAPTCHA, persistent throttling and cancellation stop queued work. The main thread owns backup state and persistence. Workers return invite results through futures; they do not write backup files.

The shared limiter uses normalized route templates plus major resource IDs. Unknown buckets serialize requests for the same major resource until a response establishes a budget. Known budget is reserved before network work begins. Global and route deadlines use a monotonic clock. All invitation channels share a temporary pause and switch to serial requests after invite throttling. Coordination does not extend to another process or the official Discord client.

## Data boundaries

Tokens are passed on individual API requests to the fixed Discord origin. Redirects are disabled. CDN requests have their own fixed host and no account authorization. Network errors use generic messages rather than dumping request objects. Requests uses the caller's normal HTTPS proxy/CA configuration.

A new backup is JSON in memory, then `DBLENC1\n` plus an authenticated OpenPGP message on disk. Atomic replacement happens only after encryption succeeds. Default data/config roots are separate, but user-selected paths can put them together. Optional unattended secret files are not encrypted. Same-user process isolation and existing parent-directory permissions remain host responsibilities.

Decrypted/imported backup contents remain untrusted. The parser applies byte/type/ID checks; the recovery renderer escapes text, constrains links and image formats, and uses fixed output names. The local export is plaintext and must be kept private. It does not carry its own authenticity guarantee beyond the encrypted file's passphrase integrity.

Restore uses fixed account-relative routes. It independently authenticates the live account, checks identity, creates an encrypted before-change snapshot, and only then sends a PATCH. Folder plans preserve currently joined servers absent from the backup. The menu compares the recomputed plan with the preview; settings readback checks the result. There is no server-supported transaction or compare-and-swap, so concurrent settings changes can still race.

## Publication boundary

Runtime data belongs in XDG storage, outside source. Source archives use only `release-files.txt`, not recursive directory copying or Git ignore rules. Public package contents are compared byte-for-byte with that source. Public metadata excludes local paths, builder identity and installed-package inventory. Exact Git tree and build assets are checked separately before upload; old local archives and security-tool state are never copied.

## Time estimates and documentation images

The collector reads servers, relationships and DM/group contacts in a read-only preparation stage and reuses those results. It calibrates encryption with a tiny in-memory message, then prints one whole-account duration before a normal checkpoint/invitation is written. The initial prediction includes preparation time; completed preparation data is saved in an encrypted partial file if preparation is interrupted. Forecast snapshots are updated without printing resource-specific estimates. A five-second reporter heartbeat shows overall remaining time while work is blocked and is stopped/joined before returning to the menu or a secret prompt. No duplicate discovery request, account-history file or credential cache is added.


`tools/screenshots.py` runs the real CLI in private pseudo-terminals with fake transports and a blocked network connection path. A fixed neutral palette and Noto Sans Mono render that output to PNG through Pillow. No desktop or user terminal configuration is captured. Demonstration backups and credentials are temporary; only the synthetic screenshots are publication assets under `builds/v1.6.0/screenshots`. Install Pillow and Noto Sans Mono only if regenerating these developer assets.

The screenshot tool also records timestamped PTY output and renders a looping GIF. The README demo uses those real output snapshots with synthetic data, slowed for readability and held on the completion summary.

## Official bot recovery

The recovery hub uses a separate client fixed to Discord API v10 with Bot authorization and a documented bot user agent. The existing personal-account backup/settings client remains on its original endpoint/auth path. Tokens are explicit per-request headers, never session defaults or message content. The hub is an organizer, not an account rejoin/friend/profile mutation service.

Plans contain fixed channel names and bounded, escaped Discord links/text. Preview reads the bot/server identities and shows the target/data scope. Apply rechecks the destination owner/name, creates a private category and children with explicit overwrites, validates channel identity/privacy before posting, disables mentions/embeds and confirms message IDs. The server owner/admins remain trusted and can change permissions between calls. Partial created resources are retained; ambiguous writes are not retried automatically. No encrypted backup, token, passphrase or raw settings block is uploaded.
