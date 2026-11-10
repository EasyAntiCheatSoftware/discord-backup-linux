# SPDX-License-Identifier: AGPL-3.0-only
"""Small private per-account timing samples. No credentials or backup contents."""

import hashlib
import json
import math
from pathlib import Path
from statistics import median
import time

from .storage import atomic_write, backup_directory, read_private_secret

MAX_AGE = 30 * 24 * 60 * 60
PHASES = ("profile", "folders", "favourite-gifs")


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**7


def valid(sample, now):
    return (isinstance(sample, dict) and type(sample.get("workers")) is int and sample["workers"] in (1, 2, 3, 4)
            and type(sample.get("invites")) is bool and type(sample.get("recorded")) in (int, float)
            and math.isfinite(sample["recorded"])
            and now - MAX_AGE <= sample["recorded"] <= now + 60
            and number(sample.get("checkpoint")) and isinstance(sample.get("phases"), dict)
            and set(sample["phases"]) <= set(PHASES) and all(number(v) for v in sample["phases"].values())
            and isinstance(sample.get("jobs"), dict) and set(sample["jobs"]) <= {"Servers", "Groups"}
            and all(number(v) for v in sample["jobs"].values()))


class TimingHistory:
    def __init__(self, account, *, invites, workers, directory=None):
        digest = hashlib.sha256(str(account).encode("ascii")).hexdigest()
        self.path = (Path(directory) if directory else backup_directory().parent / "timings") / (digest + ".json")
        self.invites, self.workers = invites, workers

    def _read(self):
        try:
            data = json.loads(read_private_secret(self.path, label="Timing history"))
            if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("samples"), list):
                return []
            now = time.time()
            return [sample for sample in data["samples"][-5:] if valid(sample, now)]
        except (OSError, ValueError, RecursionError):
            return []

    def forecast(self):
        samples = [s for s in self._read() if s["invites"] == self.invites and s["workers"] == self.workers]
        def values(group, key):
            return [s[group][key] for s in samples if key in s[group]]
        return {
            "samples": len(samples),
            "checkpoint": median(s["checkpoint"] for s in samples) if samples else None,
            "phases": {key: median(values("phases", key)) for key in PHASES if values("phases", key)},
            "jobs": {key: median(values("jobs", key)) for key in ("Servers", "Groups") if values("jobs", key)},
        }

    def record(self, *, checkpoint, phases, jobs):
        # Construct an allowlisted record; arbitrary account fields never enter the cache.
        sample = {"recorded": time.time(), "workers": self.workers, "invites": self.invites,
                  "checkpoint": checkpoint, "phases": {k: phases[k] for k in PHASES if k in phases},
                  "jobs": {k: jobs[k] for k in ("Servers", "Groups") if k in jobs}}
        if not valid(sample, time.time()):
            return
        samples = [*self._read(), sample][-5:]
        atomic_write(self.path, (json.dumps({"schema": 1, "samples": samples}, separators=(",", ":")) + "\n").encode())

