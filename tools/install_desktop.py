#!/usr/bin/env python3
"""Install one desktop icon; preserve the old duplicate script outside the desktop."""

from datetime import datetime
from pathlib import Path
import subprocess


def install_desktop(root, desktop):
    root, desktop = Path(root), Path(desktop)
    desktop.mkdir(parents=True, exist_ok=True)
    launcher = desktop / "Discord Backup.desktop"
    if launcher.is_symlink() or (launcher.exists() and "Name=Discord Backup" not in launcher.read_text()):
        raise ValueError(f"Refusing to replace an unrelated launcher: {launcher}")
    command = str(root / "run.sh")
    escaped = command.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    launcher.write_text(f'''[Desktop Entry]
Version=1.0
Type=Application
Name=Discord Backup
Comment=Scan accounts or enter a token and create encrypted backups
Exec="{escaped}" --color always
Icon=utilities-terminal
Terminal=true
Categories=Utility;Archiving;
''')
    launcher.chmod(0o755)
    duplicate = desktop / "Discord Backup.sh"
    archived = None
    if duplicate.is_file() and not duplicate.is_symlink() and "# Discord Backup Linux desktop launcher" in duplicate.read_text():
        archive = root / ".legacy-launchers"
        archive.mkdir(exist_ok=True)
        archived = archive / "Discord Backup.sh"
        if archived.exists():
            archived = archive / f"Discord Backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sh"
        duplicate.rename(archived)
    return launcher, archived


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        lookup = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=False)
        location = lookup.stdout.strip() if lookup.returncode == 0 else ""
    except FileNotFoundError:
        location = ""
    desktop = Path(location) if location else Path.home() / "Desktop"
    launcher, archived = install_desktop(root, desktop)
    print(f"Desktop launcher: {launcher}")
    if archived:
        print(f"Moved the duplicate script off the desktop: {archived}")


if __name__ == "__main__":
    main()
