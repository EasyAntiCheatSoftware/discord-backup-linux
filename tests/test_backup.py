import base64
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from discord_backup.api import DiscordClient, DiscordError
from discord_backup.backup import BackupInterrupted, Collector
from discord_backup.restore import export_recovery, folder_plan, restore_folders, restore_gifs
from discord_backup.schedule import install_schedule
from discord_backup.storage import read_backup, read_token, write_backup

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
TOKEN = "synthetic.test.token"
PASSWORD = "synthetic-backup-passphrase"


class FakeClock:
    def __init__(self, sleeps=None):
        self.now = 0.0
        self.sleeps = [] if sleeps is None else sleeps

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def folder(uid, ids, name="Saved"):
    return {"id": uid, "name": name, "color": 0x123456, "guild_ids": ids}


def legacy():
    return {
        "version": "v1.2.10", "id": "1", "name": "example", "discriminator": "1234",
        "bio": "Saved bio", "avatar-bytes": base64.b64encode(PNG).decode(), "banner-bytes": "",
        "friends": ["2"], "blocked": ["3"], "incoming": ["4"], "outgoing": ["5"],
        "guilds": [{"id": "10", "name": "Server", "invite-code": "abc-def"}],
        "group-chats": [{"id": "30", "name": "Group", "invite-code": "Unable to create."}],
        "dm-history": [{"user_id": "2", "user": "friend#1234", "last_message_id": None}],
        "guild_folders": [folder("100", ["10"])], "settings": "CAE=",
    }


class FakeHTTP:
    def __init__(self, routes=None):
        self.routes = {
            ("GET", "/users/@me"): {"id": "1", "username": "example", "discriminator": "0", "bio": "Bio", "avatar": None, "banner": None},
            ("GET", "/users/@me/relationships"): [{"id": "2", "type": 1, "user": {"id": "2", "username": "friend", "discriminator": "0"}}],
            ("GET", "/users/@me/settings"): {"guild_folders": [folder("100", ["10"])]},
            ("GET", "/users/@me/settings-proto/2"): {"settings": "CAE="},
            ("GET", "/users/@me/guilds?limit=200&after=0"): [{"id": "10", "name": "Server", "features": []}],
            ("GET", "/guilds/10/channels"): [{"id": "20", "type": 0, "name": "general"}],
            ("POST", "/channels/20/invites"): {"code": "server-invite"},
            ("POST", "/channels/30/invites"): {"code": "group-invite"},
            ("GET", "/users/@me/channels"): [
                {"id": "31", "type": 1, "last_message_id": None, "recipients": [{"id": "2", "username": "friend", "discriminator": "0"}]},
                {"id": "32", "type": 1, "last_message_id": "99", "recipients": [{"id": "3", "username": "other", "discriminator": "0"}]},
                {"id": "30", "type": 3, "name": None, "recipients": [{"id": "4", "username": "groupmember", "discriminator": "0"}]},
                {"id": "33", "type": 1, "last_message_id": None, "recipients": []},
            ],
            ("PATCH", "/users/@me/settings"): {},
            ("PATCH", "/users/@me/settings-proto/2"): {},
        }
        self.routes.update(routes or {})
        self.calls = []

    def __call__(self, request):
        parts = urlsplit(request.full_url)
        route = parts.path.removeprefix("/api/v9") + ("?" + parts.query if parts.query else "")
        self.calls.append(request)
        key = (request.get_method(), route)
        if key not in self.routes:
            raise AssertionError(f"Unexpected test request: {key}")
        value = self.routes[key]
        if callable(value):
            value = value(request)
        status, headers, data = value if isinstance(value, tuple) else (200, {}, value)
        if request.get_method() == "PATCH" and 200 <= status < 300:
            self.routes[("GET", route)] = json.loads(request.data)
        return status, headers, data if isinstance(data, bytes) else json.dumps(data).encode()

    def client(self, sleeps=None):
        clock = FakeClock(sleeps)
        return DiscordClient(TOKEN, transport=self, sleep=clock.sleep, clock=clock)

    def writes(self):
        return [request for request in self.calls if request.get_method() != "GET"]


class TemporaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()


