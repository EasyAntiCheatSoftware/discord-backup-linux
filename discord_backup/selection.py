# SPDX-License-Identifier: AGPL-3.0-only
"""Interactive discovery of local backup files; no decryption during listing."""

import os
from pathlib import Path
import stat

from .storage import backup_directory

_last_directory = None


def remember_backup(path):
    global _last_directory
    if path is not None:
        _last_directory = Path(path).expanduser().absolute().parent


def default_locations():
    candidates = [Path.cwd(), Path.cwd() / 'backups', _last_directory, backup_directory()]
    result = []
    for path in candidates:
        if path is not None and path not in result:
            result.append(path)
    return result


def find_backups(directories, *, limit=40):
    found, seen = [], set()
    for directory in directories:
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= 5000:
                        break
                    if not entry.name.lower().endswith('.bkup') or entry.is_symlink():
                        continue
                    info = entry.stat(follow_symlinks=False)
                    inode = (info.st_dev, info.st_ino)
                    if stat.S_ISREG(info.st_mode) and inode not in seen:
                        seen.add(inode)
                        found.append((info.st_mtime, Path(entry.path), info.st_size))
        except OSError:
            continue
    return sorted(found, key=lambda item: (item[0], str(item[1])), reverse=True)[:limit]


def select_backup(source=None, *, prompt=input, output=print, interactive=True):
    locations = default_locations()
    if source is not None:
        path = Path(source).expanduser()
        if path.is_dir():
            locations = [path]
        else:
            if path.is_symlink() or not path.is_file():
                raise ValueError('Select an existing regular backup file; symlinks and special files are not accepted')
            remember_backup(path)
            return path
    if not interactive:
        raise ValueError('Specify a backup file for unattended use; selecting a directory needs a terminal')
    while True:
        files = find_backups(locations)
        output('\nChoose a backup — newest first')
        for index, (_, path, size) in enumerate(files, 1):
            output(f'  {index:>2}  {path.name}  ({size / 1024:.1f} KiB)')
            output(f'      {path.parent}')
        if not files:
            output('No .bkup files found in these folders.')
        output('  P   Enter another folder or a backup file path')
        output('  D   Search current/default backup folders again')
        output('  0   Cancel')
        answer = prompt('Backup number [1], P, D, or a path: ').strip()
        if not answer and files:
            remember_backup(files[0][1])
            return files[0][1]
        if answer == '0':
            raise ValueError('Backup selection cancelled')
        if answer.lower() == 'd':
            locations = default_locations()
            continue
        if answer.isascii() and answer.isdigit() and len(answer) <= 3:
            number = int(answer)
            if 1 <= number <= len(files):
                remember_backup(files[number - 1][1])
                return files[number - 1][1]
            output('Choose a listed backup number.')
            continue
        if answer.lower() == 'p':
            answer = prompt('Folder or .bkup file path: ').strip()
        if len(answer) > 1 and answer[0] == answer[-1] and answer[0] in ('"', "'"):
            answer = answer[1:-1]
        path = Path(answer).expanduser() if answer else None
        if path is not None and path.is_dir():
            locations = [path]
        elif path is not None and path.is_file() and not path.is_symlink():
            remember_backup(path)
            return path
        else:
            output('That path is not a backup file or folder. Try again, or choose 0 to cancel.')
