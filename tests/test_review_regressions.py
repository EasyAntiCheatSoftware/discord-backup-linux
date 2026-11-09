"""Offline regressions found during the public-release review. Fixtures are synthetic."""

import json
import unittest
from unittest.mock import patch

from discord_backup.api import DiscordError, RateLimiter
from discord_backup.backup import Collector
from discord_backup.restore import folder_plan, restore_folders, restore_gifs
from discord_backup.storage import BackupWriteError, read_backup, snowflake
from test_backup import FakeClock, FakeHTTP, PASSWORD, TemporaryTest, folder, legacy


class RateWindowTests(unittest.TestCase):
    def test_long_window_allows_remaining_budget_then_stops_without_early_retry(self):
        clock = FakeClock()
        limiter = RateLimiter(clock=clock, sleep=clock.sleep)
        limiter.observe("GET", "/users/@me", 200, {
            "x-ratelimit-remaining": "1", "x-ratelimit-reset-after": "3600",
        }, {})
        with limiter.slot("GET", "/users/@me"):
            pass
        with self.assertRaises(DiscordError):
            with limiter.slot("GET", "/users/@me"):
                self.fail("Exhausted budget must not permit a request")
        self.assertEqual(clock.sleeps, [])

    def test_success_with_exhausted_budget_resets_invite_backoff(self):
        clock = FakeClock()
        limiter = RateLimiter(clock=clock, sleep=clock.sleep)
        limiter.observe("POST", "/channels/1/invites", 429, {}, {"retry_after": 0})
        limiter.observe("POST", "/channels/1/invites", 200, {
            "x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "1",
        }, {})
        limiter.observe("POST", "/channels/2/invites", 429, {}, {"retry_after": 0})
        limiter.before("POST", "/channels/3/invites")
        self.assertEqual(clock.sleeps, [1.25])

    def test_invalid_pacing_is_rejected(self):
        for options in ({"burst_limit": 0}, {"burst_limit": True}, {"min_interval": -1}, {"min_interval": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                RateLimiter(**options)


class ImportTests(TemporaryTest):
    def test_deep_json_and_invalid_metadata_are_normal_import_errors(self):
        path = self.directory / "bad.bkup"
        path.write_text("[" * 2000 + "0" + "]" * 2000)
        with self.assertRaises(ValueError):
            read_backup(path)
        for fields in ({"schema_version": True}, {"duration_seconds": "slow"},
                       {"cooldown_seconds": float("nan")}, {"performance": []},
                       {"performance": {"phase_seconds": {"profile": "slow"}}}):
            path.write_text(json.dumps({**legacy(), **fields}))
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                read_backup(path)

    def test_oversized_and_non_ascii_ids_are_rejected_without_conversion_failure(self):
        for value in ("1" * 10000, "١", True, 0, str(2**64)):
            self.assertFalse(snowflake(value))

    def test_checkpoint_failure_cannot_be_swallowed_as_an_optional_format_warning(self):
        collector = Collector(FakeHTTP().client(), self.directory, passphrase=PASSWORD)
        collector.path = self.directory / "checkpoint.bkup"
        collector.data = legacy()
        collector.data["warnings"] = []
        with patch("discord_backup.storage.encrypt", side_effect=ValueError("Encryption failed")):
            with self.assertRaises(BackupWriteError):
                collector.optional("invites", lambda: collector.checkpoint(force=True))
        self.assertEqual(collector.data["warnings"], [])
        self.assertFalse(collector.path.exists())


class RestoreTests(TemporaryTest):
    def test_changed_preview_stops_before_rollback_or_patch(self):
        http = FakeHTTP()
        plan = restore_folders(http.client(), legacy(), log=lambda value: None)
        http.routes[("GET", "/users/@me/guilds?limit=200&after=0")].append({"id": "11", "name": "New"})
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            restore_folders(http.client(), legacy(), apply=True, expected_plan=plan,
                            directory=self.directory, passphrase=PASSWORD, log=lambda value: None)
        self.assertFalse(http.writes())
        self.assertFalse(list(self.directory.glob("*.bkup")))

    def test_unconfirmed_restores_report_failure_and_keep_encrypted_rollback(self):
        for action, route in ((restore_folders, "/users/@me/settings"), (restore_gifs, "/users/@me/settings-proto/2")):
            http = FakeHTTP()
            original = http.__call__

            def transport(request):
                result = original(request)
                if request.get_method() == "PATCH":
                    http.routes[("GET", route)] = {}
                return result

            from discord_backup.api import DiscordClient
            with self.subTest(action=action.__name__), self.assertRaises((ValueError, DiscordError)):
                action(DiscordClient("synthetic.test.token", transport=transport), legacy(), apply=True,
                       directory=self.directory, passphrase=PASSWORD, log=lambda value: None)
        snapshots = list(self.directory.glob("rollback-*.bkup"))
        self.assertEqual(len(snapshots), 2)
        for path in snapshots:
            self.assertEqual(read_backup(path, passphrase=PASSWORD)["id"], "1")

    def test_large_folder_plan_preserves_order_and_shared_folder_members(self):
        saved = [folder(str(10000 + i), [str(i + 1)]) for i in range(2000)]
        current = [folder(str(10000 + i), [str(i + 2001)]) for i in range(2000)]
        plan = folder_plan(saved, current, [str(i + 1) for i in range(4000)])
        self.assertEqual(len(plan["guild_folders"]), 2000)
        self.assertEqual(plan["guild_folders"][0]["guild_ids"], ["1", "2001"])
        self.assertEqual(plan["guild_folders"][-1]["guild_ids"], ["2000", "4000"])


if __name__ == "__main__":
    unittest.main()
