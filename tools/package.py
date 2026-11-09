#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Normalize a freshly built Arch package and verify its exact installed payload."""

import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

from release import ROOT, check_content, manifest


def installed_files(root=ROOT):
    mapping = {f"usr/lib/discord-backup-linux/{name}": name for name in manifest(root)
               if name.startswith("discord_backup/") or name == "main.py"}
    mapping.update({
        "usr/bin/discord-backup": "packaging/arch/discord-backup",
        "usr/share/applications/discord-backup.desktop": "packaging/discord-backup.desktop",
        **{f"usr/share/doc/discord-backup-linux/{name}": name for name in ("README.md", "UNLOCK_BACKUP.md", "NOTICE")},
        "usr/share/licenses/discord-backup-linux/LICENSE": "LICENSE",
    })
    return mapping


def normalize(source, output, root=ROOT):
    mapping = installed_files(root)
    files = {}
    with tempfile.TemporaryFile() as raw:
        subprocess.run(["zstd", "--quiet", "--decompress", "--stdout", str(source)], stdout=raw, check=True)
        raw.seek(0)
        with tarfile.open(fileobj=raw, mode="r:") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if member.isdir():
                    continue
                if not member.isfile() or name not in {*mapping, ".PKGINFO", ".BUILDINFO", ".MTREE"} or name in files:
                    raise ValueError(f"Unexpected Arch package entry: {name}")
                if member.size > 2 * 1024 * 1024:
                    raise ValueError(f"Oversized Arch package entry: {name}")
                files[name] = archive.extractfile(member).read()
    if set(files) != {*mapping, ".PKGINFO", ".BUILDINFO", ".MTREE"}:
        raise ValueError("Arch package is missing expected files")
    for installed, source_name in mapping.items():
        if files[installed] != (root / source_name).read_bytes():
            raise ValueError(f"Installed content differs from reviewed source: {source_name}")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    public_builder = "Discord Backup Linux contributors"
    pkginfo = []
    for line in files[".PKGINFO"].decode().splitlines():
        if line.startswith("#"):
            continue
        if line.startswith("packager = "):
            line = f"packager = {public_builder}"
        if line.startswith("builddate = "):
            line = f"builddate = {epoch}"
        pkginfo.append(line)
    files[".PKGINFO"] = ("\n".join(pkginfo) + "\n").encode()
    # Avoid publishing the local package inventory, build directories or identity.
    allowed = {"format", "pkgname", "pkgbase", "pkgver", "pkgarch", "pkgbuild_sha256sum", "buildtool", "buildtoolver"}
    buildinfo = [line for line in files[".BUILDINFO"].decode().splitlines() if line.split(" = ", 1)[0] in allowed]
    buildinfo += [f"packager = {public_builder}", f"builddate = {epoch}", "builddir = /build/discord-backup-linux"]
    files[".BUILDINFO"] = ("\n".join(buildinfo) + "\n").encode()
    del files[".MTREE"]
    for name, data in files.items():
        check_content(name, data)
    with tempfile.TemporaryDirectory(prefix="discord-package-") as directory:
        staging = Path(directory)
        modes = {}
        for name, data in files.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            modes[name] = 0o755 if name == "usr/bin/discord-backup" else 0o644
            path.chmod(modes[name])
        directories = sorted(str(path.relative_to(staging)) for path in staging.rglob("*") if path.is_dir())
        for path in staging.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            os.utime(path, (epoch, epoch))
        entries = sorted([*files, *directories])
        mtree = subprocess.run(["bsdtar", "--uid", "0", "--gid", "0", "-cnf", "-", "--format=mtree",
                                "--options=!all,use-set,type,uid,gid,mode,time,size,sha256,link",
                                "--no-recursion", "--null", "--files-from", "-"],
                               input=("\0".join(entries) + "\0").encode(), cwd=staging,
                               capture_output=True, check=True).stdout
        files[".MTREE"] = gzip.compress(mtree, mtime=0)
        with tempfile.TemporaryFile() as normalized:
            with tarfile.open(fileobj=normalized, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name in [".PKGINFO", ".BUILDINFO", ".MTREE", *directories, *sorted(mapping)]:
                    entry = tarfile.TarInfo(name + ("/" if name in directories else ""))
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = "root"
                    entry.mtime = epoch
                    if name in directories:
                        entry.type, entry.mode = tarfile.DIRTYPE, 0o755
                        archive.addfile(entry)
                    else:
                        entry.mode = modes.get(name, 0o644)
                        entry.size = len(files[name])
                        archive.addfile(entry, io.BytesIO(files[name]))
            normalized.seek(0)
            with Path(output).open("wb") as destination:
                subprocess.run(["zstd", "--quiet", "--stdout", "-T1", "-19"], stdin=normalized, stdout=destination, check=True)
    return hashlib.sha256(Path(output).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.package.resolve() == args.output.resolve():
        parser.error("use a separate output path")
    digest = normalize(args.package, args.output)
    print(f"{digest}  {args.output.name}")


if __name__ == "__main__":
    main()
