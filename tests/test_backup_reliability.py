"""Rate-notice coalescing, portable partial recovery, and ETA calibration regressions."""

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import subprocess
from unittest.mock import Mock, patch

from discord_backup.api import DiscordClient, DiscordError, RateLimiter
from discord_backup.backup import BackupInterrupted, Collector
from discord_backup.cli import execute, load_backup, parser
from discord_backup.progress import EstimateReporter, estimate_remaining
from discord_backup.restore import export_recovery
from discord_backup.storage import BackupWriteError, read_backup, write_backup
from discord_backup.timing import TimingHistory
from test_backup import FakeClock, FakeHTTP, PASSWORD, TOKEN, TemporaryTest, legacy


class NoticeTests(TemporaryTest):
    def test_parallel_rate_limits_share_one_notice_and_keep_all_deadlines(self):
        clock, logs = FakeClock(), []
        limiter = RateLimiter(clock=clock, sleep=clock.sleep, log=logs.append)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda uid: limiter.observe("GET", f"/guilds/{uid}/channels", 429, {},
                                                      {"retry_after": 2, "global": True}), range(1, 41)))
        self.assertEqual(len(logs), 1)
        self.assertEqual(limiter.global_until, 2.25)
        self.assertEqual(limiter.notice_statistics(), {"rate_limit_responses": 40, "rate_limit_notices_grouped": 39})
        limiter.before("GET", "/users/@me")
        self.assertEqual(clock.sleeps, [2.25])
        self.assertEqual(len(logs), 1)
        clock.now = 31
        limiter.observe("GET", "/users/@me", 429, {}, {"retry_after": 3})
        self.assertEqual(len(logs), 2)
        self.assertIn("40 repeated notices grouped", logs[-1])

    def test_success_header_waits_are_also_grouped_without_losing_wait_totals(self):
        clock, logs = FakeClock(), []
        limiter = RateLimiter(clock=clock, sleep=clock.sleep, log=logs.append)
        for _ in range(8):
            limiter.observe("GET", "/users/@me", 200, {"x-ratelimit-remaining": "0",
                                                     "x-ratelimit-reset-after": "1"}, {})
            limiter.before("GET", "/users/@me")
        self.assertEqual(len(logs), 1)
        self.assertEqual(clock.sleeps, [1.25] * 8)
        self.assertEqual(limiter.cooldown_seconds, 10)
        self.assertEqual(limiter.notice_statistics()["rate_limit_notices_grouped"], 7)

    def test_quiet_notices_do_not_hide_persistent_limit_errors_or_change_backoff(self):
        clock, logs = FakeClock(), []
        http = FakeHTTP({("POST", "/channels/20/invites"): (429, {}, {"retry_after": 0})})
        client = DiscordClient(TOKEN, transport=http, clock=clock, sleep=clock.sleep, log=logs.append)
        with self.assertRaisesRegex(DiscordError, "persisted"):
            client.request("POST", "/channels/20/invites", {})
        self.assertEqual(len(http.calls), 5)
        self.assertEqual(clock.sleeps, [1.25, 2.25, 4.25, 8.25])
        self.assertEqual(len(logs), 1)
        self.assertIn("one at a time", logs[0])
        self.assertEqual(client.performance()["rate_limit_responses"], 5)


