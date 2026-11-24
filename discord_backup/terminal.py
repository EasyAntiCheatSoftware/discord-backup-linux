# SPDX-License-Identifier: AGPL-3.0-only
"""Small ANSI terminal theme, with plain output for pipes and NO_COLOR."""

import builtins
import os
import shutil
import sys
import textwrap
import threading

from .progress import duration

STYLES = {"cyan": "96", "green": "92", "yellow": "93", "red": "91", "purple": "95",
          "blue": "94", "bold": "1", "dim": "2"}


def clean(value):
    # Names from Discord must not be able to inject terminal escape sequences.
    return "".join(character for character in str(value) if character in "\n\t" or (ord(character) >= 32 and not 127 <= ord(character) < 160))


class Console:
    def __init__(self, mode="auto"):
        self.mode = mode
        self._lock = threading.RLock()
        self._status_stream = None

    def enabled(self, stream=None):
        if self.mode == "always":
            return True
        if self.mode == "never" or "NO_COLOR" in os.environ:
            return False
        return os.environ.get("TERM") != "dumb" and (stream or sys.stdout).isatty()

    def paint(self, value, style, stream=None):
        text = clean(value)
        return f"\033[{STYLES[style]}m{text}\033[0m" if style and self.enabled(stream) else text

    def print(self, *values, sep=" ", end="\n", file=None, flush=False, style=None):
        text = sep.join(str(value) for value in values)
        if style is None:
            if text.startswith(("Error:", "Cannot ")):
                style = "red"
            elif text.startswith(("Warning:", "Waiting ", "Rate limited", "No usable", "No backups")):
                style = "yellow"
            elif text.startswith(("Saved", "Encrypted backup:", "Recovery page:", "Folder layout restored", "Favourite GIF settings restored")):
                style = "green"
            elif text.startswith(("Scanning ", "ETA:")):
                style = "cyan"
            elif text.startswith("Backing up "):
                style = "purple"
            elif text.startswith(("Estimated full-account", "Estimated backup attempt")):
                style = "bold"
        with self._lock:
            self._clear_status()
            builtins.print(self.paint(text, style, file), end=end, file=file, flush=flush)

    def input(self, prompt=""):
        with self._lock:
            self._clear_status()
        return builtins.input(self.paint(prompt, "cyan"))

    def _clear_status(self):
        if self._status_stream is not None:
            self._status_stream.write("\r\033[2K")
            self._status_stream.flush()
            self._status_stream = None

    def log(self, message):
        stdout = sys.stdout
        if message.startswith("ETA:") and stdout.isatty() and os.environ.get("TERM") not in (None, "", "dumb"):
            # ETA text uses ASCII so character count is also terminal width.
            width = shutil.get_terminal_size(fallback=(100, 24)).columns - 1
            if width >= 30:
                line = message if len(message) <= width else message[:width - 3] + "..."
                with self._lock:
                    self._clear_status()
                    stdout.write(self.paint(line, "cyan", stdout))
                    stdout.flush()
                    self._status_stream = stdout
                return
        self.print(message, flush=True)

    def banner(self, version):
        self.print(f"\n  Discord Backup {version}", style="bold")

    def menu(self):
        self.print()
        for number, label in (("1", "Back up account"), ("2", "Recover a backup"), ("0", "Exit")):
            self.print(f"  {number}  {label}", style="cyan")

    def backup_summary(self, data):
        status = data["status"]
        performance = data.get("performance", {})
        heading = f"\n  {status.upper()} · {data['account']}"
        if "duration_seconds" in data:
            heading += f" · {data['duration_seconds']:.1f}s"
            estimate = performance.get("estimated_total_seconds")
            if type(estimate) in (int, float):
                heading += f" (estimated {duration(estimate)})"
        self.print(heading, style="green" if status == "complete" else "yellow")
        counts = []
        for key, noun in (("guilds", "server"), ("friends", "friend"), ("group-chats", "group"), ("dm-history", "DM contact")):
            count = data[key]
            counts.append(f"{count} {noun}" + ("s" if count != 1 else ""))
        self.print("  " + " · ".join(counts))
        waits, throttles = data.get("cooldown_seconds", 0), performance.get("rate_limit_responses", 0)
        if waits or throttles:
            self.print(f"  Discord waits: {waits:.1f}s · {throttles} rate-limit responses", style="dim")
        if data.get("warnings"):
            width = max(40, min(120, shutil.get_terminal_size(fallback=(100, 24)).columns))
            self.print(f"\n  Warnings ({len(data['warnings'])})", style="yellow")
            affected = [key.replace("-", " ") + f" ({value})" for key, value in data.get("sections", {}).items()
                        if value in ("partial", "interrupted", "pending")]
            if affected:
                self.print(textwrap.fill("Sections needing attention: " + ", ".join(affected),
                           width=width, initial_indent="  ", subsequent_indent="    "), style="yellow")
            for warning in data["warnings"][:3]:
                self.print(textwrap.fill(clean(warning), width=width, initial_indent="  • ",
                           subsequent_indent="    "), style="yellow")
            remaining = len(data["warnings"]) - 3
            if remaining > 0:
                self.print(f"  {remaining} more in the recovery page or inspect output.", style="dim")
            self.print("  Unlock/export saved data. Run a new backup for missing sections.", style="dim")


console = Console()
