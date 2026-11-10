# Release review: 1.4.0

The review covered the Python application, launchers, packaging, developer tools, tests and documentation. An independent baseline security pass and a focused import/credential investigation were reconciled with the application's single-user trust model. No confirmed security vulnerability or embedded production credential was identified in the reviewed pre-fix source. Generated/historical artifacts and local runtime data were excluded from that source scan; the new publication payload received separate checks.

## Correctness fixes

| Issue | Result in 1.4.0 | Regression coverage |
| --- | --- | --- |
| Successful response with remaining budget and a reset window over 120 seconds was rejected as a long cooldown | Record the window; stop only when an actual excessive wait is required | Long positive-budget window, exhaustion, no early retry |
| Success with remaining budget zero retained old invite backoff strikes | Every success resets strikes while retaining rate deadlines | 429 → success/exhausted → 429 sequence |
| Checkpoint encryption ValueError could be swallowed as an optional response-format warning | Distinct persistence error propagates | Encryption failure inside optional collection cannot become a warning |
| Excessively nested JSON and oversized decimal IDs could raise conversion/parser exceptions | Normal import/validation errors; bound identifiers before conversion | Deep JSON, very long/non-ASCII IDs, malformed schema/timing fields |
| Folder matching scanned the growing result for each folder | Dictionary lookup; linear in folders and memberships | Large ordered merge with shared folder IDs and current-only servers |
| Menu recalculated a changed restore after preview; successful PATCH was assumed sufficient | Compare the displayed plan, save rollback, read settings back | Changed preview sends no write; unconfirmed restore retains encrypted rollback |
| Recursive source archiving could include unreviewed files and local owner metadata | Explicit file manifest, content checks and normalized source metadata | Unexpected file/symlink rejection, private-path/token-shaped rejection, deterministic archive and stage tests |
| Raw Arch metadata included local build context | Exact installed-source comparison and regenerated public metadata/mtree | Package listing, metadata inspection, digest checks and installed CLI smoke test |
| Network benchmark executed an old local archive | Current-code one-versus-three-worker fixture benchmark | Both workloads use synthetic transport and real encryption |

## Validation

The test suite uses synthetic account/token fixtures, fake transports, temporary directories and real GnuPG. Existing coverage includes encryption corruption/wrong-passphrase/truncation, no secret arguments/logs, private-file modes/symlink/FIFO checks, escaped HTML and constrained links, redirects, CDN auth separation, request budgets, shared/global cooldowns, cancellation, partial preservation and speed-test cleanup.

Local validation used Arch Linux, Python 3.14 and GnuPG 2.4. CI is configured for Python 3.10 and 3.14. A configured job is not evidence that it has passed: check GitHub's run status. The synthetic benchmark measures controlled request latency and encryption/checkpoint overhead; it does not compare this program with the upstream Windows executable or establish live account speed.

Public payload inspection checks the explicit source set, new archive members, installed package files, compressed metadata and new Git tree. Test credential strings are mechanically synthetic. No account backup or private credential file is an input to the publication build. Raw private security-tool reports and old local archives are not published.

## Remaining limits

Live Discord backup and restore behavior was not tested during the release review. Private endpoints can change, and rate limits vary by account/route. Coordination is local to one process. The opaque GIF block can include preferences beyond favourite GIFs. Readback can report an unconfirmed result if Discord normalizes the block; it cannot provide a transaction against concurrent edits. Repeating a run creates a new backup rather than resuming an old partial one.

Import byte limits do not impose a total memory budget; JSON objects and generated HTML consume additional memory. Other processes running as the same user, trusted executable/dependency compromise, OS swap and parent-directory permissions are outside the app's isolation guarantees. Source pattern checks cannot prove the absence of every possible secret. Review and tests reduce specific risks; they are not a safety certification.

## 1.5.0 follow-up

The 1.5.0 changes add current-account time estimates and clearer warning summaries without changing authentication, encryption or restore authority. Estimation reads existing performance counters and a locked limiter snapshot; it sends no extra requests, changes no budgets and persists no account-history file. Server/group membership discovery precedes estimation. Failed membership discovery disables the numeric estimate. Unknown future throttles, image downloads and permission failures can still move the forecast.

New offline regressions cover different workloads/latencies/worker counts, known wait accounting, read-only limiter snapshots, duration formatting, estimate timing and unchanged API request count, unavailable estimates after discovery failure, detailed partial summaries and interrupted CLI output with encrypted partial preservation. Membership ordering still preserves relationships and memberships on later failures. Duplicate encryption at membership section boundaries was removed; the enclosing section checkpoint remains mandatory.

Documentation screenshots use the actual CLI with synthetic transports in isolated pseudo-terminals. Network connections are blocked in the fixture child, credentials and demonstration backups are temporary, and a neutral renderer adds no desktop/user metadata. The Windows GnuPG instructions are provided as PowerShell source; they were not executed on Windows during this Linux review. The app-based unlock/export and GnuPG encryption/decryption remain covered by the offline tests.

## 1.5.1 ETA visibility fix

The previous numeric estimate required both discovery sections to succeed and only refreshed when the collector advanced. This could leave users without a number during a slow/failed lookup or an invite request waiting on Discord. The fix starts a visible calculating status before account lookup, prints a preliminary number after server discovery, labels incomplete-work estimates, and adds a five-second heartbeat plus per-invitation ETA text. The background reporter consumes display snapshots and read-only limiter hints, never backup data mutations or credentials. Context-managed stop/join prevents output leaking into later menu/passphrase prompts.

Regression tests verify ETA output before any request, numeric output before group lookup, heartbeat output while the main request is blocked, known wait updates, shutdown on exception and honest recalculation after an overrun. No live Discord request was needed to reproduce or verify the display issue.

## 1.6.0 recovery and whole-account estimate

Preparation now reads/reuses account counts and contacts before the main backup. One full-account prediction is shown before normal persistence/invite writes; interrupted preparation is encrypted on error. In-memory encryption calibration replaces a generic checkpoint-cost guess. Resource rows contain counters only; the reporter maintains overall time and the final summary retains the initial prediction.

Recovery discovery reads file metadata only, skips symlinks/special files, limits scanning/list size and permits explicit file/folder overrides. The bot publisher is a distinct fixed-origin v10 Bot-auth path. Its preview is read-only; apply binds the chosen server, creates private overwrites and checks returned IDs/permissions before messages, suppresses mentions/embeds, bounds plans, and stops on uncertain writes. Test coverage includes these boundaries and an offline wizard export. Server administrators remain trusted; no live bot publication was tested.