class PartialTests(TemporaryTest):
    def interrupted(self):
        http = FakeHTTP({("GET", "/users/@me/channels"): (401, {}, {})})
        with self.assertRaises(BackupInterrupted):
            Collector(http.client(), self.directory, passphrase=PASSWORD, log=lambda message: None).run()
        return next(self.directory.glob("*.bkup"))

    def test_interrupted_file_has_marker_and_keeps_collected_contacts_and_servers(self):
        path = self.interrupted()
        self.assertTrue(path.name.endswith("-partial.bkup"))
        data = read_backup(path, passphrase=PASSWORD)
        self.assertEqual(data["status"], "partial")
        self.assertIn("PARTIAL BACKUP", data["recovery_notice"])
        self.assertEqual(data["friends"], ["2"])
        self.assertEqual(data["guilds"][0]["id"], "10")
        self.assertEqual(data["sections"]["direct-messages"], "interrupted")
        self.assertEqual(data["sections"]["profile"], "pending")
        self.assertFalse(list((self.directory / "data").rglob("*.json")))

    def test_complete_backup_is_promoted_after_its_final_encrypted_checkpoint(self):
        path, data = Collector(FakeHTTP().client(), self.directory, passphrase=PASSWORD,
                               log=lambda message: None).run()
        self.assertFalse(path.name.endswith("-partial.bkup"))
        self.assertEqual(list(self.directory.glob("*.bkup")), [path])
        self.assertEqual(read_backup(path, passphrase=PASSWORD), data)
        self.assertEqual(data["status"], "complete")

    def test_failed_new_checkpoint_preserves_a_readable_partial_file(self):
        calls = 0
        def write(path, data, **options):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise BackupWriteError("Synthetic disk failure")
            return write_backup(path, data, **options)
        with patch("discord_backup.backup.write_backup", side_effect=write):
            with self.assertRaises(BackupWriteError):
                Collector(FakeHTTP().client(), self.directory, passphrase=PASSWORD,
                          log=lambda message: None).run()
        path = next(self.directory.glob("*.bkup"))
        self.assertTrue(path.name.endswith("-partial.bkup"))
        self.assertEqual(read_backup(path, passphrase=PASSWORD)["friends"], ["2"])

    def test_successful_unconsumed_invite_is_salvaged_after_another_worker_fails(self):
        routes = {("GET", "/users/@me/guilds?limit=200&after=0"):
                  [{"id": "10", "name": "First"}, {"id": "11", "name": "Second"}],
                  ("GET", "/guilds/11/channels"): (401, {}, {})}
        class ImmediatePool:
            def __init__(self, **options):
                pass
            def submit(self, action, entry):
                future = Future()
                try:
                    future.set_result(action(entry))
                except Exception as error:
                    future.set_exception(error)
                return future
            def shutdown(self, **options):
                pass
        with patch("discord_backup.backup.ThreadPoolExecutor", ImmediatePool), \
             patch("discord_backup.backup.as_completed", side_effect=lambda futures: reversed(list(futures))):
            with self.assertRaises(BackupInterrupted):
                Collector(FakeHTTP(routes).client(), self.directory, passphrase=PASSWORD,
                          log=lambda message: None).run()
        data = read_backup(next(self.directory.glob("*.bkup")), passphrase=PASSWORD)
        self.assertEqual(data["guilds"][0]["invite-code"], "server-invite")
        self.assertEqual(data["guilds"][1]["id"], "11")

    def test_app_loading_and_html_export_prominently_mark_partial_data(self):
        path = self.interrupted()
        args = parser().parse_args(["recover", str(path)])
        with patch("discord_backup.cli.passphrase_for", return_value=PASSWORD), redirect_stdout(io.StringIO()) as output:
            data, _ = load_backup(args)
        self.assertIn("PARTIAL BACKUP", output.getvalue())
        page, _ = export_recovery(data, self.directory / "recovery")
        text = page.read_text()
        self.assertIn("<h2>PARTIAL BACKUP</h2>", text)
        self.assertIn("direct-messages", text)
        self.assertIn("interrupted", text)
        self.assertIn("Server", text)

    def test_partial_inspect_retains_json_stdout_and_warns_on_stderr(self):
        path = self.interrupted()
        output, notices = io.StringIO(), io.StringIO()
        with patch("discord_backup.cli.passphrase_for", return_value=PASSWORD), redirect_stdout(output), redirect_stderr(notices):
            self.assertEqual(execute(parser().parse_args(["inspect", str(path)])), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "partial")
        self.assertIn("PARTIAL BACKUP", notices.getvalue())

    def test_standalone_gnupg_decryption_keeps_partial_status_and_embedded_filename(self):
        path = self.interrupted()
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, (PASSWORD + "\n").encode())
            os.close(write_fd)
            write_fd = -1
            home = self.directory / "standalone-gpg"; home.mkdir(mode=0o700)
            result = subprocess.run(["gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty",
                                     "--no-autostart", "--no-symkey-cache", "--pinentry-mode", "loopback",
                                     "--passphrase-fd", str(read_fd), "--verbose", "--output", "-", "--decrypt"],
                                    input=path.read_bytes()[8:], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    pass_fds=(read_fd,), check=False, timeout=60)
        finally:
            os.close(read_fd)
            if write_fd != -1:
                os.close(write_fd)
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "partial")
        self.assertIn("PARTIAL BACKUP", data["recovery_notice"])
        self.assertIn(b"backup-partial.json", result.stderr)
        self.assertEqual(data["friends"], ["2"])


