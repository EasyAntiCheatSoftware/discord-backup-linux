#!/usr/bin/env python3
"""Measure encrypted checkpoint work with synthetic data and simulated HTTP only."""

import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_backup import FakeHTTP, PASSWORD
from discord_backup.backup import Collector
from discord_backup.storage import write_backup

routes = {
    ("GET", "/users/@me"): {"id": "1", "username": "synthetic", "bio": "x" * 262144, "avatar": None, "banner": None},
    ("GET", "/users/@me/guilds?limit=200&after=0"): [{"id": str(1000 + i), "name": f"Synthetic {i}", "features": []} for i in range(50)],
    ("GET", "/users/@me/channels"): [{"id": str(3000 + i), "type": 3, "name": f"Group {i}", "recipients": []} for i in range(20)],
}
for index in range(50):
    routes[("GET", f"/guilds/{1000 + index}/channels")] = [{"id": str(2000 + index), "type": 0, "name": "general"}]
    routes[("POST", f"/channels/{2000 + index}/invites")] = {"code": f"server-{index}"}
for index in range(20):
    routes[("POST", f"/channels/{3000 + index}/invites")] = {"code": f"group-{index}"}
http = FakeHTTP(routes)
with tempfile.TemporaryDirectory(prefix="discord-benchmark-") as task_dir:
    with patch("discord_backup.backup.write_backup", wraps=write_backup) as writes:
        start = time.perf_counter()
        _, data = Collector(http.client(), task_dir, passphrase=PASSWORD, log=lambda value: None, use_history=False).run()
        elapsed = time.perf_counter() - start
        result = {"seconds": round(elapsed, 3), "encrypted_writes": writes.call_count,
                  "api_requests": len(http.calls), "guilds": len(data["guilds"]), "groups": len(data["group-chats"]),
                  "status": data["status"],
                  "benchmark": "50 synthetic servers, 20 group chats, 256 KiB profile, simulated HTTP/no network delay"}
directory = ROOT / ".benchmarks"
directory.mkdir(exist_ok=True)
(directory / "after.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
