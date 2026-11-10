# SPDX-License-Identifier: AGPL-3.0-only
"""Account-workload time estimates; no account history or extra network requests."""

import math
import threading
import time


def duration(seconds):
    seconds = max(1, math.ceil(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def estimate_remaining(*, request_seconds, checkpoint_seconds, metadata_requests,
                       checkpoints, server_jobs, server_requests_per_job, group_jobs,
                       workers, invite_wait=0, serial_invites=False):
    """Rough wall time from this run's latency, work counts and known invite pause."""
    latency = max(0.01, request_seconds)
    parallel = 1 if serial_invites else workers
    metadata = metadata_requests * latency
    server_work = math.ceil(server_jobs / parallel) * server_requests_per_job * latency
    group_work = math.ceil(group_jobs / parallel) * latency
    # The start-rate guard applies even when the observed request latency is tiny.
    request_work = server_jobs * server_requests_per_job + group_jobs
    invitations = max(server_work + group_work, request_work / 25)
    pause = max(0, invite_wait - metadata) if request_work else 0
    return metadata + pause + invitations + checkpoints * max(0.01, checkpoint_seconds)


class EstimateReporter:
    """Keep ETA visible while the collector is blocked, using immutable snapshots."""

    def __init__(self, log, *, clock=time.monotonic, interval=5, hints=lambda: {}):
        if interval <= 0:
            raise ValueError("Progress interval must be positive")
        self.log, self.clock, self.interval, self.hints = log, clock, interval, hints
        self.started = clock()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._snapshot = None
        self._thread = threading.Thread(target=self._heartbeat, name="discord-backup-eta", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exception):
        self._stop.set()
        self._thread.join()

    def publish(self, account, *, remaining=None, note="", emit=True):
        with self._lock:
            self._snapshot = (account, remaining, note, self.clock())
            if emit:
                self._emit()

    def _emit(self):
        if self._snapshot is None:
            return
        account, remaining, note, sampled = self._snapshot
        now = self.clock()
        elapsed = max(0, now - self.started)
        elapsed_text = duration(int(elapsed)) if elapsed >= 1 else "0s"
        wait = max(0, self.hints().get("wait_seconds", 0))
        if remaining is None:
            message = f"ETA for {account}: calculating — {note}"
        else:
            remaining = max(0, remaining - max(0, now - sampled), wait)
            if remaining <= 0:
                message = f"ETA for {account}: recalculating — current work is taking longer than estimated"
            else:
                scope = "backup-attempt total" if 'available data only' in note else "whole-account total"
                message = f"ETA for {account}: about {duration(remaining)} remaining / {duration(elapsed + remaining)} {scope}"
                if note:
                    message += f" ({note})"
        message += f" | elapsed {elapsed_text}"
        if wait:
            message += f" | Discord wait {duration(wait)}"
        self.log(message)

    def _heartbeat(self):
        while not self._stop.wait(self.interval):
            with self._lock:
                if self._stop.is_set():
                    return
                try:
                    self._emit()
                except (OSError, ValueError):
                    # The output destination has closed; do not leak a worker traceback.
                    return
