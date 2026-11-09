# Contributing

Keep account credentials and real backups out of issues, pull requests, test fixtures, screenshots, and logs. Use the synthetic `FakeHTTP` transport in `tests/test_backup.py` for reproducible network behavior. Do not ask contributors to run a live account backup just to run the test suite.

Run `python3 -m unittest discover -s tests -v` and `python3 tools/release.py --check` before submitting a change. Add regression coverage for changed behavior, particularly rate budgets, cancellation, credential handling, encryption failures, and restore writes. Tests need GnuPG 2.4+ and Requests. Keep compatibility with Python 3.10 unless the runtime requirement is intentionally changed.

`release-files.txt` is the exact source publication list. Adding a source/test/document file requires reviewing it and adding its path in sorted order. Build output, local benchmark results, credential files, backups and recovery exports belong outside this list. Do not weaken the release check to make an unexplained file pass.

Describe a concrete problem, the resulting behavior, and the checks you ran. For a performance change, state the workload and whether latency was simulated or measured live. Do not describe fewer waits as an improvement unless the implementation still follows server budgets and cooldowns.

AGPL-3.0-only applies to contributions. Preserve attribution and SPDX headers where present. See SECURITY.md for reporting a credential leak or vulnerability privately.
