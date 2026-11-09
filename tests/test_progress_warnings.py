"""Per-account estimates and actionable end-of-backup warnings, using synthetic data."""

from contextlib import redirect_stdout, redirect_stderr
import io
import threading
from pathlib import Path
from unittest.mock import patch

from discord_backup.api import DiscordClient, DiscordError, RateLimiter
from discord_backup.backup import BackupInterrupted, Collector
from discord_backup.cli import execute, parser
from discord_backup.progress import EstimateReporter, duration, estimate_remaining
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

    def test_incomplete_memberships_get_a_labeled_available_data_estimate(self):
        http, logs = FakeHTTP({('GET', '/users/@me/channels'): (404, {}, {})}), []
        Collector(http.client(), self.directory, passphrase=PASSWORD, log=logs.append).run()
        estimates = [line for line in logs if 'ETA for example: about' in line and 'available data only' in line]
        self.assertTrue(estimates)
        self.assertTrue(all('group list unavailable' in line for line in estimates))

    def test_initial_eta_precedes_first_request_and_numeric_eta_precedes_groups(self):
        http, logs = FakeHTTP(), []
        initial_channels = http.routes[('GET', '/users/@me/channels')]

        def channels(request):
            self.assertTrue(any('ETA for example: about' in line and 'group count pending' in line for line in logs))
            return initial_channels

        http.routes[('GET', '/users/@me/channels')] = channels
        calls_at_eta = []

        def log(message):
            logs.append(message)
            if message.startswith('ETA for'):
                calls_at_eta.append(len(http.calls))

        Collector(http.client(), self.directory, passphrase=PASSWORD, log=log).run()
        self.assertEqual(calls_at_eta[0], 0)
        progress = [line for line in logs if line.startswith(('Servers [', 'Groups ['))]
        self.assertTrue(progress)
        self.assertTrue(all(' | ETA ' in line for line in progress))

    def test_eta_keeps_printing_while_membership_request_is_blocked(self):
        blocked, heartbeat = threading.Event(), threading.Event()
        http, logs = FakeHTTP(), []
        initial_guilds = http.routes[('GET', '/users/@me/guilds?limit=200&after=0')]

        def guilds(request):
            blocked.set()
            self.assertTrue(heartbeat.wait(2), 'No ETA appeared during a blocked request')
            blocked.clear()
            return initial_guilds

        def log(message):
            logs.append(message)
            if blocked.is_set() and threading.current_thread().name == 'discord-backup-eta':
                heartbeat.set()

        http.routes[('GET', '/users/@me/guilds?limit=200&after=0')] = guilds
        Collector(http.client(), self.directory, passphrase=PASSWORD, log=log, progress_interval=0.02).run()
        self.assertTrue(heartbeat.is_set())
        self.assertFalse(any(thread.name == 'discord-backup-eta' for thread in threading.enumerate()))

    def test_reporter_shows_new_discord_wait_and_stops_after_error(self):
        clock, output, tick = FakeClock(), [], threading.Event()
        hints = {'wait_seconds': 0}

        def log(message):
            output.append(message)
            if 'Discord wait 20s' in message:
                tick.set()

        reporter = EstimateReporter(log, clock=clock, interval=0.02, hints=lambda: dict(hints))
        with self.assertRaisesRegex(ValueError, 'synthetic stop'):
            with reporter:
                reporter.publish('example', remaining=3)
                hints['wait_seconds'] = 20
                self.assertTrue(tick.wait(2))
                self.assertEqual(reporter.short(), 'ETA ~20s left')
                raise ValueError('synthetic stop')
        self.assertFalse(reporter._thread.is_alive())

    def test_overrun_recalculates_instead_of_promising_zero_seconds(self):
        clock, output = FakeClock(), []
        reporter = EstimateReporter(output.append, clock=clock)
        with reporter:
            reporter.publish('example', remaining=1)
            clock.now += 10
            self.assertEqual(reporter.short(), 'ETA recalculating')
            with reporter._lock:
                reporter._emit()
        self.assertIn('taking longer than estimated', output[-1])
        self.assertNotIn('0s remaining', output[-1])


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