class StorageTests(TemporaryTest):
    def test_legacy_backup_loads_unchanged(self):
        path = self.directory / "legacy.bkup"
        path.write_text(json.dumps(legacy()))
        self.assertEqual(read_backup(path), legacy())

    def test_rejects_unrelated_json_and_unknown_schema(self):
        for value in ([], {"id": "1"}, {**legacy(), "schema_version": 2}, {**legacy(), "friends": [{}]}, {**legacy(), "guild_folders": [folder("1", ["bad"])]}):
            path = self.directory / "bad.bkup"
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                read_backup(path)

    def test_private_atomic_write_on_permissive_umask(self):
        previous = os.umask(0)
        try:
            path = self.directory / "backups/account.bkup"
            write_backup(path, legacy(), passphrase=PASSWORD)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            path.chmod(0o644)
            write_backup(path, legacy(), passphrase=PASSWORD)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        finally:
            os.umask(previous)

    def test_token_file_permissions_and_symlinks(self):
        path = self.directory / "token"
        path.write_text(TOKEN)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            read_token(path)
        path.chmod(0o600)
        self.assertEqual(read_token(path), TOKEN)
        link = self.directory / "link"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            read_token(link)

    def test_token_fifo_is_rejected_without_blocking(self):
        path = self.directory / "fifo"
        os.mkfifo(path, 0o600)
        with self.assertRaises(ValueError):
            read_token(path)


class ClientTests(unittest.TestCase):
    def test_fractional_rate_limit_is_respected(self):
        responses = iter([(429, {}, {"retry_after": 0.125}), (200, {}, {"id": "1"})])
        http = FakeHTTP({("GET", "/users/@me"): lambda request: next(responses)})
        sleeps = []
        self.assertEqual(http.client(sleeps).request("GET", "/users/@me"), {"id": "1"})
        self.assertEqual(sleeps, [0.375])

    def test_header_rate_limit_and_success_cooldown_are_respected(self):
        responses = iter([(429, {"retry-after": "0.5"}, b"not JSON"),
                          (200, {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "0.25"}, {}),
                          (200, {}, {})])
        http = FakeHTTP({("GET", "/users/@me"): lambda request: next(responses)})
        sleeps = []
        client = http.client(sleeps)
        client.request("GET", "/users/@me")
        client.request("GET", "/users/@me")
        self.assertEqual(sleeps, [0.75, 0.5])

    def test_persistent_and_excessive_rate_limits_stop(self):
        for delay, expected_calls in ((0, 5), (121, 1), (float("nan"), 1)):
            http = FakeHTTP({("GET", "/users/@me"): (429, {}, {"retry_after": delay})})
            with self.assertRaises(DiscordError) as result:
                http.client().request("GET", "/users/@me")
            self.assertTrue(result.exception.fatal)
            self.assertEqual(len(http.calls), expected_calls)

    def test_auth_and_captcha_fail_without_retry(self):
        for response in ((401, {}, {"message": "no"}), (400, {}, {"captcha_key": ["required"]})):
            http = FakeHTTP({("GET", "/users/@me"): response})
            with self.assertRaises(DiscordError) as result:
                http.client().request("GET", "/users/@me")
            self.assertTrue(result.exception.fatal)
            self.assertEqual(len(http.calls), 1)
            self.assertNotIn(TOKEN, str(result.exception))

    def test_post_is_not_repeated_after_server_error(self):
        http = FakeHTTP({("POST", "/channels/20/invites"): (503, {}, {})})
        with self.assertRaises(DiscordError):
            http.client().request("POST", "/channels/20/invites", {})
        self.assertEqual(len(http.calls), 1)

    def test_get_retries_server_errors_with_bound(self):
        http = FakeHTTP({("GET", "/users/@me"): (503, {}, {})})
        sleeps = []
        with self.assertRaises(DiscordError):
            http.client(sleeps).request("GET", "/users/@me")
        self.assertEqual(sleeps, [1, 2, 4, 8])
        self.assertEqual(len(http.calls), 5)

    def test_no_auth_on_cdn_and_redirects_disabled(self):
        http = FakeHTTP({("GET", "/avatars/1/a.png"): (200, {"content-type": "image/png"}, PNG)})
        client = http.client()
        self.assertEqual(client.asset("https://cdn.discordapp.com/avatars/1/a.png"), PNG)
        self.assertIsNone(http.calls[-1].get_header("Authorization"))
        with self.assertRaises(ValueError):
            client.asset("https://other.example/image.png")

    def test_pagination_includes_more_than_200_servers(self):
        page = [{"id": str(value)} for value in range(1, 201)]
        http = FakeHTTP({("GET", "/users/@me/guilds?limit=200&after=0"): page,
                         ("GET", "/users/@me/guilds?limit=200&after=200"): [{"id": "201"}]})
        self.assertEqual(len(http.client().guilds()), 201)

    def test_stuck_pagination_stops(self):
        page = [{"id": str(value)} for value in range(1, 201)]
        http = FakeHTTP({("GET", "/users/@me/guilds?limit=200&after=0"): page,
                         ("GET", "/users/@me/guilds?limit=200&after=200"): page})
        with self.assertRaises(DiscordError):
            http.client().guilds()


