# SPDX-License-Identifier: AGPL-3.0-only
"""Account-workload time estimates; no account history or extra network requests."""

import math


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
