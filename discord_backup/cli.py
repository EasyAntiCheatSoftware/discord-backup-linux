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
import webbrowser

from . import __version__
from .api import DiscordClient, DiscordError
from .backup import BackupInterrupted, Collector, user_label
from .encryption import validate_passphrase
from .hub import BOT_PERMISSIONS, DiscordBotClient, bot_identity, hub_plan, prepare_hub, publish_hub, validate_bot_token
from .restore import AccountMismatch, export_recovery, restore_folders, restore_gifs, summary
from .schedule import install_schedule, passphrase_path, token_path
from .selection import remember_backup, select_backup
from .storage import atomic_write, backup_directory, is_encrypted, is_partial, read_backup, read_passphrase, read_private_secret, read_token, recovery_notice, snowflake, validate_token, write_backup
from .tokens import account_label, scan_tokens, validate_candidates
from .terminal import console

print = console.print
input = console.input


def choose(prompt, choices, *, default=None, case_sensitive=False, error=None):
    while True:
        answer = input(prompt).strip()
        if not case_sensitive:
            answer = answer.lower()
        if not answer and default is not None:
            return default
        if answer in choices:
            return answer
        print(error or ("Invalid option. Choose " + ", ".join(choices) + "."))


def yes_no(question, *, default):
    suffix = "[Y/n]" if default else "[y/N]"
    answer = choose(f"{question} {suffix}: ", ("y", "yes", "n", "no"),
                    default="y" if default else "n",
                    error="Invalid answer. Enter y/yes or n/no, or press Enter for the shown default.")
    return answer in ("y", "yes")


