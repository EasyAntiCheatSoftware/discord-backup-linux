# SPDX-License-Identifier: AGPL-3.0-only
"""GnuPG authenticated encryption; plaintext and passphrases stay off disk."""

import os
import shutil
import subprocess
import tempfile

MAGIC = b"DBLENC1\n"
MAX_PLAINTEXT = 64 * 1024 * 1024
MAX_CIPHERTEXT = MAX_PLAINTEXT + 1024 * 1024


def validate_passphrase(passphrase, *, creating=False):
    if not isinstance(passphrase, str) or not passphrase or any(character in passphrase for character in ("\n", "\r", "\x00")):
        raise ValueError("Enter a nonempty backup passphrase without line breaks")
    if len(passphrase.encode("utf-8")) > 1024:
        raise ValueError("Backup passphrase is too long (maximum 1024 UTF-8 bytes)")
    if creating and len(passphrase) < 12:
        raise ValueError("Use a backup passphrase of at least 12 characters")
    return passphrase


def require_gpg():
    executable = shutil.which("gpg")
    if not executable:
        raise ValueError("GnuPG is required for encrypted backups. On Arch install it with: sudo pacman -S gnupg")
    return executable


def _run_gpg(content, passphrase, *, encrypting):
    executable = require_gpg()
    validate_passphrase(passphrase, creating=encrypting)
    read_fd, write_fd = os.pipe()
    try:
        # A bounded passphrase fits in a pipe atomically; it is never an argv/env value.
        os.write(write_fd, passphrase.encode("utf-8") + b"\n")
        os.close(write_fd)
        write_fd = -1
        with tempfile.TemporaryDirectory(prefix="discord-backup-gpg-") as task_dir:
            arguments = [executable, "--no-options", "--homedir", task_dir, "--batch", "--no-tty",
                         "--no-autostart", "--no-keyring", "--no-symkey-cache", "--pinentry-mode", "loopback",
                         "--passphrase-fd", str(read_fd), "--status-fd", "2", "--output", "-"]
            if encrypting:
                arguments.extend(["--cipher-algo", "AES256", "--force-ocb", "--s2k-mode", "3",
                                  "--s2k-count", "65011712", "--s2k-digest-algo", "SHA512",
                                  "--compress-algo", "none", "--set-filename", "backup.json", "--symmetric"])
            else:
                arguments.extend(["--max-output", str(MAX_PLAINTEXT), "--decrypt"])
            try:
                result = subprocess.run(arguments, input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        pass_fds=(read_fd,), timeout=60, check=False)
            except subprocess.TimeoutExpired:
                raise ValueError("Backup encryption/decryption timed out") from None
            statuses = result.stderr.splitlines()
            authenticated = (
                statuses.count(b"[GNUPG:] BEGIN_DECRYPTION") == 1
                and statuses.count(b"[GNUPG:] END_DECRYPTION") == 1
                and statuses.count(b"[GNUPG:] DECRYPTION_OKAY") == 1
                and statuses.count(b"[GNUPG:] GOODMDC") == 1
                and b"[GNUPG:] DECRYPTION_INFO 0 9 2" in statuses  # AES-256, OCB
                and sum(line.startswith(b"[GNUPG:] PLAINTEXT ") for line in statuses) == 1
            )
            if result.returncode or (not encrypting and not authenticated):
                # GnuPG may emit unauthenticated plaintext before a final integrity failure.
                # Discard ALL stdout unless the process exits successfully.
                message = "GnuPG encryption failed; no plaintext backup was written" if encrypting else "Cannot unlock backup: incorrect passphrase, damaged file, or unsupported encryption"
                raise ValueError(message)
            return result.stdout
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)


def encrypt(content, passphrase):
    if len(content) > MAX_PLAINTEXT:
        raise ValueError("Backup exceeds the 64 MiB limit; previous checkpoint was preserved")
    return MAGIC + _run_gpg(content, passphrase, encrypting=True)


def decrypt(content, passphrase):
    if not content.startswith(MAGIC):
        raise ValueError("Not an encrypted Discord Backup Linux file")
    if len(content) > MAX_CIPHERTEXT:
        raise ValueError("Encrypted backup exceeds the size limit")
    result = _run_gpg(content[len(MAGIC):], passphrase, encrypting=False)
    if len(result) > MAX_PLAINTEXT:
        raise ValueError("Decrypted backup exceeds the 64 MiB limit")
    return result
