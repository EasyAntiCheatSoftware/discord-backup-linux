# SPDX-License-Identifier: AGPL-3.0-only
"""Offline recovery pages and explicit settings restores with rollback snapshots."""

import base64
from datetime import datetime, timezone
import html
from pathlib import Path
import re
import secrets

from .api import DiscordError
from .backup import user_label
from .storage import atomic_write, backup_directory, is_partial, recovery_notice, snowflake, validate_folders, write_backup


class AccountMismatch(ValueError):
    def __init__(self, target):
        super().__init__("Target account differs from backup. Use --allow-different-account if intentional")
        self.target = target


def summary(data):
    return {
        "account": data["name"], "id": data["id"], "version": data.get("version", "unknown"),
        "status": data.get("status", "legacy (completion not recorded)"),
        **{key: len(data.get(key, [])) for key in ("guilds", "friends", "blocked", "incoming", "outgoing", "group-chats", "dm-history")},
        "folders": len(data["guild_folders"]) if data.get("guild_folders") is not None else "unavailable",
        "favourite_gifs": "saved" if "settings" in data else "unavailable",
        "warnings": data.get("warnings", []),
        "sections": data.get("sections", {}),
        **{key: data[key] for key in ("duration_seconds", "cooldown_seconds", "performance") if key in data},
    }


def e(value):
    return html.escape(str(value), quote=True)


def user_link(uid, label=None):
    if not snowflake(uid):
        return e(label or "Unknown user")
    return f'<a href="https://discord.com/users/{uid}" rel="noreferrer">{e(label or uid)}</a>'


def table(headers, rows):
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return "<table><thead><tr>" + "".join(f"<th>{e(header)}</th>" for header in headers) + f"</tr></thead><tbody>{body}</tbody></table>" if body else "<p>No entries saved.</p>"