class CollectionTests(TemporaryTest):
    def collect(self, http, **kwargs):
        return Collector(http.client(), self.directory / "backups", passphrase=PASSWORD, log=lambda message: None, **kwargs).run()

    def test_complete_backup_contacts_groups_and_invites(self):
        http = FakeHTTP()
        path, data = self.collect(http)
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["friends"], ["2"])
        self.assertEqual([item["user_id"] for item in data["dm-history"]], ["3", "2"])
        self.assertEqual(data["guilds"][0]["invite-code"], "server-invite")
        self.assertEqual(data["group-chats"][0]["invite-code"], "group-invite")
        self.assertEqual(data["users"]["4"]["username"], "groupmember")
        self.assertNotIn(TOKEN.encode(), path.read_bytes())
        self.assertEqual(read_backup(path, passphrase=PASSWORD), data)
        self.assertNotIn("\\", path.name)

    def test_read_only_backup_never_writes_to_discord(self):
        http = FakeHTTP()
        _, data = self.collect(http, create_invites=False)
        self.assertEqual(data["status"], "complete")
        self.assertEqual(http.writes(), [])
        self.assertIsNone(data["guilds"][0]["invite-code"])
        self.assertEqual(len(data["group-chats"]), 1)

    def test_missing_optional_endpoint_makes_partial_backup(self):
        http = FakeHTTP({("GET", "/users/@me/settings"): (404, {}, {})})
        path, data = self.collect(http)
        self.assertEqual(data["status"], "partial")
        self.assertIsNone(data["guild_folders"])
        self.assertEqual(data["sections"]["folders"], "partial")
        self.assertEqual(read_backup(path, passphrase=PASSWORD)["friends"], ["2"])

    def test_expired_credentials_preserve_completed_sections(self):
        http = FakeHTTP({("GET", "/users/@me/channels"): (401, {}, {})})
        with self.assertRaises(BackupInterrupted):
            self.collect(http)
        path = next((self.directory / "backups").glob("*.bkup"))
        data = read_backup(path, passphrase=PASSWORD)
        self.assertEqual(data["friends"], ["2"])
        self.assertEqual(len(data["guilds"]), 1)
        self.assertTrue(data["interrupted"])
        self.assertEqual(data["status"], "partial")

    def test_invite_failure_preserves_server_membership(self):
        http = FakeHTTP({("POST", "/channels/20/invites"): (403, {}, {})})
        _, data = self.collect(http)
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["guilds"][0]["id"], "10")
        self.assertIsNone(data["guilds"][0]["invite-code"])

    def test_collision_resistant_filenames(self):
        first, _ = self.collect(FakeHTTP())
        second, _ = self.collect(FakeHTTP())
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())

    def test_interrupted_invite_preserves_all_server_memberships(self):
        http = FakeHTTP({("POST", "/channels/20/invites"): (400, {}, {"captcha_key": ["required"]})})
        with self.assertRaises(BackupInterrupted):
            self.collect(http)
        path = next((self.directory / "backups").glob("*.bkup"))
        data = read_backup(path, passphrase=PASSWORD)
        self.assertEqual(data["guilds"][0]["id"], "10")
        self.assertEqual(data["status"], "partial")
        self.assertEqual(len(data["dm-history"]), 2)
        self.assertEqual(len(data["group-chats"]), 1)


