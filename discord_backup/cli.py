# SPDX-License-Identifier: AGPL-3.0-only
"""Terminal menu and scriptable Linux command line interface."""

import argparse
from datetime import datetime
import getpass
import json
from pathlib import Path
import secrets
import sys
import tempfile
import warnings

from . import __version__
from .api import DiscordClient, DiscordError
from .backup import Collector
from .encryption import validate_passphrase
from .restore import export_recovery, restore_folders, restore_gifs, summary
from .schedule import install_schedule, passphrase_path, token_path
from .storage import atomic_write, backup_directory, is_encrypted, read_backup, read_passphrase, read_token, validate_token, write_backup
from .tokens import account_label, scan_tokens, validate_candidates
from .terminal import console

print = console.print
input = console.input


def hidden_input(prompt):
    if not sys.stdin.isatty():
        raise ValueError("A terminal is required for hidden input; use private --token-file/--passphrase-file options for unattended runs")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(console.paint(prompt, "cyan", sys.stderr))
        except getpass.GetPassWarning:
            raise ValueError("Cannot hide secret input in this terminal") from None


def hidden_token():
    return validate_token(hidden_input("Your Discord account token (hidden): "))


def hidden_passphrase(*, creating=False):
    if creating:
        print("Choose a backup passphrase of at least 12 characters. Keep it: it is required to unlock your backups.")
    password = validate_passphrase(hidden_input("Backup passphrase (hidden): "), creating=creating)
    if creating and hidden_input("Confirm backup passphrase: ") != password:
        raise ValueError("Backup passphrases did not match")
    return password


def passphrase_for(args, *, creating=False):
    password = read_passphrase(args.passphrase_file) if getattr(args, "passphrase_file", None) else hidden_passphrase(creating=creating)
    return validate_passphrase(password, creating=creating)


def load_backup(args):
    password = passphrase_for(args) if is_encrypted(args.backup) else None
    return read_backup(args.backup, passphrase=password), password


def scan_accounts(args):
    print("Scanning your local Discord caches (tokens stay hidden)…")
    result = scan_tokens(browsers=getattr(args, "scan_browsers", False), extra_paths=getattr(args, "scan_path", []))
    print(f"Read {result.files_read} cache files; found {len(result.candidates)} candidate tokens")
    for message in result.warnings:
        print(f"Warning: {message}")
    if not result.candidates:
        return []
    print("Checking accounts with Discord…")
    return validate_candidates(result.candidates, log=console.log)


def select_token(args):
    if getattr(args, "token_file", None):
        return read_token(args.token_file)
    if getattr(args, "manual", False):
        return hidden_token()
    if not sys.stdin.isatty():
        raise ValueError("Account selection needs a terminal; use --token-file for unattended runs")
    if not getattr(args, "scan", False):
        choice = input("1  Scan stored Discord accounts\n2  Enter a token manually\nChoice [1]: ").strip()
        if choice == "2":
            return hidden_token()
        if choice not in ("", "1"):
            raise ValueError("Choose 1 to scan or 2 for manual entry")
        if not getattr(args, "scan_browsers", False):
            args.scan_browsers = input("Also scan Chrome/Chromium/Brave/Edge browser profiles? [y/N]: ").strip().lower() == "y"
    try:
        accounts = scan_accounts(args)
    except DiscordError as error:
        print(str(error))
        accounts = []
    if not accounts:
        print("No usable cached accounts found. You can enter your token manually.")
        return hidden_token()
    for index, candidate in enumerate(accounts, 1):
        print(f"{index}  {account_label(candidate)}")
    while True:
        selection = input("Select an account number, M for manual entry, or 0 to cancel: ").strip()
        if selection.lower() == "m":
            return hidden_token()
        if selection == "0":
            raise ValueError("Account selection cancelled")
        if selection.isdigit() and 1 <= int(selection) <= len(accounts):
            return accounts[int(selection) - 1].token
        print("Choose one of the listed accounts or M for manual entry")


def client_for(args):
    return DiscordClient(select_token(args), log=console.log)


def add_auth_options(command):
    choice = command.add_mutually_exclusive_group()
    choice.add_argument("--token-file", type=Path)
    choice.add_argument("--scan", action="store_true", help="Scan Linux Discord caches and select an account")
    choice.add_argument("--manual", action="store_true", help="Enter a token in a hidden prompt")
    command.add_argument("--scan-browsers", action="store_true", help="Also scan Chromium/Chrome/Brave/Edge profile caches")
    command.add_argument("--scan-path", type=Path, action="append", default=[], help="Additional LevelDB cache directory (repeatable)")


def add_passphrase_option(command):
    command.add_argument("--passphrase-file", type=Path, help="Private passphrase file for unattended encryption/decryption")


