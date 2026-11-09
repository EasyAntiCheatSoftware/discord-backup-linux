# Changelog

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
