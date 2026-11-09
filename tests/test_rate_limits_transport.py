import unittest
from unittest.mock import patch
from urllib.request import Request

import requests
from requests.adapters import BaseAdapter

from discord_backup.api import DiscordError, PooledTransport, RateLimiter
from discord_backup.backup import Collector
from test_backup import FakeClock, FakeHTTP, PASSWORD, TemporaryTest, legacy


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.limiter = RateLimiter(sleep=self.clock.sleep, clock=self.clock, min_interval=0)

    def test_exhausted_endpoint_does_not_pause_unrelated_reads(self):
        self.limiter.observe("GET", "/users/@me", 200, {
            "x-ratelimit-bucket": "profile", "x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "2",
        }, {})
        self.limiter.before("GET", "/users/@me/relationships")
        self.assertEqual(self.clock.sleeps, [])
        self.limiter.before("GET", "/users/@me")
        self.assertEqual(self.clock.sleeps, [2.25])

    def test_cpu_work_consumes_the_existing_cooldown(self):
        self.limiter.observe("GET", "/users/@me/guilds?after=0", 200, {
            "x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "10",
        }, {})
        self.clock.now += 7
        self.limiter.before("GET", "/users/@me/guilds?after=200")
        self.assertEqual(self.clock.sleeps, [3.25])

    def test_global_429_stops_all_endpoints(self):
        self.limiter.observe("POST", "/channels/1/invites", 429, {}, {"retry_after": 0.75, "global": True})
        self.limiter.before("GET", "/users/@me/relationships")
        self.assertEqual(self.clock.sleeps, [1.0])

    def test_global_header_is_respected_without_json(self):
        self.limiter.observe("GET", "/users/@me", 429, {"retry-after": "2", "x-ratelimit-global": "true"}, None)
        self.limiter.before("GET", "/users/@me/guilds")
        self.assertEqual(self.clock.sleeps, [2.25])

    def test_shared_buckets_share_limits_within_the_same_major_resource(self):
        self.limiter.observe("GET", "/guilds/1/channels", 200, {"x-ratelimit-bucket": "shared", "x-ratelimit-remaining": "1"}, {})
        self.limiter.observe("GET", "/guilds/2/channels", 200, {"x-ratelimit-bucket": "shared", "x-ratelimit-remaining": "1"}, {})
        self.limiter.observe("GET", "/guilds/1/roles", 200, {
            "x-ratelimit-bucket": "shared", "x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "3",
        }, {})
        self.limiter.before("GET", "/guilds/2/channels")
        self.assertEqual(self.clock.sleeps, [])
        self.limiter.before("GET", "/guilds/1/channels")
        self.assertEqual(self.clock.sleeps, [3.25])

    def test_longer_of_header_and_body_retry_after_is_used(self):
        self.limiter.observe("GET", "/users/@me", 429, {"retry-after": "4"}, {"retry_after": 0.5})
        self.limiter.before("GET", "/users/@me")
        self.assertEqual(self.clock.sleeps, [4.25])

    def test_no_fixed_delay_between_ordinary_requests(self):
        limiter = RateLimiter(clock=self.clock, sleep=self.clock.sleep)
        for index in range(3):
            limiter.before("GET", f"/guilds/{index + 1}/channels")
        self.assertEqual(self.clock.sleeps, [])

    def test_rolling_burst_guard_is_retained(self):
        limiter = RateLimiter(clock=self.clock, sleep=self.clock.sleep, burst_limit=2)
        for index in range(3):
            limiter.before("GET", f"/guilds/{index + 1}/channels")
        self.assertEqual(self.clock.sleeps, [1])

    def test_invite_429_pauses_all_invite_channels_and_adds_backoff(self):
        self.limiter.observe("POST", "/channels/1/invites", 429, {}, {"retry_after": 0.1})
        self.limiter.before("GET", "/users/@me/relationships")
        self.assertEqual(self.clock.sleeps, [])
        self.limiter.before("POST", "/channels/2/invites")
        self.assertEqual(self.clock.sleeps, [1.25])
        self.assertIn(("POST", "/channels/{channel_id}/invites"), self.limiter.serial_templates)
        self.limiter.observe("POST", "/channels/2/invites", 429, {}, {"retry_after": 0.1})
        self.limiter.before("POST", "/channels/3/invites")
        self.assertEqual(self.clock.sleeps, [1.25, 2.25])

    def test_invite_backoff_never_shortens_server_retry_after(self):
        self.limiter.observe("POST", "/channels/1/invites", 429, {}, {"retry_after": 10})
        self.limiter.before("POST", "/channels/2/invites")
        self.assertEqual(self.clock.sleeps, [10.25])


class RecordingAdapter(BaseAdapter):
    def __init__(self, status=200, body=b"{}"):
        self.status, self.body = status, body
        self.sent = []
        self.closed = False

    def send(self, request, **kwargs):
        self.sent.append(request)
        response = requests.Response()
        response.status_code = self.status
        response.headers["Location"] = "https://other.example/redirect-target"
        response._content = self.body
        response._content_consumed = True
        response.request = request
        response.url = request.url
        return response

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def test_redirects_are_not_followed_and_request_auth_does_not_persist(self):
        transport = PooledTransport()
        adapter = RecordingAdapter(status=302)
        transport.session.mount("https://", adapter)
        first = Request("https://discord.com/api/v9/users/@me", headers={"Authorization": "synthetic-token"})
        status, _, _ = transport(first)
        self.assertEqual(status, 302)
        self.assertEqual(len(adapter.sent), 1)
        transport(Request("https://cdn.discordapp.com/avatar.png"))
        self.assertEqual(adapter.sent[0].headers["Authorization"], "synthetic-token")
        self.assertNotIn("Authorization", adapter.sent[1].headers)
        self.assertNotIn("Authorization", transport.session.headers)
        transport.close()
        self.assertTrue(adapter.closed)

    def test_network_exception_does_not_expose_request_credentials(self):
        transport = PooledTransport()
        try:
            with patch.object(transport.session, "request", side_effect=requests.ConnectionError("synthetic-secret-token")):
                with self.assertRaises(DiscordError) as result:
                    transport(Request("https://discord.com/api/v9/users/@me"))
            self.assertNotIn("synthetic-secret-token", str(result.exception))
        finally:
            transport.close()

    def test_response_size_limit_is_retained(self):
        transport = PooledTransport()
        transport.session.mount("https://", RecordingAdapter(body=b"x" * 17))
        try:
            with patch("discord_backup.api.MAX_RESPONSE", 16), self.assertRaises(DiscordError):
                transport(Request("https://discord.com/api/v9/users/@me"))
        finally:
            transport.close()


class CheckpointTests(TemporaryTest):
    def test_batched_progress_and_forced_flush(self):
        clock = FakeClock()
        collector = Collector(FakeHTTP().client(), self.directory, passphrase=PASSWORD, clock=clock)
        collector.path = self.directory / "encrypted.bkup"
        collector.data = legacy()
        with patch("discord_backup.backup.write_backup") as write:
            self.assertTrue(collector.checkpoint())
            collector.data["bio"] = "updated in memory"
            clock.now = 4
            self.assertFalse(collector.checkpoint())
            clock.now = 5
            self.assertTrue(collector.checkpoint())
            clock.now = 5.1
            self.assertTrue(collector.checkpoint(force=True))
        self.assertEqual(write.call_count, 3)
        self.assertTrue(all(call.kwargs["passphrase"] == PASSWORD for call in write.call_args_list))


if __name__ == "__main__":
    unittest.main()