def add_backup_options(command):
    command.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=3, help="Independent invite workers sharing Discord's rate limits (default: 3)")
    command.add_argument("--no-invites", action="store_true", help="Read-only backup; save membership without creating invites")


def parser():
    root = argparse.ArgumentParser(prog="discord-backup", description="Discord account backup and recovery for Arch/Linux. Run without arguments for a menu.")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="Terminal colors (also respects NO_COLOR)")
    commands = root.add_subparsers(dest="command")
    backup = commands.add_parser("backup", help="Save an account; creates invites where permitted unless --no-invites")
    add_auth_options(backup)
    add_passphrase_option(backup)
    backup.add_argument("--output", type=Path, default=None, help="Backup directory (default: XDG data directory)")
    add_backup_options(backup)
    speed = commands.add_parser("speed-test", help="Time a real backup in temporary encrypted storage, then delete its files")
    add_auth_options(speed)
    add_backup_options(speed)
    inspect = commands.add_parser("inspect", help="Show a .bkup summary offline")
    inspect.add_argument("backup", type=Path)
    add_passphrase_option(inspect)
    export = commands.add_parser("export", help="Create a local HTML recovery guide and extract profile images/bio")
    export.add_argument("backup", type=Path)
    add_passphrase_option(export)
    export.add_argument("--output", type=Path, help="New directory for recovery files")
    for name, help_text in (("restore-folders", "Preview or apply the saved folder layout"), ("restore-gifs", "Preview or apply the saved frecency/GIF settings block")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("backup", type=Path)
        add_auth_options(command)
        add_passphrase_option(command)
        command.add_argument("--apply", action="store_true", help="Apply changes; without this flag, only preview")
        command.add_argument("--allow-different-account", action="store_true")
        command.add_argument("--rollback-dir", type=Path, help="Directory for the before-change snapshot")
    listing = commands.add_parser("list", help="List local .bkup files")
    listing.add_argument("--directory", type=Path, default=None)
    save = commands.add_parser("save-token", help="Explicitly save your token with mode 0600 for unattended backups")
    save.add_argument("--output", type=Path, default=None)
    add_auth_options(save)
    secret = commands.add_parser("save-passphrase", help="Explicitly save a private backup passphrase for scheduled runs")
    secret.add_argument("--output", type=Path, default=None)
    scanner = commands.add_parser("scan", help="List locally stored Discord accounts without showing tokens")
    scanner.add_argument("--scan-browsers", action="store_true")
    scanner.add_argument("--scan-path", type=Path, action="append", default=[])
    encryption = commands.add_parser("encrypt", help="Encrypt an existing plaintext .bkup file into a new file")
    encryption.add_argument("backup", type=Path)
    encryption.add_argument("--output", type=Path)
    add_passphrase_option(encryption)
    schedule = commands.add_parser("schedule", help="Write systemd user service/timer files for review and manual enabling")
    schedule.add_argument("--token-file", type=Path, default=None)
    add_passphrase_option(schedule)
    schedule.add_argument("--output", type=Path, default=None, help="Backup directory")
    schedule.add_argument("--create-invites", action="store_true", help="Allow scheduled runs to create invites (default: read-only)")
    return root


def execute(args):
    if args.command == "backup":
        with client_for(args) as client:
            password = passphrase_for(args, creating=True)
            path, data = Collector(client, args.output, passphrase=password, create_invites=not args.no_invites,
                                   workers=args.workers, log=console.log).run()
        print(f"Saved: {path}")
        console.backup_summary(summary(data))
        return 0 if data["status"] == "complete" else 2
    if args.command == "speed-test":
        temporary = tempfile.TemporaryDirectory(prefix="discord-backup-speed-test-")
        try:
            print("Speed test: encrypted backup files are temporary and will be deleted automatically.")
            with client_for(args) as client:
                _, data = Collector(client, temporary.name, passphrase=secrets.token_urlsafe(32),
                                    create_invites=not args.no_invites, workers=args.workers, log=console.log).run()
            console.backup_summary(summary(data))
            print(json.dumps(data["performance"], indent=2))
            return 0 if data["status"] == "complete" else 2
        finally:
            temporary.cleanup()
            print("Deleted the temporary test backup and its files.")
    if args.command == "inspect":
        data, _ = load_backup(args)
        print(json.dumps(summary(data), ensure_ascii=False, indent=2))
    elif args.command == "export":
        data, _ = load_backup(args)
        output = args.output or args.backup.expanduser().with_name(args.backup.stem + "-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        page, notices = export_recovery(data, output)
        print(f"Recovery page: {page.resolve()}")
        print("The recovery export contains decrypted profile and contact data; keep this directory private.")
        for notice in notices:
            print(f"Warning: {notice}")
        return 2 if notices else 0
    elif args.command in ("restore-folders", "restore-gifs"):
        data, password = load_backup(args)
        if args.apply and password is None:
            password = passphrase_for(args, creating=True)
        action = restore_folders if args.command == "restore-folders" else restore_gifs
        with client_for(args) as client:
            plan = action(client, data, apply=args.apply, allow_different=args.allow_different_account, directory=args.rollback_dir, passphrase=password, log=console.log)
        if not args.apply:
            if plan is not None:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            print("Preview only. Run again with --apply to save a rollback snapshot and apply changes.")
    elif args.command == "list":
        directory = (args.directory or backup_directory()).expanduser()
        paths = sorted(directory.glob("*.bkup"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths:
            print(path)
        if not paths:
            print(f"No backups in {directory}")
    elif args.command == "save-token":
        output = (args.output or token_path()).expanduser()
        if output.exists() or output.is_symlink():
            raise ValueError("Token file already exists; choose a new --output path or remove the old file yourself")
        atomic_write(output, (select_token(args) + "\n").encode())
        print(f"Saved private token file: {output}")
    elif args.command == "save-passphrase":
        output = (args.output or passphrase_path()).expanduser()
        if output.exists() or output.is_symlink():
            raise ValueError("Passphrase file already exists; choose a new --output path")
        atomic_write(output, (hidden_passphrase(creating=True) + "\n").encode())
        print(f"Saved private passphrase file: {output}")
    elif args.command == "scan":
        accounts = scan_accounts(args)
        for index, candidate in enumerate(accounts, 1):
            print(f"{index}  {account_label(candidate)}")
        if not accounts:
            print("No usable accounts found; manual token entry is available from the backup menu.")
    elif args.command == "encrypt":
        if is_encrypted(args.backup):
            raise ValueError("This backup is already encrypted")
        data = read_backup(args.backup)
        output = args.output or args.backup.expanduser().with_name(args.backup.stem + "-encrypted.bkup")
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists; choose a new file")
        write_backup(output, data, passphrase=passphrase_for(args, creating=True))
        print(f"Encrypted backup: {output}")
        print("The original plaintext backup still exists. After checking the encrypted copy, remove the original if you no longer need it.")
    elif args.command == "schedule":
        token_file = args.token_file or token_path()
        passphrase_file = args.passphrase_file or passphrase_path()
        read_token(token_file)  # Validate ownership and permissions before writing units.
        validate_passphrase(read_passphrase(passphrase_file), creating=True)
        units = install_schedule(token_file, args.output, passphrase_file=passphrase_file, create_invites=args.create_invites)
        print(f"Wrote units in {units}. Review them, then enable with:")
        print("systemctl --user daemon-reload")
        print("systemctl --user enable --now discord-backup.timer")
    return 0


def menu():
    console.banner(__version__, backup_directory())
    while True:
        console.menu()
        choice = input("Choice: ").strip()
        if choice == "0":
            return 0
        command = []
        if choice == "1":
            command = ["backup"]
            if input("Create server/group invites where permitted? [Y/n]: ").strip().lower() == "n":
                command.append("--no-invites")
        elif choice in ("2", "3", "4"):
            source = input("Path to .bkup file: ").strip()
            command = [{"2": "export", "3": "restore-folders", "4": "restore-gifs"}[choice], source]
        elif choice in ("5", "6", "7", "8", "9"):
            command = [{"5": "list", "6": "save-token", "7": "schedule", "8": "save-passphrase", "9": "speed-test"}[choice]]
        else:
            print("Choose a number from the menu")
            continue
        try:
            if choice in ("3", "4"):
                args = parser().parse_args(command)
                data, password = load_backup(args)
                action = restore_folders if choice == "3" else restore_gifs
                with client_for(args) as client:
                    plan = action(client, data, log=console.log)
                    if plan is not None:
                        print(json.dumps(plan, ensure_ascii=False, indent=2))
                    if input("Type APPLY to save a rollback snapshot and apply this restore: ").strip() == "APPLY":
                        password = password if password is not None else hidden_passphrase(creating=True)
                        options = {"expected_plan": plan} if choice == "3" else {}
                        action(client, data, apply=True, passphrase=password, log=console.log, **options)
                    else:
                        print("Preview finished; nothing changed")
                continue
            result = execute(parser().parse_args(command))
            if result == 2:
                print("Completed with warnings; review the details above")
        except (OSError, ValueError, DiscordError) as error:
            print(f"Error: {error}", file=sys.stderr)


def main(argv=None):
    args = parser().parse_args(argv)
    console.mode = args.color
    try:
        if args.command is None:
            if not sys.stdin.isatty():
                parser().print_help()
                return 0
            return menu()
        return execute(args)
    except (OSError, ValueError, DiscordError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled", file=sys.stderr)
        return 130
