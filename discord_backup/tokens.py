# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only discovery of account tokens in the current user's Linux client caches."""

import base64
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat

from .api import DiscordClient, DiscordError, PooledTransport, RateLimiter
from .backup import user_label
from .storage import snowflake, xdg_path

TOKEN_PATTERN = re.compile(rb"(?<![A-Za-z0-9_-])(?:[A-Za-z0-9_-]{20,40}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,120}|mfa\.[A-Za-z0-9_-]{80,120})(?![A-Za-z0-9_-])")
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_CANDIDATES = 50
CHUNK_SIZE = 1024 * 1024


@dataclass
class Candidate:
    token: str = field(repr=False)
    sources: list = field(default_factory=list)
    user: dict | None = None


@dataclass
class ScanResult:
    candidates: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    files_read: int = 0


def cache_locations(*, browsers=False, home=None):
    home = Path(home) if home else Path.home()
    config = xdg_path("XDG_CONFIG_HOME", ".config") if home == Path.home() else home / ".config"
    roots = []
    for app in ("discord", "discordcanary", "discordptb", "discorddevelopment", "Discord", "DiscordCanary", "DiscordPTB"):
        roots.append((app, config / app / "Local Storage/leveldb"))
    roots.extend([
        ("Discord Flatpak", home / ".var/app/com.discordapp.Discord/config/discord/Local Storage/leveldb"),
        ("Discord Canary Flatpak", home / ".var/app/com.discordapp.DiscordCanary/config/discordcanary/Local Storage/leveldb"),
        ("Vesktop", config / "vesktop/sessionData/Local Storage/leveldb"),
        ("Vesktop", config / "vesktop/Local Storage/leveldb"),
        ("Vesktop Flatpak", home / ".var/app/dev.vencord.Vesktop/config/vesktop/sessionData/Local Storage/leveldb"),
        ("Vesktop Flatpak", home / ".var/app/dev.vencord.Vesktop/config/vesktop/Local Storage/leveldb"),
        ("ArmCord", config / "ArmCord/Local Storage/leveldb"),
        ("Legcord", config / "legcord/Local Storage/leveldb"),
    ])
    if browsers:
        for name, directory in (("Chromium", config / "chromium"), ("Chrome", config / "google-chrome"),
                                ("Brave", config / "BraveSoftware/Brave-Browser"), ("Edge", config / "microsoft-edge")):
            roots.append((name, directory / "Default/Local Storage/leveldb"))
            if directory.is_dir():
                roots.extend((name, profile / "Local Storage/leveldb") for profile in sorted(directory.glob("Profile *")) if not profile.is_symlink())
    return roots


def plausible_token(raw):
    if raw.startswith(b"mfa."):
        return True
    try:
        first = raw.split(b".", 1)[0]
        uid = base64.urlsafe_b64decode(first + b"=" * (-len(first) % 4)).decode("ascii")
        return snowflake(uid)
    except (ValueError, UnicodeError):
        return False


def scan_tokens(*, browsers=False, extra_paths=(), locations=None):
    """Never modify caches, follow file symlinks, read other users' files, or log tokens."""
    result, found, seen_files, total = ScanResult(), {}, set(), 0

    def remember(content, label, *, before=None):
        for match in TOKEN_PATTERN.finditer(content):
            if before is not None and match.start() >= before:
                continue
            raw = match.group()
            if not plausible_token(raw):
                continue
            token = raw.decode("ascii")
            if token not in found:
                if len(found) >= MAX_CANDIDATES:
                    return
                found[token] = Candidate(token)
            if label not in found[token].sources:
                found[token].sources.append(label)

    roots = list(locations if locations is not None else cache_locations(browsers=browsers))
    roots.extend(("Selected cache", Path(path).expanduser()) for path in extra_paths)
    for label, directory in roots:
        directory = Path(directory)
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            paths = sorted((path for path in directory.iterdir() if path.suffix in (".ldb", ".log")), key=lambda path: path.name, reverse=True)
        except OSError:
            result.warnings.append(f"{label}: cache could not be read")
            continue
        for path in paths:
            if total >= MAX_TOTAL or len(found) >= MAX_CANDIDATES:
                result.warnings.append("Scan limit reached; use a specific --scan-path or manual entry if needed")
                result.candidates = list(found.values())
                return result
            fd = -1
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                info = os.fstat(fd)
                identity = (info.st_dev, info.st_ino)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or identity in seen_files:
                    continue
                seen_files.add(identity)
                if info.st_size > MAX_FILE or total + info.st_size > MAX_TOTAL:
                    result.warnings.append(f"{label}: a cache file exceeded the scan size limit")
                    continue
                with os.fdopen(fd, "rb") as handle:
                    fd = -1
                    result.files_read += 1
                    overlap, remaining, encrypted = b"", MAX_FILE, False
                    while remaining > 0:
                        chunk = handle.read(min(CHUNK_SIZE, remaining, MAX_TOTAL - total))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        total += len(chunk)
                        content = overlap + chunk
                        encrypted |= b"dQw4w9WgXcQ:" in content
                        safe_end = max(0, len(content) - 512)
                        remember(content, label, before=safe_end)
                        overlap = content[safe_end:]
                    remember(overlap, label)
                    if encrypted:
                        result.warnings.append(f"{label}: encrypted credential entries were found; unreadable entries require manual token entry")
            except OSError:
                result.warnings.append(f"{label}: a cache file could not be read")
            finally:
                if fd != -1:
                    os.close(fd)
    result.candidates = list(found.values())
    result.warnings = list(dict.fromkeys(result.warnings))
    return result


def token_user_id(token):
    if token.startswith("mfa."):
        return None
    try:
        first = token.split(".", 1)[0].encode("ascii")
        uid = base64.urlsafe_b64decode(first + b"=" * (-len(first) % 4)).decode("ascii")
        return uid if snowflake(uid) else None
    except (ValueError, UnicodeError):
        return None


def validate_candidates(candidates, *, client_factory=None, log=lambda message: None):
    accounts, by_id = [], {}
    transport = PooledTransport() if client_factory is None else None
    limiter = RateLimiter(log=log)
    try:
        for candidate in candidates:
            known = by_id.get(token_user_id(candidate.token))
            if known is not None:
                known.sources = list(dict.fromkeys(known.sources + candidate.sources))
                continue
            client = client_factory(candidate.token) if client_factory else DiscordClient(candidate.token, transport=transport, limiter=limiter, log=log)
            try:
                me = client.request("GET", "/users/@me")
            except DiscordError as error:
                if error.status == 401:
                    continue
                raise DiscordError("Unable to verify scanned accounts; check your connection or enter a token manually", error.status, error.fatal) from None
            finally:
                close = getattr(client, "close", None)
                if close:
                    close()
            if not isinstance(me, dict) or not snowflake(me.get("id")) or not isinstance(me.get("username"), str) or me.get("bot"):
                continue
            uid = str(me["id"])
            if uid in by_id:
                by_id[uid].sources = list(dict.fromkeys(by_id[uid].sources + candidate.sources))
                continue
            candidate.user = {key: me.get(key) for key in ("id", "username", "global_name", "discriminator")}
            by_id[uid] = candidate
            accounts.append(candidate)
    finally:
        if transport:
            transport.close()
    return accounts


def account_label(candidate):
    return f"{user_label(candidate.user)} ({candidate.user['id']}) — {', '.join(candidate.sources)}"