def confirm_action(word, prompt):
    return choose(prompt, (word, ""), case_sensitive=True,
                  error=f"Invalid confirmation. Type {word}, or press Enter to cancel.") == word


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
    args.backup = select_backup(args.backup, prompt=input, output=print, interactive=sys.stdin.isatty())
    password = passphrase_for(args) if is_encrypted(args.backup) else None
    data = read_backup(args.backup, passphrase=password)
    if is_partial(data):
        stream = sys.stderr if args.command == "inspect" else sys.stdout
        print("\nPARTIAL BACKUP", style="yellow", file=stream)
        print(recovery_notice(data), file=stream)
        print("Section status: " + ", ".join(f"{key}: {state}" for key, state in data.get("sections", {}).items()), file=stream)
    return data, password


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
        choice = choose("1  Scan stored Discord accounts\n2  Enter a token manually\nChoice [1]: ", ("1", "2"), default="1")
        if choice == "2":
            return hidden_token()
        if not getattr(args, "scan_browsers", False):
            args.scan_browsers = yes_no("Also scan Chrome/Chromium/Brave/Edge browser profiles?", default=False)
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
        if selection.isascii() and selection.isdigit() and len(selection) <= len(str(len(accounts))) and 1 <= int(selection) <= len(accounts):
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
    inspect.add_argument("backup", type=Path, nargs="?")
    add_passphrase_option(inspect)
    export = commands.add_parser("export", help="Create a local HTML recovery guide and extract profile images/bio")
    export.add_argument("backup", type=Path, nargs="?")
    add_passphrase_option(export)
    export.add_argument("--output", type=Path, help="New directory for recovery files")
    for name, help_text in (("restore-folders", "Preview or apply the saved folder layout"), ("restore-gifs", "Preview or apply the saved frecency/GIF settings block")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("backup", type=Path, nargs="?")
        add_auth_options(command)
        add_passphrase_option(command)
        command.add_argument("--apply", action="store_true", help="Apply changes; without this flag, only preview")
        command.add_argument("--allow-different-account", action="store_true")
        command.add_argument("--rollback-dir", type=Path, help="Directory for the before-change snapshot")
    recover = commands.add_parser("recover", help="Choose a backup and use the guided recovery menu")
    recover.add_argument("backup", type=Path, nargs="?", help="Optional backup file or folder to browse")
    add_passphrase_option(recover)
    hub = commands.add_parser("restore-hub", help="Preview or publish a private recovery hub through your own bot")
    hub.add_argument("backup", type=Path, nargs="?")
    add_passphrase_option(hub)
    hub.add_argument("--bot-token-file", type=Path, help="Private file containing your bot token; otherwise hidden input")
    hub.add_argument("--guild", help="Existing private recovery server ID; otherwise select from the bot's servers")
    hub.add_argument("--include", nargs="+", choices=("servers", "groups", "relationships", "contacts", "warnings"),
                     default=["servers", "groups", "relationships", "contacts", "warnings"])
    hub.add_argument("--apply", action="store_true", help="Publish after showing the destination and plan; otherwise preview")
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
            collector = Collector(client, args.output, passphrase=password, create_invites=not args.no_invites,
                                  workers=args.workers, log=console.log)
            try:
                path, data = collector.run()
            except BackupInterrupted:
                remember_backup(collector.path)
                console.backup_summary(summary(collector.data))
                raise
        remember_backup(path)
        print(f"Saved: {path}")
        console.backup_summary(summary(data))
        return 0 if data["status"] == "complete" else 2
    if args.command == "speed-test":
        temporary = tempfile.TemporaryDirectory(prefix="discord-backup-speed-test-")
        try:
            print("Speed test: encrypted backup files are temporary and will be deleted automatically.")
            with client_for(args) as client:
                _, data = Collector(client, temporary.name, passphrase=secrets.token_urlsafe(32),
                                    create_invites=not args.no_invites, workers=args.workers, log=console.log, use_history=False).run()
            console.backup_summary(summary(data))
            print(json.dumps(data["performance"], indent=2))
            return 0 if data["status"] == "complete" else 2
        finally:
            temporary.cleanup()
            print("Deleted the temporary test backup and its files.")
    if args.command == "inspect":
        data, _ = load_backup(args)
        print(json.dumps(summary(data), ensure_ascii=False, indent=2))
    elif args.command == "recover":
        return recovery_menu(args)
    elif args.command == "restore-hub":
        data, _ = load_backup(args)
        return hub_flow(args, data)
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


def settings_flow(args, data, password):
    action = restore_folders if args.command == "restore-folders" else restore_gifs
    with client_for(args) as client:
        allow_different = getattr(args, "allow_different_account", False)
        try:
            plan = action(client, data, allow_different=allow_different, log=console.log)
        except AccountMismatch as error:
            print(f"Backup account: {data['name']} ({data['id']})")
            print(f"Selected target: {user_label(error.target)} ({error.target['id']})")
            if not confirm_action("DIFFERENT", "Type DIFFERENT to preview a restore on this other account, or press Enter to cancel: "):
                print("Different-account restore cancelled; nothing changed")
                return
            allow_different = True
            plan = action(client, data, allow_different=True, log=console.log)
        if plan is not None:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not confirm_action("APPLY", "Type APPLY to save an encrypted rollback and apply this restore, or press Enter to cancel: "):
            print("Preview finished; nothing changed")
            return
        password = password if password is not None else hidden_passphrase(creating=True)
        options = {"expected_plan": plan} if args.command == "restore-folders" else {}
        action(client, data, apply=True, passphrase=password, allow_different=allow_different,
               directory=getattr(args, "rollback_dir", None), log=console.log, **options)


def choose_hub_server(bot):
    bot_identity(bot)
    guilds = bot.guilds()
    print("\nChoose a trusted recovery server you own. Its owner and administrators can read the recovered data.")
    for index, guild in enumerate(guilds, 1):
        print(f"  {index}  {guild.get('name', 'Server')} ({guild['id']})")
    if not guilds:
        application = bot.request("GET", "/oauth2/applications/@me")
        if isinstance(application, dict) and snowflake(application.get("id")):
            print("Add this bot to a private server using:")
            print(f"https://discord.com/oauth2/authorize?client_id={application['id']}&scope=bot&permissions={BOT_PERMISSIONS}")
        print("Create a private server in Discord if needed, then add the bot. No user account token is needed for this method.")
    while True:
        answer = input("Server number, a server ID, or 0 to cancel: ").strip()
        if answer == "0":
            raise ValueError("Recovery cancelled")
        if answer.isascii() and answer.isdigit() and len(answer) <= 3:
            if 1 <= int(answer) <= len(guilds):
                return str(guilds[int(answer) - 1]["id"])
        elif len(answer) > 3 and snowflake(answer):
            return answer
        print("Invalid option. Enter a listed server number, a server ID, or 0 to cancel.")


def hub_flow(args, data, *, confirm=False):
    include = getattr(args, "include", ["servers", "groups", "relationships", "contacts", "warnings"])
    hub_plan(data, include=include)  # Validate size and fields before asking for credentials.
    print("Recovery hub: automatically organize saved links and contacts in private Discord channels.")
    print("Joining servers, adding friends and changing your profile remain manual, as in the original project.")
    guide = Path(__file__).resolve().parents[1] / "docs/RECOVERY_HUB.md"
    if not guide.is_file():
        guide = Path("/usr/share/doc/discord-backup-linux/RECOVERY_HUB.md")
    print("Use your own bot in an existing trusted server. Setup guide:")
    print(guide if guide.is_file() else "https://github.com/EasyAntiCheatSoftware/discord-backup-linux/blob/main/docs/RECOVERY_HUB.md")
    token_file = getattr(args, "bot_token_file", None)
    token = read_private_secret(token_file, label="Bot token") if token_file else hidden_input("Your bot token (hidden; not saved): ")
    with DiscordBotClient(validate_bot_token(token), log=console.log) as bot:
        guild_id = getattr(args, "guild", None)
        if not guild_id:
            if not sys.stdin.isatty():
                raise ValueError("Use --guild with a recovery server ID for unattended operation")
            guild_id = choose_hub_server(bot)
        prepared = prepare_hub(bot, data, guild_id, include=include)
        count = sum(len(messages) for messages in prepared["channels"].values())
        guild = prepared["guild"]
        print(f"\nDestination: {guild['name']} ({guild['id']}); owner {guild['owner_id']}")
        print(f"Plan: 1 new private category, {len(prepared['channels'])} text channels, {count} messages")
        print("Included: " + ", ".join(include))
        print("This uploads decrypted backup data to Discord. The server owner, administrators and bot can access it.")
        apply = getattr(args, "apply", False)
        if confirm:
            apply = confirm_action("PUBLISH", "Type PUBLISH to create this recovery hub, or press Enter to cancel: ")
        if not apply:
            print("Preview only; no channels or messages were created. Use --apply to publish from the command line.")
            return 0
        report = publish_hub(bot, prepared, log=console.log)
        print(f"Recovery hub {report['status']}: {report['channels']} channels, {report['messages']} confirmed messages")
        return 0 if report["status"] == "complete" else 2


def recovery_menu(args):
    data, password = load_backup(args)
    source = args.backup
    print(f"\nLoaded {source.name}")
    print(f"Account: {data['name']} • {len(data.get('guilds', []))} servers • {len(data.get('friends', []))} friends • {len(data.get('group-chats', []))} groups")
    while True:
        print("\n  1  Local recovery page + profile files (offline)")
        print("  2  Private Discord recovery hub (your bot)")
        print("  3  Restore server folders (preview first)")
        print("  4  Restore favourite GIF settings (preview first)")
        print("  B  Choose another backup\n  0  Back")
        choice = choose("Recovery method [1]: ", ("1", "2", "3", "4", "b", "0"), default="1")
        try:
            if choice == "0":
                return 0
            if choice == "b":
                args.backup = None
                data, password = load_backup(args)
                source = args.backup
                print(f"Loaded {source.name} for {data['name']}")
            elif choice == "1":
                default = source.with_name(source.stem + "-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2))
                entered = input(f"New recovery folder [{default}]: ").strip()
                page, notices = export_recovery(data, Path(entered).expanduser() if entered else default)
                print(f"Recovery page: {page.resolve()}")
                print("These files contain decrypted personal data. Keep the recovery folder private.")
                for notice in notices:
                    print(f"Warning: {notice}")
                if yes_no("Open the local recovery page in your browser?", default=False):
                    if not webbrowser.open(page.resolve().as_uri()):
                        print("Open index.html from the recovery folder manually.")
            elif choice == "2":
                hub_args = parser().parse_args(["restore-hub", str(source)])
                if not yes_no("Include friends, relationships and DM contact links in the hub?", default=True):
                    hub_args.include = ["servers", "groups", "warnings"]
                hub_flow(hub_args, data, confirm=True)
            elif choice in ("3", "4"):
                command = "restore-folders" if choice == "3" else "restore-gifs"
                settings_flow(parser().parse_args([command, str(source)]), data, password)
            else:
                print("Choose one of the listed recovery methods.")
        except (OSError, ValueError, DiscordError) as error:
            print(f"Error: {error}", file=sys.stderr)


def menu():
    console.banner(__version__, backup_directory())
    while True:
        console.menu()
        choice = choose("Choice: ", tuple(str(number) for number in range(10)))
        if choice == "0":
            return 0
        command = []
        if choice == "1":
            command = ["backup"]
            if not yes_no("Create server/group invites where permitted?", default=True):
                command.append("--no-invites")
        elif choice in ("2", "3", "4"):
            command = [{"2": "recover", "3": "restore-folders", "4": "restore-gifs"}[choice]]
        elif choice in ("5", "6", "7", "8", "9"):
            command = [{"5": "list", "6": "save-token", "7": "schedule", "8": "save-passphrase", "9": "speed-test"}[choice]]
        else:
            print("Choose a number from the menu")
            continue
        try:
            if choice in ("3", "4"):
                args = parser().parse_args(command)
                data, password = load_backup(args)
                settings_flow(args, data, password)
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
