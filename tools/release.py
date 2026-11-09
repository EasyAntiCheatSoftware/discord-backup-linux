#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build a deterministic source archive from an explicit, checked publication list."""

import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "dist", "builds", ".benchmarks", ".legacy-launchers", "__pycache__", ".venv"}
EXECUTABLES = {"run.sh", "build-arch.sh", "packaging/arch/discord-backup"}
# Split patterns keep the scanner's own source from resembling a credential.
SENSITIVE = {
    "private filesystem path": re.compile(rb"/(?:" + rb"home|Users)/[A-Za-z0-9_.-]+/"),
    "Discord token": re.compile(rb"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,40}\." + rb"[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,120}(?![A-Za-z0-9_-])"),
    "MFA token": re.compile(rb"mfa" + rb"\.[A-Za-z0-9_-]{60,}"),
    "GitHub credential": re.compile(rb"(?:gh[pousr]_" + rb"[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "private key": re.compile(rb"-----BEGIN " + rb"(?:[A-Z]+ )?PRIVATE KEY-----"),
    "cloud access key": re.compile(rb"(?:AKIA|ASIA)" + rb"[A-Z0-9]{16}"),
    "API secret": re.compile(rb"sk-(?:proj-)?" + rb"[A-Za-z0-9_-]{40,}"),
    "backup ciphertext": re.compile(rb"^DBL" + rb"ENC1\n"),
}


def check_content(name, content):
    if len(content) > 2 * 1024 * 1024:
        raise ValueError(f"Unexpected large publication file: {name}")
    content.decode("utf-8")  # Source payload is text only, including synthetic fixtures.
    for label, pattern in SENSITIVE.items():
        if pattern.search(content):
            # Never print the matching value, including in exceptions.
            raise ValueError(f"Publication check failed: {label} in {name}")


def manifest(root=ROOT):
    lines = (root / "release-files.txt").read_text().splitlines()
    names = [line for line in lines if line and not line.startswith("#")]
    if names != sorted(set(names)):
        raise ValueError("release-files.txt must be sorted with no duplicates")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("Invalid release manifest path")
        local = root / name
        if any(parent.is_symlink() for parent in [local, *local.parents] if parent != root.parent):
            raise ValueError(f"Symlink in publication input: {name}")
        if not local.is_file():
            raise ValueError(f"Missing release file: {name}")
        check_content(name, local.read_bytes())
    return names


def verify_tree(root=ROOT):
    names = manifest(root)
    expected = set(names)
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs[:] = [name for name in subdirs if name not in IGNORED_DIRS]
        for name in [*subdirs, *files]:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"Unexpected symlink: {path.relative_to(root)}")
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            relative = str((Path(directory) / name).relative_to(root))
            if relative not in expected:
                raise ValueError(f"Unlisted source file; review before release: {relative}")
    return names


def version(root=ROOT):
    return re.search(r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$',
                     (root / "discord_backup/__init__.py").read_text(), re.M).group(1)


def build(root=ROOT, output=None, stage=None):
    names = verify_tree(root)
    output = Path(output) if output else root / "dist"
    output.mkdir(parents=True, exist_ok=True)
    release = f"discord-backup-linux-{version(root)}"
    archive = output / f"{release}.tar.gz"
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    if epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be nonnegative")
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as handle:
                for name in names:
                    content = (root / name).read_bytes()
                    entry = tarfile.TarInfo(f"{release}/{name}")
                    entry.size, entry.mtime = len(content), epoch
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = "root"
                    entry.mode = 0o755 if name in EXECUTABLES else 0o644
                    handle.addfile(entry, io.BytesIO(content))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    arch = output / "arch"
    arch.mkdir(exist_ok=True)
    shutil.copyfile(archive, arch / archive.name)
    recipe = (root / "packaging/arch/PKGBUILD").read_text()
    (arch / "PKGBUILD").write_text(recipe.replace("'@SOURCE_SHA256@'", f"'{digest}'"))
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    if stage is not None:
        stage = Path(stage)
        if stage.exists():
            raise ValueError("Publication stage already exists; use a new directory")
        stage.mkdir(parents=True)
        for name in names:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, destination)
            destination.chmod(0o755 if name in EXECUTABLES else 0o644)
        verify_tree(stage)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the exact source manifest without building")
    parser.add_argument("--stage", type=Path, help="Also copy exactly the reviewed files into a new directory")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.check:
        print(f"Checked {len(verify_tree())} release files")
    else:
        print(f"Source archive: {build(output=args.output, stage=args.stage)}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, UnicodeError) as error:
        raise SystemExit(str(error)) from None
