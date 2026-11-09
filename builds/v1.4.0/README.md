# Version 1.4.0 build

This directory contains the complete portable Linux source archive and an unsigned Arch Linux package. The repository root contains the same source and the build tools. No credentials, account backups or local runtime exports are included.

Download both the desired artifact and `SHA256SUMS`, then run `sha256sum -c SHA256SUMS` from the download directory. A missing artifact produces a missing-file warning for that entry. Checksums verify consistency, not publisher identity.

- `discord-backup-linux-1.4.0.tar.gz`: complete source, tests, launchers, documentation and Arch build recipe. Extract it and run `./run.sh`; dependencies are Python 3.10+, GnuPG 2.4+ and Requests.
- `discord-backup-linux-1.4.0-1-any.pkg.tar.zst`: Arch package. Install with `sudo pacman -U ./discord-backup-linux-1.4.0-1-any.pkg.tar.zst`, then run `discord-backup`. It is unsigned.

The source archive has normalized ownership, permissions and timestamps. The public package was compared against that source; builder identity, private build paths and the host package inventory were removed and `.MTREE` regenerated. Timestamp fields use epoch zero. The package retains a reduced `.BUILDINFO`, not a complete build-environment record.

Validation: all 83 offline tests passed, the source checksum passed makepkg validation, the Arch package built, all Python files parsed with the Python 3.10 grammar, and the extracted installed CLI passed version/help/encrypted-inspect smoke checks from a different working directory. Local runtime tests used Python 3.14 and GnuPG 2.4. Check GitHub Actions for actual minimum-version CI results.

A synthetic workload with 16 servers, 8 group chats, 46 requests and 120 ms simulated request latency took 7.178 seconds with one worker and 4.049 seconds with three workers, including real encryption. This is a single controlled run, not a live Discord benchmark or a comparison with the original Windows program. No live Discord backup/restore was performed during this release review.

See the root README, `UNLOCK_BACKUP.md`, `CHANGELOG.md` and `docs/REVIEW.md` for use, portable decryption, fixes and remaining limits.
