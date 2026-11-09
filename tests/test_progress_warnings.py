"""Per-account estimates and actionable end-of-backup warnings, using synthetic data."""

from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
from unittest.mock import patch

from discord_backup.api import DiscordClient, DiscordError, RateLimiter
from discord_backup.backup import BackupInterrupted, Collector
from discord_backup.cli import execute, parser
from discord_backup.progress import duration, estimate_remaining
from discord_backup.restore import summary
from discord_backup.terminal import Console
from test_backup import FakeClock, FakeHTTP, PASSWORD, TOKEN, TemporaryTest


class EstimateTests(TemporaryTest):
    def estimate(self, **options):
        defaults = dict(request_seconds=0.4, checkpoint_seconds=0.1, metadata_requests=3,
                        checkpoints=5, server_jobs=12, server_requests_per_job=2,
                        group_jobs=3, workers=3)
        return estimate_remaining(**{**defaults, **options})

    def test_account_workload_latency_and_worker_count_change_the_estimate(self):
        small = self.estimate(server_jobs=1, group_jobs=0)
        self.assertGreater(self.estimate(), small)
        self.assertGreater(self.estimate(request_seconds=1), self.estimate())
        self.assertGreater(self.estimate(workers=1), self.estimate())
        self.assertGreater(self.estimate(serial_invites=True), self.estimate())
        self.assertLess(self.estimate(server_jobs=0, group_jobs=0), self.estimate())

    def test_known_wait_is_added_once_and_metadata_work_consumes_it(self):
        base = self.estimate(metadata_requests=0)
        self.assertAlmostEqual(self.estimate(metadata_requests=0, invite_wait=20) - base, 20)
        self.assertAlmostEqual(self.estimate(metadata_requests=10, invite_wait=20), base + 20)
        self.assertEqual(self.estimate(server_jobs=0, group_jobs=0, invite_wait=120),
                         self.estimate(server_jobs=0, group_jobs=0))

    def test_limiter_forecast_reads_state_without_reserving_requests(self):
        clock = FakeClock()
        limiter = RateLimiter(clock=clock, sleep=clock.sleep)
        limiter.observe('POST', '/channels/1/invites', 429, {}, {'retry_after': 8})
        before = (dict(limiter._active), len(limiter._starts))
        self.assertEqual(limiter.invite_forecast(), {'wait_seconds': 8.25, 'serial': True})
        self.assertEqual((limiter._active, len(limiter._starts)), before)
        clock.now += 3
        self.assertEqual(limiter.invite_forecast()['wait_seconds'], 5.25)

    def test_duration_covers_seconds_minutes_and_hours(self):
        self.assertEqual(duration(0.1), '1s')
        self.assertEqual(duration(65), '1m 05s')
        self.assertEqual(duration(7201), '2h 00m')

    def test_estimate_is_printed_for_this_account_without_extra_requests(self):
        http, logs = FakeHTTP(), []
        _, data = Collector(http.client(), self.directory, passphrase=PASSWORD, log=logs.append).run()
        estimates = [message for message in logs if message.startswith('ETA for example: about')]
        self.assertTrue(estimates)
        self.assertLess(next(i for i, line in enumerate(logs) if line.startswith('ETA for')),
                        logs.index('Saving server-invites…'))
        self.assertNotIn(TOKEN, '\n'.join(logs))
        self.assertEqual(data['status'], 'complete')
        # The estimator adds no calls to the nine-request fixture workload.
        self.assertEqual(len(http.calls), 9)

    def test_incomplete_memberships_do_not_get_a_misleading_numeric_estimate(self):
        http, logs = FakeHTTP({('GET', '/users/@me/channels'): (404, {}, {})}), []
        Collector(http.client(), self.directory, passphrase=PASSWORD, log=logs.append).run()
        self.assertTrue(any('ETA for example: unavailable' in line for line in logs))
        self.assertFalse(any('ETA for example: about' in line for line in logs))


class WarningTests(TemporaryTest):
    def test_final_summary_prints_specific_missing_section_and_recovery_action(self):
        http = FakeHTTP({('GET', '/users/@me/settings'): (404, {}, {}),
                         ('POST', '/channels/30/invites'): (403, {}, {})})
        _, data = Collector(http.client(), self.directory, passphrase=PASSWORD, log=lambda value: None).run()
        output = io.StringIO()
        with redirect_stdout(output):
            Console(mode='never').backup_summary(summary(data))
        text = output.getvalue()
        self.assertIn('Warnings (2)', text)
        self.assertIn('folders (partial)', text)
        self.assertIn('HTTP 404', text)
        self.assertIn('Group invite (groupmember)', text)
        self.assertIn('HTTP 403', text)
        self.assertIn('Membership/contact data already collected is kept', text)
        self.assertIn('Unlock/export', text)
        self.assertIn('new backup', text)
        self.assertNotIn(TOKEN, text)

    def test_interrupted_cli_prints_warning_details_and_retains_encrypted_partial(self):
        http = FakeHTTP({('POST', '/channels/20/invites'): (400, {}, {'captcha_key': ['required']})})
        args = parser().parse_args(['backup', '--manual', '--output', str(self.directory)])
        output = io.StringIO()
        with patch('discord_backup.cli.client_for', return_value=http.client()), \
             patch('discord_backup.cli.passphrase_for', return_value=PASSWORD), redirect_stdout(output):
            with self.assertRaises(BackupInterrupted):
                execute(args)
        text = output.getvalue()
        self.assertIn('PARTIAL', text)
        self.assertIn('CAPTCHA', text)
        self.assertIn('server invites (interrupted)', text)
        self.assertIn('group invites (pending)', text)
        self.assertTrue(list(self.directory.glob('*.bkup')))