class TimingTests(TemporaryTest):
    def history(self, account="123456789012345678", **options):
        return TimingHistory(account, invites=options.get("invites", True), workers=options.get("workers", 3))

    def test_history_is_bounded_private_and_separate_per_account_and_mode(self):
        history = self.history()
        for index in range(8):
            history.record(checkpoint=0.2, phases={"profile": 2, "id": 99}, jobs={"Servers": index + 1})
        self.assertEqual(len(json.loads(history.path.read_text())["samples"]), 5)
        self.assertEqual(history.forecast()["jobs"]["Servers"], 6)
        self.assertEqual(stat.S_IMODE(history.path.stat().st_mode), 0o600)
        self.assertEqual(self.history("987654321098765432").forecast()["samples"], 0)
        self.assertEqual(self.history(invites=False).forecast()["samples"], 0)
        self.assertEqual(self.history(workers=1).forecast()["samples"], 0)
        self.assertNotIn("123456789012345678", history.path.read_text())
        self.assertNotIn("id", json.loads(history.path.read_text())["samples"][0]["phases"])

    def test_corrupt_stale_and_symlinked_timing_files_are_ignored(self):
        history = self.history()
        history.record(checkpoint=0.2, phases={}, jobs={})
        data = json.loads(history.path.read_text())
        data["samples"][0]["recorded"] = 0
        history.path.write_text(json.dumps(data))
        self.assertEqual(history.forecast()["samples"], 0)
        history.path.write_text("{invalid")
        self.assertEqual(history.forecast()["samples"], 0)
        target = self.directory / "unchanged"; target.write_text("synthetic private data")
        history.path.unlink(); history.path.symlink_to(target)
        self.assertEqual(history.forecast()["samples"], 0)
        history.record(checkpoint=0.1, phases={}, jobs={})
        self.assertEqual(target.read_text(), "synthetic private data")

    def test_whole_account_initial_eta_uses_history_without_extra_discord_calls(self):
        history = self.history("1")
        history.record(checkpoint=0.2, phases={"profile": 0.2, "folders": 0.2, "favourite-gifs": 0.2},
                       jobs={"Servers": 10, "Groups": 5})
        http, logs = FakeHTTP(), []
        _, data = Collector(http.client(), self.directory, passphrase=PASSWORD, log=logs.append).run()
        self.assertEqual(len(http.calls), 9)
        self.assertEqual(data["performance"]["eta_history_samples"], 1)
        self.assertGreater(data["performance"]["estimated_total_seconds"], 15)
        self.assertTrue(any("1 recent matching runs" in message for message in logs))

    def test_live_throttled_throughput_revises_remaining_time_upward(self):
        clock = FakeClock()
        collector = Collector(FakeHTTP().client(), self.directory, passphrase=PASSWORD, clock=clock, use_history=False)
        collector.data = {"name": "demo", "sections": {"guilds": "saved", "direct-messages": "saved"},
                          "guilds": [{"id": str(i)} for i in range(1, 11)], "group-chats": []}
        collector.phase_seconds = {"guilds": 0, "relationships": 0, "direct-messages": 0}
        collector._reporter = Mock()
        collector._started = 0
        baseline = collector.estimate(force=True)
        collector._active_phase, collector._phase_started_at = "server-invites", 0
        collector._invite_done["Servers"] = 3
        clock.now = 60
        updated = collector.estimate(force=True)
        self.assertGreater(updated, baseline * 10)
        self.assertGreater(updated, 100)

    def test_periodic_encrypted_checkpoints_are_included_in_long_invite_forecasts(self):
        options = dict(request_seconds=0.1, checkpoint_seconds=1, metadata_requests=0, checkpoints=1,
                       server_jobs=20, server_requests_per_job=2, group_jobs=0, workers=3, server_seconds_per_job=5)
        base = estimate_remaining(**options)
        self.assertEqual(estimate_remaining(**options, checkpoint_interval=5), base + 20)

    def test_new_cooldown_adds_to_pending_work_without_double_counting_existing_wait(self):
        clock, hints, logs = FakeClock(), {"wait_seconds": 0}, []
        reporter = EstimateReporter(logs.append, clock=clock, hints=lambda: dict(hints))
        reporter.publish("demo", remaining=30)
        clock.now = 5; hints["wait_seconds"] = 20
        reporter._emit()
        self.assertIn("45s remaining", logs[-1])
        reporter.publish("demo", remaining=45)
        clock.now = 10; hints["wait_seconds"] = 15
        reporter._emit()
        self.assertIn("40s remaining", logs[-1])

