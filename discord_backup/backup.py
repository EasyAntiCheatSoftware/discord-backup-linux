# SPDX-License-Identifier: AGPL-3.0-only
"""Collect the upstream backup fields, checkpointing every completed section."""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import time

from . import __version__
from .api import DiscordError
from .encryption import require_gpg, validate_passphrase
from .progress import EstimateReporter, estimate_remaining
from .storage import BackupWriteError, backup_directory, private_directory, snowflake, validate_folders, write_backup


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def user_label(user):
    username = user.get("username", user.get("id", "Unknown"))
    discriminator = str(user.get("discriminator", "0"))
    return f"{username}#{discriminator}" if discriminator not in ("0", "", "None") else str(username)


def object_list(value):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Expected a list of objects")
    return value


class BackupInterrupted(DiscordError):
    pass


class Collector:
    def __init__(self, client, directory=None, *, passphrase, create_invites=True, log=print,
                 clock=time.monotonic, checkpoint_interval=5, workers=3, progress_interval=5):
        self.client = client
        self.directory = Path(directory) if directory else backup_directory()
        self.create_invites = create_invites
        self.log = log
        self.path = None
        self.data = {}
        self.passphrase = validate_passphrase(passphrase, creating=True)
        self.clock = clock
        self.checkpoint_interval = checkpoint_interval
        self._last_checkpoint = float("-inf")
        self.checkpoints_written = 0
        if workers not in (1, 2, 3, 4):
            raise ValueError("Choose between one and four backup workers")
        self.workers = workers
        self._pool = None
        self.checkpoint_seconds = 0
        self.phase_seconds = {}
        self._started = None
        self._last_estimate = float("-inf")
        self._invite_done = {"Servers": 0, "Groups": 0}
        self._profile_requests = 0
        self.progress_interval = progress_interval
        self._reporter = None
        require_gpg()

    def checkpoint(self, *, force=False):
        if not force and self.clock() - self._last_checkpoint < self.checkpoint_interval:
            return False
        started = self.clock()
        write_backup(self.path, self.data, passphrase=self.passphrase)
        self.checkpoint_seconds += max(0, self.clock() - started)
        self._last_checkpoint = self.clock()
        self.checkpoints_written += 1
        return True

    def warning(self, message):
        self.data["warnings"].append(message)
        self.log(f"Warning: {message}")

    def optional(self, label, action):
        try:
            return action()
        except BackupWriteError:
            raise
        except DiscordError as error:
            if error.fatal:
                raise
            if error.status == 403:
                detail = "Discord denied access (HTTP 403); this item was skipped"
            elif error.status in (404, 405):
                detail = f"Discord did not provide this data (HTTP {error.status}); it is missing from this backup"
            elif error.status >= 500:
                detail = f"Discord temporarily failed (HTTP {error.status}); try another backup later"
            else:
                detail = str(error)
            if "invite" in label.lower():
                detail += ". Membership/contact data already collected is kept; this invite may be unavailable"
            self.warning(f"{label}: {detail}")
        except (ValueError, KeyError, TypeError, IndexError):
            self.warning(f"{label}: Discord returned an unsupported or incomplete format; some data in this section may be missing")
        return None

    def server_jobs(self):
        return [entry for entry in self.data["guilds"] if self.create_invites or
                "VANITY_URL" in self._guild_lookup[entry["id"]].get("features", [])]

    def estimate(self, *, force=False):
        sections = self.data["sections"]
        now = self.clock()
        if not force and now - self._last_estimate < 5:
            return None
        if not any(sections.get(key) == "saved" for key in ("guilds", "direct-messages")) and not all(
                key in self.phase_seconds for key in ("guilds", "direct-messages")):
            self._reporter.publish(self.data["name"], note="loading server/group counts")
            self._last_estimate = now
            return None
        stats = self.client.performance()
        latency = stats["http_worker_seconds"] / stats["requests"] if stats["http_worker_seconds"] and stats["requests"] else 0.25
        checkpoint = self.checkpoint_seconds / max(1, self.checkpoints_written)
        metadata = {"guilds": 1, "direct-messages": 1, "profile": self._profile_requests,
                    "relationships": 1, "folders": 1, "favourite-gifs": 1}
        reads = sum(calls for key, calls in metadata.items() if key not in self.phase_seconds)
        jobs = self.server_jobs()
        servers = max(0, len(jobs) - self._invite_done["Servers"])
        groups = max(0, len(self.data["group-chats"]) - self._invite_done["Groups"]) if self.create_invites else 0
        hints = self.client.limiter.invite_forecast()
        remaining = estimate_remaining(request_seconds=latency, checkpoint_seconds=checkpoint,
            metadata_requests=reads, checkpoints=max(1, 9 - len(self.phase_seconds)),
            server_jobs=servers, server_requests_per_job=2 if self.create_invites else 1,
            group_jobs=groups, workers=self.workers, invite_wait=hints["wait_seconds"], serial_invites=hints["serial"])
        pending = [label for key, label in (("guilds", "server count pending"), ("direct-messages", "group count pending"))
                   if key not in self.phase_seconds]
        missing = [label for key, label in (("guilds", "server list unavailable"), ("direct-messages", "group list unavailable"))
                   if key in self.phase_seconds and sections.get(key) != "saved"]
        notes = (["preliminary; " + ", ".join(pending)] if pending else []) + (
                 ["available data only; " + ", ".join(missing)] if missing else [])
        self._reporter.publish(self.data["name"], remaining=remaining, note="; ".join(notes))
        self._last_estimate = now
        return remaining

    def run(self):
        self._started = self.clock()
        with EstimateReporter(self.log, clock=self.clock, interval=self.progress_interval,
                              hints=self.client.limiter.invite_forecast) as reporter:
            self._reporter = reporter
            reporter.publish("selected account", note="checking account and loading its workload")
            try:
                return self._run()
            finally:
                self._reporter = None

    def _run(self):
        started = self._started
        me = self.client.request("GET", "/users/@me")
        if not isinstance(me, dict) or not snowflake(me.get("id")) or not isinstance(me.get("username"), str):
            raise DiscordError("Unexpected account profile response")
        if me.get("bot"):
            raise DiscordError("Use your own account token; bot accounts do not contain account backups")
        self.data = {
            "version": f"linux-{__version__}", "schema_version": 1,
            "created_at": utc_now(), "status": "partial", "sections": {}, "warnings": [],
            "id": str(me["id"]), "name": me["username"],
            "discriminator": str(me.get("discriminator", "0")),
            "global_name": me.get("global_name"), "bio": me.get("bio") or "",
            "avatar-bytes": "", "banner-bytes": "", "users": {},
            "friends": [], "blocked": [], "incoming": [], "outgoing": [],
            "guilds": [], "guild_folders": None, "group-chats": [], "dm-history": [],
        }
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        self.path = private_directory(self.directory) / f"backup-{stamp}-{secrets.token_hex(6)}.bkup"
        self._reporter.publish(me["username"], note="loading server/group counts")
        self.checkpoint(force=True)
        self.log(f"Backing up {user_label(me)}")
        self.log("Estimating this account's backup time; reading its memberships first…")
        self._profile_requests = int("bio" not in me or "banner" not in me) + sum(bool(me.get(key)) for key in ("avatar", "banner"))
        self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="discord-backup")
        label = "preparation"
        try:
            tasks = [("guilds", self.guilds), ("relationships", self.relationships),
                     ("direct-messages", self.channels), ("profile", lambda: self.profile(me)),
                     ("folders", self.folders), ("favourite-gifs", self.gifs),
                     ("server-invites", self.server_invites), ("group-invites", self.group_invites)]
            self.data["sections"] = {label: "pending" for label, _ in tasks}
            for label, action in tasks:
                self.log(f"Saving {label}…")
                before = len(self.data["warnings"])
                phase_started = self.clock()
                self.optional(label, action)
                self.phase_seconds[label] = round(self.clock() - phase_started, 3)
                self.data["sections"][label] = "saved" if len(self.data["warnings"]) == before else "partial"
                self.checkpoint(force=True)
                self.estimate(force=True)
            self.data["status"] = "partial" if self.data["warnings"] else "complete"
        except (DiscordError, KeyboardInterrupt) as error:
            self.client.cancel(error if isinstance(error, DiscordError) else None)
            self.data["interrupted"] = True
            self.data["sections"][label] = "interrupted"
            reason = str(error) if isinstance(error, DiscordError) else "Cancelled"
            self.warning(f"Backup interrupted: {reason}. Completed sections were preserved; later sections may not have been attempted")
            raise BackupInterrupted(f"{reason}. Saved partial backup: {self.path}") from error
        finally:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
            self.data["finished_at"] = utc_now()
            self.data["duration_seconds"] = round(self.clock() - started, 2)
            self.data["cooldown_seconds"] = round(self.client.limiter.cooldown_seconds, 2)
            self.data["performance"] = {**self.client.performance(), "workers": self.workers,
                                        "phase_seconds": self.phase_seconds,
                                        "checkpoint_seconds": round(self.checkpoint_seconds, 3)}
            self.checkpoint(force=True)
        return self.path, self.data

    def invite_results(self, entries, action, label):
        """Workers only fetch results; data updates and encrypted saves stay on one thread."""
        if not entries:
            return
        if self._pool is None or self.workers == 1:
            for index, entry in enumerate(entries, 1):
                self.log(f"{label} [{index}/{len(entries)}] {entry.get('name', 'Unknown')} | {self._reporter.short()}")
                entry["invite-code"] = self.optional(f"{label[:-1]} invite ({entry.get('name', 'Unknown')})", lambda entry=entry: action(entry))
                self._invite_done[label] += 1
                self.checkpoint()
                self.estimate()
            return
        futures = {self._pool.submit(action, entry): entry for entry in entries}
        for index, future in enumerate(as_completed(futures), 1):
            entry = futures[future]
            entry["invite-code"] = self.optional(f"{label[:-1]} invite ({entry.get('name', 'Unknown')})", future.result)
            self._invite_done[label] += 1
            self.log(f"{label} [{index}/{len(entries)}] {entry.get('name', 'Unknown')} | {self._reporter.short()}")
            self.checkpoint()
            self.estimate()

    def remember_user(self, user):
        if not isinstance(user, dict) or not snowflake(user.get("id")):
            raise ValueError("Invalid user")
        uid = str(user["id"])
        self.data["users"][uid] = {key: user.get(key) for key in ("id", "username", "global_name", "discriminator")}
        return uid

    def profile(self, me):
        # A profile response can contain bio/banner omitted by /users/@me.
        if "bio" not in me or "banner" not in me:
            result = self.optional("Extended profile", lambda: self.client.request("GET", f"/users/{me['id']}/profile"))
            if isinstance(result, dict):
                me = {**me, **(result.get("user") or {})}
                self.data["bio"] = (result.get("user_profile") or {}).get("bio", me.get("bio", "")) or ""
        for kind in ("avatar", "banner"):
            asset_hash = me.get(kind)
            if not asset_hash:
                continue
            if not isinstance(asset_hash, str) or not re.fullmatch(r"(?:a_)?[a-fA-F0-9]+", asset_hash):
                self.warning(f"{kind}: invalid image identifier")
                continue
            extension = "gif" if asset_hash.startswith("a_") else "png"
            url = f"https://cdn.discordapp.com/{kind}s/{me['id']}/{asset_hash}.{extension}?size=1024"
            image = self.optional(kind, lambda: self.client.asset(url))
            if image is not None:
                self.data[f"{kind}-bytes"] = base64.b64encode(image).decode("ascii")

    def relationships(self):
        relationships = object_list(self.client.request("GET", "/users/@me/relationships"))
        mapping = {1: "friends", 2: "blocked", 3: "incoming", 4: "outgoing"}
        for relationship in relationships:
            user = relationship.get("user") or {"id": relationship["id"]}
            uid = self.remember_user(user)
            if relationship.get("type") in mapping:
                self.data[mapping[relationship["type"]]].append(uid)

    def folders(self):
        settings = self.client.request("GET", "/users/@me/settings")
        if not isinstance(settings, dict) or "guild_folders" not in settings:
            raise ValueError("Folder layout unavailable")
        self.data["guild_folders"] = validate_folders(settings["guild_folders"])

    def gifs(self):
        result = self.client.request("GET", "/users/@me/settings-proto/2")
        if not isinstance(result, dict) or not isinstance(result.get("settings"), str):
            raise ValueError("GIF settings unavailable")
        base64.b64decode(result["settings"], validate=True)
        self.data["settings"] = result["settings"]

    def create_invite(self, channel_id, max_age):
        if not snowflake(channel_id):
            raise ValueError("Invalid channel ID")
        invite = self.client.request("POST", f"/channels/{channel_id}/invites", {
            "max_age": max_age, "max_uses": 0, "temporary": False, "unique": False,
        })
        if not isinstance(invite, dict) or not re.fullmatch(r"[A-Za-z0-9_-]+", str(invite.get("code", ""))):
            raise ValueError("Invalid invite response")
        return invite["code"]

    def guild_invite(self, guild):
        if "VANITY_URL" in guild.get("features", []):
            details = self.client.request("GET", f"/guilds/{guild['id']}")
            if isinstance(details, dict) and details.get("vanity_url_code"):
                return details["vanity_url_code"]
        if not self.create_invites:
            return None
        channels = object_list(self.client.request("GET", f"/guilds/{guild['id']}/channels"))
        channels = [channel for channel in channels if channel.get("type") in (0, 2, 5, 13)]
        channels.sort(key=lambda channel: (not any(word in str(channel.get("name", "")).lower() for word in ("general", "rules", "welcome")), str(channel.get("id", ""))))
        for channel in channels[:5]:
            try:
                age = 0 if "COMMUNITY" in guild.get("features", []) else 2592000
                return self.create_invite(channel["id"], age)
            except DiscordError as error:
                if error.fatal or error.status not in (403, 404):
                    raise
        raise DiscordError("No accessible channel allowed an invite")

    def guilds(self):
        guilds = self.client.guilds()
        self._guild_lookup = {str(guild["id"]): guild for guild in guilds}
        # Save server membership before making requests that could be interrupted.
        self.data["guilds"] = [{"id": str(guild["id"]), "name": guild.get("name", "Unknown"), "invite-code": None} for guild in guilds]
    def server_invites(self):
        self.invite_results(self.server_jobs(), lambda entry: self.guild_invite(self._guild_lookup[entry["id"]]), "Servers")

    def channels(self):
        channels = object_list(self.client.request("GET", "/users/@me/channels"))
        # Capture every contact before attempting group invitations.
        for channel in channels:
            recipients = channel.get("recipients", [])
            for user in recipients:
                self.remember_user(user)
            if channel.get("type") == 1 and recipients:
                self.data["dm-history"].append({
                    "id": str(channel["id"]), "user_id": str(recipients[0]["id"]),
                    "user": user_label(recipients[0]), "last_message_id": channel.get("last_message_id"),
                })
            elif channel.get("type") == 3:
                self.data["group-chats"].append({
                    "id": str(channel["id"]), "name": channel.get("name") or ", ".join(user_label(user) for user in recipients),
                    "recipients": [str(user["id"]) for user in recipients], "invite-code": None,
                })
        self.data["dm-history"].sort(key=lambda entry: int(entry.get("last_message_id") or 0), reverse=True)

    def group_invites(self):
        if self.create_invites:
            self.invite_results(self.data["group-chats"], lambda group: self.create_invite(group["id"], 604800), "Groups")
