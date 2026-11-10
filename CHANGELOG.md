# Changelog

## 1.7.0 — 2026-11-10

- Group repeated rate-limit and budget-wait notices across workers into at most one update every 30 seconds. Preserve all request deadlines, backoff/retry bounds and serial-invite fallback. Show throttle and grouped-notice counts in the final summary.
- Keep new files named `-partial.bkup` until the final successful encrypted complete checkpoint. Preserve successful unconsumed invite results while stopping workers, and retain readable checkpoints after later disk/encryption failures.
- Identify partial recovery in the picker, after unlock and in the HTML export. Store readable recovery status in the authenticated JSON and use `backup-partial.json` as the encrypted payload filename. Expand standalone Linux/macOS/Windows instructions to show status, sections and warnings without this app.
- Improve whole-account forecasts with observed invite wall time, periodic encryption costs and newly extended cooldowns. Reuse up to five private recent timing samples for the same account and worker/invite options; exclude interrupted runs and speed tests. First-run predictions explicitly note unknown future throttles.
- Shorten the README and move advanced scanning, storage, restore, scheduling and performance details to a linked guide. Keep the demo GIF, upstream attribution and cross-machine recovery instructions.

## 1.6.1 — 2026-11-10

- Retry invalid yes/no answers at the same prompt instead of silently choosing a default. Accept y/yes and n/no without case sensitivity; only an empty answer selects the displayed default.
- Retry invalid menu choices, account/server selections and exact-word restore confirmations. Invalid input cannot start a backup, upload contacts, open a browser or apply a restore. Keep Enter-to-cancel behavior for restore confirmations and normal EOF/Ctrl+C cancellation.
- Add nine offline regression tests covering prompt validation and action gating.

## 1.6.0 — 2026-11-09

- Analyze and reuse the account workload before the main backup, then display one whole-account time estimate before the first normal checkpoint or invitation. Calibrate encryption in memory, retain an overall heartbeat, and show the initial estimate with actual elapsed time. Resource rows have counters only. Preparation errors preserve collected data in an encrypted partial file.
- Add a recent-backup picker across current/default/session locations, custom folder browsing and direct file selection. Omitted paths open the picker in interactive recovery commands.
- Add a guided recovery menu that unlocks once, exports a local page/profile files, previews settings restores, or prepares a private bot recovery hub. Cross-account settings restores show both identities and require explicit target/apply confirmation.
- Add a separate official v10 Bot-auth client and a preview/apply publisher for private recovery categories/channels. Validate destination binding and permissions, disable mentions/embeds, bound messages and stop on ambiguous writes without deleting partial work.
- Document bot setup and the original project's manual joining/friend/profile steps. No CAPTCHA bypass or automatic arbitrary-server joining is added.

## 1.5.1 — 2026-11-09

- Replace the README lead screenshot with an animated synthetic backup demo and retain a static preview.

- Show ETA status before the first backup request and keep a five-second heartbeat active during blocked HTTP requests, encryption and rate-limit waits. Stop/join the reporter before returning to the menu or a secret prompt.
- Discover servers first and show a preliminary numeric estimate before the group lookup completes. Failed discovery no longer suppresses all timing output; any numeric estimate for an incomplete workload is labeled available data only.
- Append a short ETA to each server/group invitation progress line. An overrun reports recalculating instead of zero seconds.
- Add regressions for output before the first request, numeric output before group discovery, heartbeats during blocked requests, wait updates, reporter shutdown and forecast overruns.

## 1.5.0 — 2026-11-09

- Show an account-specific remaining/total time estimate after membership discovery. Update from this run's request timings, workload, encryption cost, worker count and known invite cooldowns; make no extra API calls and save no account-history cache.
- Read relationships and memberships early enough to estimate before profile/settings and invite work. Keep membership checkpoints at the enclosing section boundary, removing duplicate encrypted saves.
- Print every warning and affected/unattempted sections in the final summary, including interrupted backups. Explain missing invite access, preserved data and the need for a new backup to collect missing sections.
- Add isolated synthetic terminal screenshots, a refreshed README and a same-machine/cross-machine unlock guide with GnuPG and app instructions.

## 1.4.0 — 2026-11-09

First prepared public source/package release after the Linux implementation review.

- Accept a long rate-limit reset window when a successful response still has request budget. Stop if an actual required wait exceeds the configured policy; never retry early.
- Reset invitation backoff after every successful response, including a response that exhausts the current budget.
- Reject invalid request-pacing configuration and discard inactive reservation entries.
- Reject excessive/non-ASCII identifiers, invalid timing metadata and deeply nested malformed imports with ordinary errors.
- Propagate checkpoint encryption failures instead of converting them to optional API-format warnings.
- Replace repeated folder lookups with a linear mapping while preserving server order and current-only memberships.
- Bind menu folder apply to the displayed plan and verify settings after successful restore requests. Save rollback before any modifying request.
- Publish source through an explicit per-file manifest; normalize archive ownership, timestamps and modes; check credential/private-path patterns.
- Compare the Arch package's installed files against reviewed source and remove local build identity, paths and package inventory from the public package metadata.
- Replace the historical-archive benchmark with an offline one-versus-three-worker workload. Add CI, recovery instructions, release documentation and review notes.

## Local development before 1.4.0

Earlier local snapshots introduced encrypted backups and rollback, token scanning/manual entry, recovery exports, colored output, user timers, connection pooling, parallel invitations, shared rate budgets, metadata-first collection and batched checkpoints. They are not separate supported public releases. No personal data or historical local artifacts are part of this repository.
