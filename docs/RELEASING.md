# Building and publishing

The public source set is `release-files.txt`. `tools/release.py --check` rejects unexpected source files, symlinks, oversized/non-text inputs, credential-shaped strings and private home paths. Local state directories listed in the tool are excluded. The source archive uses fixed ownership/modes and `SOURCE_DATE_EPOCH` (default zero), with no original filename in the gzip header.

```sh
python3 -m unittest discover -s tests -v
python3 tools/release.py --check
python3 tools/release.py
./build-arch.sh
```

`dist/arch/PKGBUILD` receives the archive's SHA-256. The checked-in PKGBUILD is a template with an invalid checksum placeholder, so directly building it cannot silently skip source verification. `makepkg` checks the source and runs tests.

Before sharing a locally built package, normalize and verify it:

```sh
mkdir -p dist/public
cp dist/discord-backup-linux-1.6.0.tar.gz dist/public/
python3 tools/package.py dist/arch/discord-backup-linux-1.6.0-1-any.pkg.tar.zst \
  --output dist/public/discord-backup-linux-1.6.0-1-any.pkg.tar.zst
(cd dist/public && sha256sum discord-backup-linux-1.6.0.tar.gz \
  discord-backup-linux-1.6.0-1-any.pkg.tar.zst > SHA256SUMS)
pacman -Qip dist/public/discord-backup-linux-1.6.0-1-any.pkg.tar.zst
```

The normalizer requires exactly the expected installed files and compares each with reviewed source. It removes the host package inventory and normalizes build identity/path fields, ownership, modes and timestamps. It regenerates `.MTREE`. This deliberately reduces `.BUILDINFO` and is not a full reproducible-build environment record. `makepkg`'s direct output remains available locally; use the normalized copy for publication. Binary package equality across different host toolchains is not promised.

`python3 tools/release.py --stage /path/to/a/new/staging-directory` creates a source-only publication copy. The destination must not exist. Initialize/push Git from that copy rather than from a home directory or an old local working tree. Check the exact tracked list, content and commit metadata; credentials and runtime exports must never enter Git history. Avoid personal email addresses in local commit configuration.

Build assets may be attached to a GitHub release or stored under `builds/vVERSION` with their checksum file. They are generated output, excluded from the source archive. Verify all uploaded artifact hashes against the reviewed local files. Do not upload `dist` wholesale: it may contain old builds and raw host metadata.

CI runs offline tests and source checks on pull requests and pushes. It has read-only repository permissions and does not publish or use Discord credentials. Check its actual result before describing a version as tested on the minimum Python version.