class RecoveryTests(TemporaryTest):
    def test_export_legacy_images_and_escape_untrusted_fields(self):
        data = legacy()
        data["name"] = '<script>alert("name")</script>'
        data["bio"] = "<img src=x onerror=alert(1)>"
        data["guilds"][0]["invite-code"] = 'javascript:alert("oops")'
        data["group-chats"][0]["name"] = "<script>bad()</script>"
        page, notices = export_recovery(data, self.directory / "export")
        content = page.read_text()
        self.assertEqual(notices, [])
        self.assertNotIn("<script>", content)
        self.assertNotIn("javascript:", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("https://discord.com/users/2", content)
        self.assertEqual((page.parent / "avatar.png").read_bytes(), PNG)
        self.assertEqual((page.parent / "bio.txt").read_text(), data["bio"])
        self.assertEqual(stat.S_IMODE(page.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            export_recovery(data, page.parent)

    def test_invalid_image_does_not_prevent_recovery_page(self):
        data = {**legacy(), "avatar-bytes": base64.b64encode(b"<html>upstream error page</html>").decode()}
        page, notices = export_recovery(data, self.directory / "invalid-image")
        self.assertTrue(page.exists())
        self.assertEqual(len(notices), 1)

    def test_folder_plan_preserves_input_and_new_servers(self):
        saved = [folder("100", ["10", "11", "12"])]
        current = [folder("100", ["10", "13"]), folder("200", ["14"])]
        before = copy.deepcopy((saved, current))
        plan = folder_plan(saved, current, ["10", "12", "13", "14", "15"])
        self.assertEqual(plan["guild_folders"][0]["guild_ids"], ["10", "12", "13"])
        self.assertEqual([uid for item in plan["guild_folders"] for uid in item["guild_ids"]], ["10", "12", "13", "14", "15"])
        self.assertEqual((saved, current), before)

    def test_preview_sends_no_patch_and_apply_saves_rollback(self):
        http = FakeHTTP()
        restore_folders(http.client(), legacy(), log=lambda message: None)
        self.assertEqual(http.writes(), [])
        restore_folders(http.client(), legacy(), apply=True, directory=self.directory, passphrase=PASSWORD, log=lambda message: None)
        self.assertEqual(len(http.writes()), 1)
        rollback = read_backup(next(self.directory.glob("rollback-*.bkup")), passphrase=PASSWORD)
        self.assertEqual(rollback["guild_folders"], [folder("100", ["10"])])

    def test_cross_account_and_missing_current_layout_stop_writes(self):
        for routes in ({("GET", "/users/@me"): {"id": "2", "username": "other"}}, {("GET", "/users/@me/settings"): {}}):
            http = FakeHTTP(routes)
            with self.assertRaises((ValueError, DiscordError)):
                restore_folders(http.client(), legacy(), apply=True, directory=self.directory, log=lambda message: None)
            self.assertEqual(http.writes(), [])

    def test_gif_preview_and_rollback(self):
        http = FakeHTTP({("GET", "/users/@me/settings-proto/2"): {"settings": "CAI="}})
        restore_gifs(http.client(), legacy(), log=lambda message: None)
        self.assertEqual(http.writes(), [])
        restore_gifs(http.client(), legacy(), apply=True, directory=self.directory, passphrase=PASSWORD, log=lambda message: None)
        self.assertEqual(len(http.writes()), 1)
        self.assertEqual(read_backup(next(self.directory.glob("rollback-*.bkup")), passphrase=PASSWORD)["settings"], "CAI=")

    def test_cli_offline_inspect_and_export_from_other_directory(self):
        path = self.directory / "legacy.bkup"
        path.write_text(json.dumps(legacy()))
        inspected = subprocess.run([sys.executable, ROOT / "main.py", "inspect", path], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(json.loads(inspected.stdout)["friends"], 1)
        exported = subprocess.run([ROOT / "run.sh", "export", path, "--output", self.directory / "recovery"], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertTrue((self.directory / "recovery/index.html").exists())

    def test_schedule_escapes_paths_and_defaults_to_read_only(self):
        config = self.directory / "config"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            units = install_schedule(self.directory / 'token % " $ path', self.directory / "backup space")
        text = (units / "discord-backup.service").read_text()
        self.assertIn("--no-invites", text)
        self.assertIn("%%", text)
        self.assertIn("$$", text)
        self.assertIn('\\"', text)
        self.assertIn("Persistent=true", (units / "discord-backup.timer").read_text())


if __name__ == "__main__":
    unittest.main()
