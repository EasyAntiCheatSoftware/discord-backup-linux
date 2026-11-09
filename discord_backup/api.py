# SPDX-License-Identifier: AGPL-3.0-only
"""Small synchronous HTTP client with bounded retries and no credential redirects."""

import json
import math
from collections import deque
from contextlib import contextmanager
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request

import requests
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase

from . import __version__
from .storage import snowflake, validate_token

API_ROOT = "https://discord.com/api/v9"
MAX_RESPONSE = 16 * 1024 * 1024


class DiscordError(Exception):
    def __init__(self, message, status=0, fatal=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


class ExplicitAuth(AuthBase):
    def __call__(self, request):
        # Keep environment proxy/CA support without allowing .netrc to replace a token.
        return request


class PooledTransport:
    """Reuse TLS connections, with explicit request credentials and no redirect/retry."""

    def __init__(self):
        self._local = threading.local()
        self._sessions = []
        self._lock = threading.Lock()

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.auth = ExplicitAuth()
            session.mount("https://", HTTPAdapter(max_retries=0, pool_connections=2, pool_maxsize=2))
            self._local.session = session
            with self._lock:
                self._sessions.append(session)
        return self._local.session

    def __call__(self, request):
        try:
            with self.session.request(request.get_method(), request.full_url, data=request.data,
                                      headers=dict(request.header_items()), allow_redirects=False,
                                      timeout=(10, 30), stream=True) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise DiscordError("Discord response exceeded the size limit")
                    chunks.append(chunk)
                return response.status_code, {key.lower(): value for key, value in response.headers.items()}, b"".join(chunks)
        except requests.RequestException:
            # Request exceptions may include headers or URLs. Keep them out of logs.
            raise DiscordError("Network request failed; check your connection and try again") from None

    def close(self):
        with self._lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()


def delay_seconds(value, *, maximum=120):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        raise DiscordError("Discord supplied an invalid retry delay", fatal=True) from None
    if not math.isfinite(seconds) or seconds < 0 or (maximum is not None and seconds > maximum):
        raise DiscordError("Discord requested a long or invalid cooldown; try again later", 429, True)
    return seconds


class DiscordClient:
    def __init__(self, token, *, transport=None, sleep=time.sleep, clock=time.monotonic,
                 log=lambda message: None, limiter=None):
        self._token = validate_token(token)
        self.transport = PooledTransport() if transport is None else transport
        self._owns_transport = transport is None
        self.sleep = sleep
        self.log = log
        self.limiter = limiter or RateLimiter(sleep=sleep, clock=clock, log=log)
        self.clock = clock
        self._stats_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._cancel_error = None
        self.requests_made = 0
        self.http_seconds = 0
        self.endpoint_stats = {}

    def cancel(self, error=None):
        with self._stats_lock:
            if error is not None and self._cancel_error is None:
                self._cancel_error = error
        self._cancelled.set()

    def check_cancelled(self):
        if self._cancelled.is_set():
            raise self._cancel_error or DiscordError("Backup cancelled", fatal=True)

    def performance(self):
        with self._stats_lock:
            return {"requests": self.requests_made, "http_worker_seconds": round(self.http_seconds, 3),
                    "endpoints": {key: dict(value) for key, value in self.endpoint_stats.items()}}

    def close(self):
        if self._owns_transport:
            self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()

    def request(self, method, route, payload=None):
        try:
            return self._request(method, route, payload)
        except DiscordError as error:
            if error.fatal:
                self.cancel(error)
                raise self._cancel_error from None
            raise

    def _request(self, method, route, payload=None):
        if not route.startswith("/") or route.startswith("//") or "#" in route or "\\" in route:
            raise ValueError("Expected a relative Discord API route")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        for attempt in range(5):
            self.check_cancelled()
            request = Request(API_ROOT + route, data=body, method=method, headers={
                "Authorization": self._token,
                "User-Agent": f"DiscordBackupLinux/{__version__} (+https://github.com/EasyAntiCheatSoftware/discord-backup-linux)",
                "Accept": "application/json", "Content-Type": "application/json",
            })
            with self.limiter.slot(method, route, self._cancelled):
                self.check_cancelled()
                started = self.clock()
                status = 0
                try:
                    status, headers, raw = self.transport(request)
                finally:
                    elapsed = max(0, self.clock() - started)
                    endpoint = method + " " + self.limiter.key(method, route)[0][1]
                    with self._stats_lock:
                        self.requests_made += 1
                        self.http_seconds += elapsed
                        stats = self.endpoint_stats.setdefault(endpoint, {"calls": 0, "seconds": 0, "errors": 0})
                        stats["calls"] += 1
                        stats["seconds"] = round(stats["seconds"] + elapsed, 3)
                        stats["errors"] += int(status == 0 or status >= 400)
                try:
                    data = json.loads(raw) if raw else None
                except (ValueError, UnicodeError, RecursionError):
                    data = None
                self.limiter.observe(method, route, status, headers, data)
            if isinstance(data, dict) and ("captcha_key" in data or "captcha_sitekey" in data):
                raise DiscordError("Discord requires a CAPTCHA; stop and use the official client", status, True)
            if status == 401:
                raise DiscordError("Discord rejected the account token (HTTP 401)", 401, True)
            if status == 429:
                if attempt == 4:
                    raise DiscordError("Discord rate limit persisted; try again later", 429, True)
                continue
            # Repeating a POST after a 5xx can create duplicate invites.
            if status >= 500 and method == "GET" and attempt < 4:
                self.sleep(2**attempt)
                continue
            if not 200 <= status < 300:
                raise DiscordError(f"Discord returned HTTP {status}", status)
            if raw and data is None:
                raise DiscordError("Discord returned an unexpected non-JSON response")
            return data
        raise AssertionError("Unreachable retry state")

    def guilds(self):
        result, after, seen = [], "0", set()
        while True:
            page = self.request("GET", f"/users/@me/guilds?limit=200&after={after}")
            if not isinstance(page, list) or any(not isinstance(item, dict) or not snowflake(item.get("id")) for item in page):
                raise DiscordError("Unexpected server list response")
            if not page:
                return result
            fresh = [item for item in page if str(item["id"]) not in seen]
            if not fresh:
                raise DiscordError("Server pagination did not advance")
            result.extend(fresh)
            seen.update(str(item["id"]) for item in fresh)
            if len(page) < 200:
                return result
            cursor = str(max(int(item["id"]) for item in page))
            if int(cursor) <= int(after):
                raise DiscordError("Server pagination did not advance")
            after = cursor

    def asset(self, url):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "cdn.discordapp.com":
            raise ValueError("Only Discord CDN images are allowed")
        request = Request(url, headers={"User-Agent": f"DiscordBackupLinux/{__version__}"})
        status, headers, body = self.transport(request)
        if status != 200:
            raise DiscordError(f"Discord CDN returned HTTP {status}", status)
        if not headers.get("content-type", "").startswith("image/"):
            raise DiscordError("Discord CDN did not return an image")
        return body


class RateLimiter:
    """Coordinate workers with server budgets, global waits, and a burst guard."""

    def __init__(self, *, sleep=time.sleep, clock=time.monotonic, log=lambda message: None,
                 min_interval=0, burst_limit=25):
        if not math.isfinite(min_interval) or min_interval < 0 or type(burst_limit) is not int or burst_limit < 1:
            raise ValueError("Invalid request pacing configuration")
        self.sleep, self.clock, self.log = sleep, clock, log
        self.min_interval = min_interval
        self.burst_limit = burst_limit
        self._starts = deque()
        self._condition = threading.Condition(threading.RLock())
        self._active = {}
        self._budgets = {}
        self._waiting = 0
        self._wait_started = 0
        self.next_request = 0
        self.global_until = 0
        self.routes, self.route_until, self.bucket_until = {}, {}, {}
        self.template_until, self.template_failures = {}, {}
        self.serial_templates = set()
        self.cooldown_seconds = 0

    def invite_forecast(self):
        """Read-only hints for the progress estimate; never reserve or send a request."""
        key = ("POST", "/channels/{channel_id}/invites")
        with self._condition:
            return {
                "wait_seconds": max(0, max(self.global_until, self.template_until.get(key, 0)) - self.clock()),
                "serial": key in self.serial_templates,
            }

    @staticmethod
    def key(method, route):
        path = urlsplit(route).path
        parts = path.strip("/").split("/")
        major = tuple(parts[:3] if parts[0] == "webhooks" else parts[:2]) if len(parts) > 1 and parts[0] in ("channels", "guilds", "webhooks") else ()
        normalized = []
        for index, part in enumerate(parts):
            if index == 1 and parts[0] in ("guilds", "channels", "webhooks"):
                normalized.append("{" + parts[0][:-1] + "_id}")
            elif (index == 1 and parts[0] == "invites") or (index == 2 and parts[0] == "webhooks"):
                normalized.append("{code}")
            elif part.isdigit() and parts[index - 1] != "settings-proto":
                normalized.append("{id}")
            else:
                normalized.append(part)
        return (method, "/" + "/".join(normalized)), major

    def _bucket(self, scope):
        key, major = scope
        return self.routes.get(key, key), major

    def _active_in(self, bucket):
        return sum(count for scope, count in self._active.items() if self._bucket(scope) == bucket)

    @contextmanager
    def slot(self, method, route, cancelled=None):
        scope = self.before(method, route, reserve=True, cancelled=cancelled)
        try:
            yield
        finally:
            with self._condition:
                self._active[scope] -= 1
                if not self._active[scope]:
                    del self._active[scope]
                self._condition.notify_all()

    def before(self, method, route, *, reserve=False, cancelled=None):
        scope = self.key(method, route)
        announced = False
        while True:
            with self._condition:
                if cancelled is not None and cancelled.is_set():
                    raise DiscordError("Backup cancelled", fatal=True)
                now = self.clock()
                bucket = self._bucket(scope)
                budget = self._budgets.get(bucket)
                if budget and now >= budget[1]:
                    self._budgets.pop(bucket, None)
                    budget = None
                while self._starts and now - self._starts[0] >= 1:
                    self._starts.popleft()
                cooldown = max(self.global_until, self.template_until.get(scope[0], 0),
                               self.route_until.get(scope, 0), self.bucket_until.get(bucket, 0))
                guard = self._starts[0] + 1 if len(self._starts) >= self.burst_limit else 0
                if reserve:
                    if scope[0] in self.serial_templates and any(count for active_scope, count in self._active.items() if active_scope[0] == scope[0]):
                        self._condition.wait(timeout=0.05)
                        continue
                    active = self._active_in(bucket)
                    if budget is None and active:
                        self._condition.wait(timeout=0.05)
                        continue
                    if budget and budget[0] <= 0:
                        if active:
                            self._condition.wait(timeout=0.05)
                            continue
                        cooldown = max(cooldown, budget[1])
                wait = max(cooldown, self.next_request, guard) - now
                if cooldown - now > 120.25:
                    raise DiscordError("Discord requested a long cooldown; try again later", 429, True)
                if wait <= 0:
                    self.next_request = now + self.min_interval
                    self._starts.append(now)
                    if reserve:
                        if budget:
                            budget[0] -= 1
                        self._active[scope] = self._active.get(scope, 0) + 1
                    return scope
                server_wait = cooldown > now
                if server_wait:
                    if not announced:
                        self.log(f"Waiting {cooldown - now:.2f}s for Discord's rate-limit window")
                        announced = True
                    if not self._waiting:
                        self._wait_started = now
                    self._waiting += 1
            try:
                # Short waits recheck global limits discovered by another worker.
                if cancelled is not None and self.sleep is time.sleep:
                    cancelled.wait(min(wait, 0.1))
                else:
                    self.sleep(wait)
            finally:
                if server_wait:
                    with self._condition:
                        self._waiting -= 1
                        if not self._waiting:
                            self.cooldown_seconds += max(0, self.clock() - self._wait_started)

    def observe(self, method, route, status, headers, data):
        with self._condition:
            self._observe(method, route, status, headers, data)
            self._condition.notify_all()

    def _observe(self, method, route, status, headers, data):
        scope = self.key(method, route)
        key, major = scope
        if headers.get("x-ratelimit-bucket"):
            self.routes[key] = headers["x-ratelimit-bucket"]
        bucket = self._bucket(scope)
        if "x-ratelimit-remaining" in headers and "x-ratelimit-reset-after" in headers:
            try:
                remaining = max(0, int(headers["x-ratelimit-remaining"]))
            except (ValueError, TypeError):
                raise DiscordError("Discord supplied an invalid request budget", fatal=True) from None
            # A long window with requests remaining is not a request to sleep.
            until = self.clock() + delay_seconds(headers["x-ratelimit-reset-after"], maximum=None) + 0.25
            available = max(0, remaining - max(0, self._active_in(bucket) - 1))
            previous = self._budgets.get(bucket)
            if previous and previous[1] > self.clock():
                available = min(available, previous[0])
            self._budgets[bucket] = [available, until]
        if status == 429:
            values = [headers["retry-after"]] if "retry-after" in headers else []
            if isinstance(data, dict) and "retry_after" in data:
                values.append(data["retry_after"])
            delay = max(delay_seconds(value) for value in (values or [1]))
            until = self.clock() + delay + 0.25
            if key == ("POST", "/channels/{channel_id}/invites"):
                strikes = self.template_failures.get(key, 0) + 1
                self.template_failures[key] = strikes
                if key not in self.serial_templates:
                    self.log("Rate limited during invite creation; switching to one invite request at a time")
                self.serial_templates.add(key)
                backoff = min(16, 2 ** min(strikes - 1, 4))
                self.template_until[key] = max(self.template_until.get(key, 0), self.clock() + max(delay, backoff) + 0.25)
            global_limit = (isinstance(data, dict) and data.get("global") is True) or headers.get("x-ratelimit-global", "").lower() == "true" or headers.get("x-ratelimit-scope") == "global"
            if global_limit:
                self.global_until = max(self.global_until, until)
            else:
                self.route_until[scope] = max(self.route_until.get(scope, 0), until)
                self.bucket_until[bucket] = max(self.bucket_until.get(bucket, 0), until)
            self.log(f"Rate limited ({'global' if global_limit else 'endpoint'}); retrying after the cooldown")
        elif headers.get("x-ratelimit-remaining") == "0":
            delay = delay_seconds(headers.get("x-ratelimit-reset-after", 1))
            until = self.clock() + delay + 0.25
            self.route_until[scope] = max(self.route_until.get(scope, 0), until)
            self.bucket_until[bucket] = max(self.bucket_until.get(bucket, 0), until)
        if 200 <= status < 300:
            self.template_failures.pop(key, None)
