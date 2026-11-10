#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Compare one and three workers using synthetic HTTP latency; never contact Discord."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_backup import FakeHTTP, PASSWORD, TOKEN
from discord_backup.api import DiscordClient
from discord_backup.backup import Collector


def measure(workers, latency):
    routes = {
        ("GET", "/users/@me/guilds?limit=200&after=0"): [
            {"id": str(100 + i), "name": f"Synthetic {i}", "features": []} for i in range(16)],
        ("GET", "/users/@me/channels"): [
            {"id": str(300 + i), "type": 3, "name": f"Group {i}", "recipients": []} for i in range(8)],
    }
    for i in range(16):
        routes[("GET", f"/guilds/{100+i}/channels")] = [{"id": str(200+i), "type": 0, "name": "general"}]
        routes[("POST", f"/channels/{200+i}/invites")] = {"code": f"guild-{i}"}
    for i in range(8):
        routes[("POST", f"/channels/{300+i}/invites")] = {"code": f"group-{i}"}
    backend, lock = FakeHTTP(routes), threading.Lock()
    active = peak = 0

    def transport(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(latency)
            return backend(request)
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory(prefix="discord-network-benchmark-") as directory:
        with DiscordClient(TOKEN, transport=transport) as client:
            started = time.perf_counter()
            _, data = Collector(client, directory, workers=workers, passphrase=PASSWORD, log=lambda value: None, use_history=False).run()
            elapsed = time.perf_counter() - started
    return {"workers": workers, "simulated_latency_ms": round(latency * 1000), "seconds": round(elapsed, 3),
            "api_requests": len(backend.calls), "peak_inflight": peak, "guilds": len(data["guilds"]),
            "groups": len(data["group-chats"]), "status": data["status"],
            "scope": "synthetic transport, real encryption; no live Discord requests"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency", type=float, default=0.12, help="Synthetic request latency in seconds (0 to 1)")
    args = parser.parse_args()
    if not 0 <= args.latency <= 1:
        parser.error("latency must be between 0 and 1 second")
    for workers in (1, 3):
        print(json.dumps(measure(workers, args.latency)), flush=True)


if __name__ == "__main__":
    main()
