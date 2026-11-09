# Unlock a backup without Discord Backup Linux

You need the `.bkup` file, its backup passphrase, and **GnuPG 2.4 or newer**. The encryption is portable: no Discord token, original computer, app installation, public key, or private key is required.

The file starts with the eight bytes `DBLENC1` plus a newline. Everything after that header is a standard password-encrypted OpenPGP message using AES-256/OCB. Remove only those first eight bytes before giving the message to GnuPG.

## Linux or macOS

Install GnuPG using your distribution/package manager. From the directory containing your backup:

```sh
umask 077
tail -c +9 "backup.bkup" | gpg --output "backup.json" --decrypt
```

Replace `backup.bkup` with the actual filename. GnuPG asks for the backup passphrase; keep the passphrase out of the command itself. Choose a new output filename if `backup.json` already exists. Accept the output only when GnuPG reports successful decryption without integrity errors. A failed decryption may leave a partial output file, which you should discard.

## Windows PowerShell

With GnuPG installed and `gpg` available in your terminal:

```powershell
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path "backup.bkup"))
[System.IO.File]::WriteAllBytes("backup.gpg", $bytes[8..($bytes.Length - 1)])
gpg --output "backup.json" --decrypt "backup.gpg"
```

GnuPG asks for the passphrase. The intermediate `backup.gpg` is still encrypted.

## What you get

`backup.json` is readable JSON containing the saved server invites, relationship IDs, contacts, profile data, and settings. Avatar/banner contents are stored as base64 fields. A partial backup unlocks the same way, but includes only the sections completed before interruption. Decryption does not fill in missing sections.

The JSON file is plaintext; keep it private. The original `.bkup` stays encrypted and unchanged. There is no passphrase reset or recovery key. Keep a copy of these instructions with your backup files.