def image_extension(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Saved image is not PNG, GIF, JPEG, or WebP")


def export_recovery(data, directory):
    directory = Path(directory).expanduser()
    # A new directory prevents overwriting a previous recovery export.
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    notices, assets = [], []
    atomic_write(directory / "bio.txt", data.get("bio", "").encode("utf-8"))
    for kind in ("avatar", "banner"):
        if not data.get(f"{kind}-bytes"):
            continue
        try:
            raw = base64.b64decode(data[f"{kind}-bytes"], validate=True)
            filename = f"{kind}.{image_extension(raw)}"
            atomic_write(directory / filename, raw)
            assets.append(f'<a href="{filename}">{kind.title()}</a><br><img class="{kind}" src="{filename}" alt="Saved {kind}">')
        except ValueError:
            notices.append(f"{kind.title()}: invalid image data; not exported.")

    def server_rows(key):
        rows = []
        for item in data.get(key, []):
            uid = item.get("id", "")
            code = item.get("invite-code")
            invite = f'<a href="https://discord.gg/{code}" rel="noreferrer">Join via invite</a>' if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_-]+", code) else "No invite saved"
            channel_path = f"@me/{uid}" if key == "group-chats" else str(uid)
            location = f'<a href="https://discord.com/channels/{channel_path}" rel="noreferrer">Open in Discord</a>' if snowflake(uid) else ""
            rows.append([e(item.get("name", "Unknown")), e(uid), invite, location])
        return rows

    sections = ["<h2 id=profile>Profile</h2>", " ".join(assets),
                '<p><a href="bio.txt">Saved bio text</a> — apply your images and bio in Discord’s profile settings.</p>',
                f"<pre>{e(data.get('bio', ''))}</pre>",
                "<h2 id=servers>Servers</h2>", table(("Name", "Server ID", "Invite", "Existing membership"), server_rows("guilds")),
                "<h2 id=groups>Group chats</h2><p>Group invites may expire, become full, or stop working after you leave.</p>",
                table(("Name", "Channel ID", "Invite", "Existing access"), server_rows("group-chats"))]
    users = data.get("users", {})
    for key, title in (("friends", "Friends"), ("blocked", "Blocked users"), ("incoming", "Incoming requests"), ("outgoing", "Outgoing requests")):
        rows = []
        for uid in data.get(key, []):
            user = users.get(str(uid))
            rows.append([user_link(uid, user_label(user) if isinstance(user, dict) else uid), e(uid)])
        sections.extend([f"<h2>{title}</h2>", table(("User", "User ID"), rows)])
    sections.extend(["<h2 id=dms>DM contacts</h2><p>This is a contact list, not message contents. Open each profile to start a conversation.</p>",
                     table(("Contact", "Last message ID"), [[user_link(item.get("user_id"), item.get("user", item.get("user_id"))), e(item.get("last_message_id") or "")] for item in data.get("dm-history", [])]),
                     "<h2 id=folders>Server folders</h2>"])
    if data.get("guild_folders") is None:
        sections.append("<p>Folder layout was not saved.</p>")
    else:
        guild_names = {str(item.get("id")): item.get("name", item.get("id")) for item in data.get("guilds", [])}
        sections.append(table(("Folder", "Color", "Servers in order"), [
            [e(folder.get("name") or "Unfoldered"), e(f"#{folder['color']:06x}" if folder.get("color") is not None else "Default"),
             e(", ".join(str(guild_names.get(str(uid), uid)) for uid in folder["guild_ids"]))]
            for folder in data["guild_folders"]]))
    all_notices = [str(item) for item in data.get("warnings", [])] + notices
    if all_notices:
        sections.extend(["<h2>Backup and export warnings</h2><ul>", "".join(f"<li>{e(item)}</li>" for item in all_notices), "</ul>"])
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Discord account recovery</title><style>
:root{color-scheme:dark}body{font:16px/1.6 system-ui,sans-serif;background:#13151c;color:#e6e7ef;max-width:1100px;margin:40px auto;padding:0 24px}
h1,h2{line-height:1.25}h1{font-size:2.3rem}h2{margin-top:44px}a{color:#a6b8ff}nav{display:flex;gap:20px;flex-wrap:wrap}
table{border-collapse:collapse;width:100%;display:block;overflow:auto}td,th{text-align:left;padding:12px;border-bottom:1px solid #343849;vertical-align:top;overflow-wrap:anywhere}th{color:#abb4ce}
pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:20px;background:#202430;border-radius:12px}.avatar{max-width:128px;border-radius:20px}.banner{max-width:100%}.note{color:#b3bbd0}header{border-bottom:1px solid #343849;padding-bottom:24px}
</style><header><p class="note">DISCORD BACKUP · LOCAL RECOVERY</p>"""
    page += f"<h1>{e(data['name'])}</h1><p>Account {e(data['id'])} · {e(data.get('created_at', 'Legacy backup'))} · {e(data.get('status', 'Legacy status unknown'))}</p>"
    if is_partial(data):
        page += f"<aside><h2>PARTIAL BACKUP</h2><p>{e(recovery_notice(data))}</p>"
        page += table(("Section", "Status"), [[e(key), e(state)] for key, state in data.get("sections", {}).items()]) + "</aside>"
    page += '<nav><a href="#profile">Profile</a><a href="#servers">Servers</a><a href="#groups">Groups</a><a href="#dms">DM contacts</a><a href="#folders">Folders</a></nav></header>'
    page += "<p class=note>Rejoin servers with their invites and add friends manually. This page does not contact Discord until you follow a link. Expired invites and lost access cannot be recovered by this tool.</p>"
    page += "".join(sections) + "</html>\n"
    atomic_write(directory / "index.html", page.encode("utf-8"))
    return directory / "index.html", notices


def folder_plan(saved, current, guild_ids):
    """Restore joined saved servers; retain current-only servers and their folders."""
    validate_folders(saved)
    validate_folders(current)
    joined = {str(uid) for uid in guild_ids}
    seen, result, by_id = set(), [], {}
    for source in (saved, current):
        for folder in source:
            ids = []
            for value in folder["guild_ids"]:
                uid = str(value)
                if uid in joined and uid not in seen:
                    ids.append(uid)
                    seen.add(uid)
            if not ids:
                continue
            folder_id = str(folder["id"]) if folder.get("id") is not None else None
            match = by_id.get(folder_id)
            if match is not None:
                match["guild_ids"].extend(ids)
            else:
                entry = {"id": folder.get("id"), "name": folder.get("name"), "color": folder.get("color"), "guild_ids": ids}
                result.append(entry)
                if folder_id is not None:
                    by_id[folder_id] = entry
    for uid in guild_ids:
        if str(uid) not in seen:
            result.append({"id": None, "name": None, "color": None, "guild_ids": [str(uid)]})
            seen.add(str(uid))
    return {"guild_folders": result}


def check_account(client, data, allow_different):
    me = client.request("GET", "/users/@me")
    if not isinstance(me, dict) or not snowflake(me.get("id")) or not isinstance(me.get("username"), str):
        raise DiscordError("Unexpected target account response")
    if str(me["id"]) != str(data["id"]) and not allow_different:
        raise AccountMismatch(me)
    return me


def rollback_snapshot(me, fields, directory, passphrase):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    path = Path(directory or backup_directory()).expanduser() / f"rollback-{stamp}-{secrets.token_hex(6)}.bkup"
    write_backup(path, {"id": str(me["id"]), "name": me["username"], "version": "linux-rollback", **fields}, passphrase=passphrase)
    return path


def folder_signature(folders):
    validate_folders(folders)
    return [(str(item["id"]) if item.get("id") is not None else None, item.get("name"),
             item.get("color"), [str(uid) for uid in item["guild_ids"]]) for item in folders]


def restore_folders(client, data, *, apply=False, allow_different=False, directory=None, passphrase=None, log=print, expected_plan=None):
    if data.get("guild_folders") is None:
        raise ValueError("This backup has no saved folder layout")
    me = check_account(client, data, allow_different)
    guilds = client.guilds()
    current = client.request("GET", "/users/@me/settings")
    if not isinstance(current, dict) or "guild_folders" not in current:
        raise DiscordError("Current folder layout is unavailable; restore stopped")
    plan = folder_plan(data["guild_folders"], current["guild_folders"], [guild["id"] for guild in guilds])
    if expected_plan is not None and folder_signature(plan["guild_folders"]) != folder_signature(expected_plan["guild_folders"]):
        raise ValueError("Folder layout or memberships changed after preview; preview again before applying")
    log(f"Target account: {user_label(me)} ({me['id']})")
    if apply:
        path = rollback_snapshot(me, {"guild_folders": current["guild_folders"]}, directory, passphrase)
        log(f"Rollback snapshot: {path}")
        client.request("PATCH", "/users/@me/settings", plan)
        confirmed = client.request("GET", "/users/@me/settings")
        if not isinstance(confirmed, dict) or folder_signature(confirmed.get("guild_folders")) != folder_signature(plan["guild_folders"]):
            raise DiscordError("Discord did not confirm the requested folder layout; inspect your settings and the saved rollback")
        log("Folder layout restored and verified")
    return plan


def restore_gifs(client, data, *, apply=False, allow_different=False, directory=None, passphrase=None, log=print):
    if not isinstance(data.get("settings"), str):
        raise ValueError("This backup has no saved favourite GIF settings")
    base64.b64decode(data["settings"], validate=True)
    me = check_account(client, data, allow_different)
    log(f"Target account: {user_label(me)} ({me['id']})")
    log("This replaces the saved frecency settings block, including favourite GIFs and any other fields in that block")
    if apply:
        current = client.request("GET", "/users/@me/settings-proto/2")
        if not isinstance(current, dict) or not isinstance(current.get("settings"), str):
            raise DiscordError("Cannot save current GIF settings; restore stopped")
        path = rollback_snapshot(me, {"settings": current["settings"]}, directory, passphrase)
        log(f"Rollback snapshot: {path}")
        client.request("PATCH", "/users/@me/settings-proto/2", {"settings": data["settings"]})
        confirmed = client.request("GET", "/users/@me/settings-proto/2")
        if not isinstance(confirmed, dict) or confirmed.get("settings") != data["settings"]:
            raise DiscordError("Discord did not confirm the saved frecency block; inspect your settings and the saved rollback")
        log("Favourite GIF settings restored and verified")
