# SPDX-License-Identifier: AGPL-3.0-only
"""Generate inspectable systemd user units; enabling them is a separate command."""

from pathlib import Path
import sys

from .storage import atomic_write, backup_directory, xdg_path


def token_path():
    return xdg_path("XDG_CONFIG_HOME", ".config") / "discord-backup-linux/token"


def passphrase_path():
    return xdg_path("XDG_CONFIG_HOME", ".config") / "discord-backup-linux/backup-passphrase"


def systemd_quote(value):
    value = str(value)
    if any(ord(character) < 32 for character in value):
        raise ValueError("Systemd paths cannot contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def install_schedule(token_file=None, output=None, *, passphrase_file=None, create_invites=False):
    token_file = Path(token_file or token_path()).expanduser().resolve()
    output = Path(output or backup_directory()).expanduser().resolve()
    passphrase_file = Path(passphrase_file or passphrase_path()).expanduser().resolve()
    entrypoint = Path(__file__).resolve().parents[1] / "main.py"
    arguments = [sys.executable, entrypoint, "backup", "--token-file", token_file, "--passphrase-file", passphrase_file, "--output", output]
    if not create_invites:
        arguments.append("--no-invites")
    service = """[Unit]
Description=Discord account backup
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
UMask=0077
NoNewPrivileges=true
TimeoutStartSec=1h
""" + "ExecStart=" + " ".join(systemd_quote(argument) for argument in arguments) + "\n"
    timer = """[Unit]
Description=Discord account backup after login and daily

[Timer]
OnStartupSec=2min
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15min

[Install]
WantedBy=timers.target
"""
    units = xdg_path("XDG_CONFIG_HOME", ".config") / "systemd/user"
    atomic_write(units / "discord-backup.service", service.encode())
    atomic_write(units / "discord-backup.timer", timer.encode())
    return units
