from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
from pathlib import Path
import threading
import time
from unittest.mock import patch

from discord_backup.api import DiscordClient, DiscordError, PooledTransport, RateLimiter
from discord_backup.backup import BackupInterrupted, Collector
from discord_backup.cli import execute, parser
from discord_backup.storage import read_backup
from test_backup import FakeHTTP, PASSWORD, TOKEN, TemporaryTest, legacy


class ParallelTests(TemporaryTest):
    def test_http_sessions_are_separate_for_each_worker(self):
        transport = PooledTransport()
        barrier = threading.Barrier(3)

        def session_id():
            session = transport.session
            barrier.wait(timeout=1)
            return id(session)

        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                ids = list(pool.map(lambda value: session_id(), range(3)))
            self.assertEqual(len(set(ids)), 3)
        finally:
            transport.close()

    def test_independent_major_resources_overlap(self):
        limiter = RateLimiter()
        release, all_started = threading.Event(), threading.Event()
        lock = threading.Lock()
        active, peak = 0, 0

        def work(uid):
            nonlocal active, peak
            with limiter.slot("GET", f"/guilds/{uid}/channels"):
                with lock:
                    active += 1
                    peak = max(peak, active)
                    if active == 3:
                        all_started.set()
                release.wait(1)
                with lock:
                    active -= 1

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(work, uid) for uid in (1, 2, 3)]
            try:
                self.assertTrue(all_started.wait(1))
            finally:
                release.set()
            for future in futures:
                future.result(timeout=1)
        self.assertEqual(peak, 3)

    def test_unknown_shared_bucket_does_not_start_duplicate_inflight_requests(self):
        limiter = RateLimiter()
        first_started, second_started, release = threading.Event(), threading.Event(), threading.Event()

        def first():
            with limiter.slot("GET", "/guilds/1/channels"):
                first_started.set()
                release.wait(1)

        def second():
            with limiter.slot("GET", "/guilds/1/channels"):
                second_started.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            self.assertTrue(first_started.wait(1))
            two = pool.submit(second)
            try:
                self.assertFalse(second_started.wait(0.05))
            finally:
                release.set()
            one.result(timeout=1)
            two.result(timeout=1)
        self.assertTrue(second_started.is_set())

    def test_known_budget_is_reserved_before_requests_start(self):
        limiter = RateLimiter()
        limiter.observe("GET", "/guilds/1/channels", 200, {
            "x-ratelimit-bucket": "shared", "x-ratelimit-remaining": "2", "x-ratelimit-reset-after": "10",
        }, {})
        release, two_started, cancelled = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        started = 0

        def work():
            nonlocal started
            try:
                with limiter.slot("GET", "/guilds/1/channels", cancelled):
                    with lock:
                        started += 1
                        if started == 2:
                            two_started.set()
                    release.wait(1)
            except DiscordError:
                pass

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(work) for _ in range(3)]
            try:
                self.assertTrue(two_started.wait(1))
                time.sleep(0.03)
                self.assertEqual(started, 2)
            finally:
                cancelled.set()
                release.set()
            for future in futures:
                future.result(timeout=1)

    def test_global_wait_can_be_cancelled_promptly(self):
        limiter, cancelled = RateLimiter(), threading.Event()
        limiter.observe("GET", "/users/@me", 429, {}, {"retry_after": 5, "global": True})
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(limiter.before, "GET", "/users/@me/relationships", cancelled=cancelled)
            time.sleep(0.03)
            cancelled.set()
            with self.assertRaises(DiscordError):
                future.result(timeout=0.5)

    def test_global_429_blocks_other_worker_endpoints(self):
        limiter = RateLimiter()
        limiter.observe("POST", "/channels/1/invites", 429, {}, {"retry_after": 0.1, "global": True})
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(limiter.before, "GET", "/users/@me/relationships")
            time.sleep(0.03)
            self.assertFalse(future.done())
            future.result(timeout=1)
        self.assertGreaterEqual(time.monotonic() - started, 0.34)

    def test_auth_failure_stops_other_invite_workers_and_saves_partial_data(self):
        routes = {("GET", "/users/@me/guilds?limit=200&after=0"):
                  [{"id": str(uid), "name": f"Guild {uid}", "features": []} for uid in (10, 11, 12)],
                  ("POST", "/channels/20/invites"): (401, {}, {})}
        for uid in (11, 12):
            def delayed(request, channel=uid + 10):
                time.sleep(0.1)
                return [{"id": str(channel), "type": 0, "name": "general"}]
            routes[("GET", f"/guilds/{uid}/channels")] = delayed
            routes[("POST", f"/channels/{uid + 10}/invites")] = {"code": "should-not-be-requested"}
        http = FakeHTTP(routes)
        client = DiscordClient(TOKEN, transport=http)
        with self.assertRaises(BackupInterrupted):
            Collector(client, self.directory, passphrase=PASSWORD, log=lambda value: None).run()
        self.assertEqual(len(http.writes()), 1)
        data = read_backup(next(self.directory.glob("*.bkup")), passphrase=PASSWORD)
        self.assertEqual(len(data["guilds"]), 3)
        self.assertEqual(data["status"], "partial")

    def test_performance_report_masks_account_and_resource_ids(self):
        http = FakeHTTP()
        client = http.client()
        client.request("GET", "/guilds/10/channels")
        client.request("POST", "/channels/20/invites", {})
        endpoints = client.performance()["endpoints"]
        self.assertIn("GET /guilds/{guild_id}/channels", endpoints)
        self.assertIn("POST /channels/{channel_id}/invites", endpoints)
        self.assertNotIn("GET /guilds/10/channels", endpoints)

    def test_speed_test_removes_temporary_files_on_success_and_failure(self):
        for failing in (False, True):
            created = []

            class TestCollector:
                def __init__(self, client, directory, **options):
                    self.directory = Path(directory)
                    created.append(self.directory)
                    (self.directory / "temporary.bkup").write_bytes(b"synthetic encrypted test data")

                def run(self):
                    if failing:
                        raise DiscordError("Synthetic network failure")
                    return self.directory / "temporary.bkup", {**legacy(), "status": "complete", "performance": {"requests": 0}}

            args = parser().parse_args(["speed-test", "--manual"])
            with patch("discord_backup.cli.Collector", TestCollector), patch("discord_backup.cli.client_for", return_value=FakeHTTP().client()), redirect_stdout(io.StringIO()):
                if failing:
                    with self.assertRaises(DiscordError):
                        execute(args)
                else:
                    self.assertEqual(execute(args), 0)
            self.assertEqual(len(created), 1)
            self.assertFalse(created[0].exists())
