# Unlock an encrypted backup

The same `.bkup` file works on the original machine or another machine. You need the **backup passphrase** you chose when creating it. A Discord token is not needed to inspect, decrypt or export a backup. Keep your passphrase separately; there is no reset or recovery key.

## With the app — same machine or another Linux machine

1. Open **Discord Backup** and choose **2 — Recover / restore a backup**.
2. Select a recent backup from the current/default folders, or enter a custom folder/file path.
3. Enter its backup passphrase in the hidden prompt.
4. Choose **1 — Local recovery page + profile files**, select a new output directory, and open its `index.html`.

The export includes saved profile images, bio, contact/profile links, server/group invitations and warnings. It contains **decrypted personal data**. Keep that directory private. Export requires a new directory so it cannot overwrite a previous export.

The equivalent terminal commands are:

```sh
./run.sh inspect /path/to/backup.bkup
./run.sh export /path/to/backup.bkup --output "$HOME/discord-recovery"
xdg-open "$HOME/discord-recovery/index.html"
```

Use `discord-backup` instead of `./run.sh` if you installed the Arch package. `inspect` prints a summary and warnings; `export` creates the recovery page and extracts supported images. Neither contacts Discord. On another Linux machine, install the app and its dependencies, copy only the encrypted backup across, and use the same commands/passphrase. Do not copy an unattended token or passphrase file just to unlock a backup.

## Without the app — GnuPG 2.4 or newer

No app installation, Discord token, original computer, public key or private key is required. Install **GnuPG 2.4+** and copy the `.bkup` file and these instructions to the other machine.

The format starts with the eight bytes `DBLENC1` plus a newline. Everything after that wrapper is a standard password-encrypted OpenPGP message using AES-256/OCB. Remove only the first eight bytes before giving the message to GnuPG.

### Linux or macOS

From the directory containing your backup:

```sh
umask 077
tail -c +9 "backup.bkup" | gpg --output "backup.json" --decrypt
```

Replace `backup.bkup` with its real filename. GnuPG asks for the passphrase; do not put the passphrase in the command. Choose a new output filename if `backup.json` exists. Accept the output only when GnuPG reports successful decryption without integrity errors. Discard a partial output file left by a failed decryption.

### Windows PowerShell

Install GnuPG 2.4+ and make sure `gpg` is available in your terminal. Choose unused filenames for the intermediate message and decrypted output:

```powershell
if ((Test-Path "backup.gpg") -or (Test-Path "backup.json")) {
    throw "Choose unused output filenames before decrypting."
}
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path "backup.bkup"))
if ($bytes.Length -le 8 -or [System.Text.Encoding]::ASCII.GetString($bytes, 0, 8) -ne "DBLENC1`n") {
    throw "This is not an encrypted Discord Backup Linux file."
}
[System.IO.File]::WriteAllBytes("backup.gpg", $bytes[8..($bytes.Length - 1)])
gpg --output "backup.json" --decrypt "backup.gpg"
if ($LASTEXITCODE -ne 0) {
    throw "Decryption failed. Do not use any partial backup.json output."
}
```

GnuPG asks for the passphrase. `backup.gpg` remains encrypted. `backup.json` is plaintext, so protect it. The Windows instructions unlock the file; they do not install a Windows version of this Linux app.

## After unlocking

`backup.json` contains the saved invites, relationship IDs, contacts, profile data, settings and warnings. Avatar/banner contents are base64 fields. A partial backup unlocks the same way and contains only data collected before interruption. Decryption does not recreate missing sections or make expired invitations work.

The original `.bkup` stays encrypted and unchanged. Reading/exporting is offline; applying a saved folder/GIF layout is a separate operation that requires live account authentication and explicit apply.

## If it does not unlock

- **Incorrect passphrase:** use the backup passphrase, not your Discord password or token. There is no reset.
- **Unsupported encryption:** check `gpg --version`; this format needs GnuPG 2.4 or newer with OCB support.
- **Damaged or incomplete file:** retry from another copy of the original encrypted file. Do not trust partial plaintext after an integrity/decryption failure.
- **Legacy plaintext backup:** the app accepts the original JSON `.bkup` format directly; no encryption passphrase is needed until you create an encrypted copy.
