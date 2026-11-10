# SPDX-License-Identifier: AGPL-3.0-only
"""Private, atomic storage and validation for current and upstream JSON .bkup files."""

import json
import math
import os
from pathlib import Path
import stat
import tempfile

from .encryption import MAGIC, MAX_CIPHERTEXT, decrypt, encrypt, validate_passphrase

MAX_BACKUP_BYTES = 64 * 1024 * 1024


class BackupWriteError(ValueError):
    """A local persistence failure, never an optional Discord format warning."""


def is_partial(data):
    return data.get("status") == "partial" or data.get("interrupted") is True or any(
        state in ("partial", "pending", "interrupted") for state in data.get("sections", {}).values())


def recovery_notice(data):
    if is_partial(data):
        return ("PARTIAL BACKUP: collection did not finish successfully. Saved sections, contacts, profile files and "
                "available invitations can still be recovered. Check sections and warnings for missing work; "
                "a new backup is needed to collect missing data. This file cannot be resumed.")
    return "Complete backup. Check warnings and invitation validity before recovery."


def xdg_path(variable, fallback):
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def backup_directory():
    return xdg_path("XDG_DATA_HOME", ".local/share") / "discord-backup-linux/backups"


def private_directory(path):
    path = Path(path).expanduser()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ValueError("Output must be a directory")
    return path


def atomic_write(path, content):
    """Replace a file atomically with mode 0600, including on permissive umasks."""
    path = Path(path).expanduser()
    private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".backup-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_backup(path, data, *, passphrase):
    try:
        content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError("Backup exceeds the 64 MiB limit; previous checkpoint was preserved")
        atomic_write(path, encrypt(content, passphrase, filename="backup-partial.json" if is_partial(data) else "backup.json"))
    except (ValueError, RecursionError) as error:
        raise BackupWriteError(str(error)) from error


def is_encrypted(path):
    with Path(path).expanduser().open("rb") as handle:
        return handle.read(len(MAGIC)) == MAGIC


def snowflake(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return False
    text = str(value)
    return 1 <= len(text) <= 20 and text.isascii() and text.isdigit() and 0 < int(text) < 2**64


def validate_folders(folders):
    if not isinstance(folders, list):
        raise ValueError("Folder layout must be a list")
    for folder in folders:
        if not isinstance(folder, dict) or not isinstance(folder.get("guild_ids"), list):
            raise ValueError("Each folder must have a guild_ids list")
        if not all(snowflake(guild) for guild in folder["guild_ids"]):
            raise ValueError("Invalid server ID in folder layout")
        if folder.get("id") is not None and not snowflake(folder["id"]):
            raise ValueError("Invalid folder ID")
        if folder.get("name") is not None and not isinstance(folder["name"], str):
            raise ValueError("Invalid folder name")
        color = folder.get("color")
        if color is not None and (type(color) is not int or not 0 <= color <= 0xFFFFFF):
            raise ValueError("Invalid folder color")
    return folders


def read_backup(path, *, passphrase=None):
    with Path(path).expanduser().open("rb") as handle:
        raw = handle.read(MAX_CIPHERTEXT + 1)
    if len(raw) > MAX_CIPHERTEXT:
        raise ValueError("Backup exceeds the 64 MiB limit")
    if raw.startswith(MAGIC):
        if passphrase is None:
            raise ValueError("This backup is encrypted; enter its backup passphrase")
        raw = decrypt(raw, passphrase)
    if len(raw) > MAX_BACKUP_BYTES:
        raise ValueError("Backup exceeds the 64 MiB limit")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("Backup must be a UTF-8 JSON .bkup file") from error
    if not isinstance(data, dict) or not snowflake(data.get("id")) or not isinstance(data.get("name"), str):
        raise ValueError("Not a Discord-Backup file: missing account id or name")
    if "schema_version" in data and (type(data["schema_version"]) is not int or data["schema_version"] != 1):
        raise ValueError("Unsupported backup schema version")
    for key in ("guilds", "group-chats", "dm-history"):
        if key in data and (not isinstance(data[key], list) or not all(isinstance(item, dict) for item in data[key])):
            raise ValueError(f"Invalid {key} list in backup")
    for key in ("friends", "blocked", "incoming", "outgoing"):
        if key in data and (not isinstance(data[key], list) or not all(snowflake(item) for item in data[key])):
            raise ValueError(f"Invalid {key} list in backup")
    if data.get("guild_folders") is not None:
        validate_folders(data["guild_folders"])
    for key in ("bio", "avatar-bytes", "banner-bytes", "settings"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"Invalid {key} in backup")
    if not isinstance(data.get("users", {}), dict) or not isinstance(data.get("warnings", []), list):
        raise ValueError("Invalid backup metadata")
    if not isinstance(data.get("sections", {}), dict) or any(
            not isinstance(key, str) or state not in ("saved", "partial", "pending", "interrupted")
            for key, state in data.get("sections", {}).items()):
        raise ValueError("Invalid backup section status")
    if "status" in data and data["status"] not in ("partial", "complete"):
        raise ValueError("Invalid backup status")
    if "interrupted" in data and type(data["interrupted"]) is not bool:
        raise ValueError("Invalid interruption status")
    if is_partial(data):
        data["status"] = "partial"
        data["recovery_notice"] = recovery_notice(data)
    for key in ("duration_seconds", "cooldown_seconds"):
        if key in data and (type(data[key]) not in (int, float) or not 0 <= data[key] <= 1e12 or not math.isfinite(data[key])):
            raise ValueError(f"Invalid {key} in backup")
    if "performance" in data:
        performance = data["performance"]
        if not isinstance(performance, dict) or not isinstance(performance.get("phase_seconds", {}), dict):
            raise ValueError("Invalid performance metadata")
        timings = performance.get("phase_seconds", {}).values()
        if any(type(value) not in (int, float) or not 0 <= value <= 1e12 or not math.isfinite(value) for value in timings):
            raise ValueError("Invalid phase timings")
    return data


def read_private_secret(path, *, label="Secret"):
    """Read one explicitly selected private file without following symlinks."""
    fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError(f"{label} file must be a regular file owned by you with mode 0600 or 0400")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            secret = handle.read(4097).rstrip("\r\n")
    finally:
        if fd != -1:
            os.close(fd)
    if len(secret) > 4096:
        raise ValueError(f"{label} file is too long")
    return secret


def read_token(path):
    return validate_token(read_private_secret(path, label="Token"))


def read_passphrase(path):
    return validate_passphrase(read_private_secret(path, label="Passphrase"))


def validate_token(token):
    token = token.strip()
    if not token or len(token) > 4096 or any(not 33 <= ord(character) <= 126 for character in token):
        raise ValueError("Enter one nonempty account token without whitespace")
    if token.lower().startswith(("bot ", "bearer ")):
        raise ValueError("This tool requires an account token")
    return token
