import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from discord_backup.api import DiscordError
from discord_backup.cli import parser, select_token
from discord_backup.encryption import MAGIC, decrypt, encrypt
from discord_backup.storage import read_backup, write_backup
from discord_backup.tokens import Candidate, account_label, cache_locations, scan_tokens, validate_candidates
from test_backup import PASSWORD, ROOT, TemporaryTest, legacy


def token(uid="123456789012345678", signature="S"):
    first = base64.urlsafe_b64encode(uid.encode()).rstrip(b"=").decode()
    return first + ".ABCDEF." + signature * 38


class EncryptionTests(TemporaryTest):
    def test_roundtrip_requires_password_and_hides_metadata(self):
        first = self.directory / "first.bkup"
        second = self.directory / "second.bkup"
        write_backup(first, legacy(), passphrase=PASSWORD)
        write_backup(second, legacy(), passphrase=PASSWORD)
        self.assertTrue(first.read_bytes().startswith(MAGIC))
        self.assertNotIn(b'"friends"', first.read_bytes())
        self.assertNotIn(b"Saved bio", first.read_bytes())
        self.assertNotEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(read_backup(first, passphrase=PASSWORD), legacy())
        with self.assertRaisesRegex(ValueError, "encrypted"):
            read_backup(first)

    def test_wrong_password_and_tampering_release_no_data(self):
        encrypted = encrypt(json.dumps(legacy()).encode(), PASSWORD)
        with self.assertRaisesRegex(ValueError, "Cannot unlock"):
            decrypt(encrypted, "incorrect-password")
        damaged = bytearray(encrypted)
        damaged[len(damaged) // 2] ^= 1
        for value in (bytes(damaged), encrypted[:-10]):
            with self.assertRaisesRegex(ValueError, "Cannot unlock"):
                decrypt(value, PASSWORD)

    def test_unencrypted_openpgp_literal_packet_cannot_impersonate_backup(self):
        content = b'{"id":"1","name":"forged"}'
        literal = b"b\x00\x00\x00\x00\x00" + content
        packet = bytes([0xCB, len(literal)]) + literal
        with self.assertRaisesRegex(ValueError, "Cannot unlock"):
            decrypt(MAGIC + packet, PASSWORD)

    def test_missing_gpg_preserves_checkpoint_without_plaintext_fallback(self):
        path = self.directory / "saved.bkup"
        write_backup(path, legacy(), passphrase=PASSWORD)
        original = path.read_bytes()
        with patch("discord_backup.encryption.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "GnuPG"):
                write_backup(path, {**legacy(), "bio": "new private text"}, passphrase=PASSWORD)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [path])

    def test_passphrase_is_not_in_process_arguments_or_environment(self):
        real_run = subprocess.run
        with patch("discord_backup.encryption.subprocess.run", wraps=real_run) as run:
            ciphertext = encrypt(b"synthetic private data", PASSWORD)
        arguments = run.call_args.args[0]
        self.assertNotIn(PASSWORD, repr(arguments))
        self.assertIn("--passphrase-fd", arguments)
        self.assertNotIn("env", run.call_args.kwargs)
        self.assertEqual(decrypt(ciphertext, PASSWORD), b"synthetic private data")

    def test_cli_unlocks_with_private_file_and_exports(self):
        path = self.directory / "encrypted.bkup"
        write_backup(path, legacy(), passphrase=PASSWORD)
        secret = self.directory / "passphrase"
        secret.write_text(PASSWORD + "\n")
        secret.chmod(0o600)
        inspected = subprocess.run([sys.executable, ROOT / "main.py", "inspect", path, "--passphrase-file", secret], capture_output=True, text=True)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(json.loads(inspected.stdout)["friends"], 1)
        self.assertNotIn(PASSWORD, inspected.stdout + inspected.stderr)
        exported = subprocess.run([ROOT / "run.sh", "export", path, "--passphrase-file", secret, "--output", self.directory / "export"], capture_output=True, text=True)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertTrue((self.directory / "export/index.html").exists())

    def test_cli_encrypts_legacy_without_overwriting_original(self):
        source = self.directory / "legacy.bkup"
        original = json.dumps(legacy())
        source.write_text(original)
        secret = self.directory / "passphrase"
        secret.write_text(PASSWORD)
        secret.chmod(0o600)
        result = subprocess.run([ROOT / "run.sh", "encrypt", source, "--passphrase-file", secret], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_text(), original)
        self.assertEqual(read_backup(self.directory / "legacy-encrypted.bkup", passphrase=PASSWORD), legacy())

    def test_unicode_passphrase_with_spaces_roundtrips(self):
        password = "  doğru şifre uzun  "
        ciphertext = encrypt(b"test", password)
        self.assertEqual(decrypt(ciphertext, password), b"test")


class TokenTests(TemporaryTest):
    def cache(self, name, contents):
        directory = self.directory / name
        directory.mkdir()
        path = directory / "000001.ldb"
        path.write_bytes(contents)
        return directory

    def test_binary_cache_scanning_deduplicates_and_leaves_files_unchanged(self):
        raw = b'prefix\x00"' + token().encode() + b'"\x00suffix'
        first = self.cache("native", raw)
        second = self.cache("flatpak", raw)
        result = scan_tokens(locations=[("Discord", first), ("Flatpak", second)])
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].token, token())
        self.assertEqual(result.candidates[0].sources, ["Discord", "Flatpak"])
        self.assertNotIn(token(), repr(result))
        self.assertEqual((first / "000001.ldb").read_bytes(), raw)

    def test_token_crossing_chunk_boundary_is_complete_and_not_duplicated(self):
        raw = b"\x00" * (1024 * 1024 - 60) + token().encode() + b"\x00"
        directory = self.cache("boundary", raw)
        result = scan_tokens(locations=[("Discord", directory)])
        self.assertEqual([item.token for item in result.candidates], [token()])

    def test_invalid_patterns_and_symlinked_files_are_skipped(self):
        directory = self.cache("invalid", b"A" * 24 + b".ABCDEF." + b"S" * 38)
        secret = self.directory / "other.ldb"
        secret.write_text(token())
        (directory / "linked.ldb").symlink_to(secret)
        self.assertEqual(scan_tokens(locations=[("Discord", directory)]).candidates, [])

    def test_encrypted_entries_have_explicit_manual_fallback_warning(self):
        directory = self.cache("encrypted", b'dQw4w9WgXcQ:encrypted-data')
        result = scan_tokens(locations=[("Discord", directory)])
        self.assertEqual(result.candidates, [])
        self.assertTrue(any("manual" in message for message in result.warnings))

    def test_oversized_cache_is_not_read(self):
        directory = self.cache("large", b"")
        with (directory / "000001.ldb").open("r+b") as handle:
            handle.truncate(33 * 1024 * 1024)
        result = scan_tokens(locations=[("Discord", directory)])
        self.assertEqual(result.files_read, 0)
        self.assertTrue(result.warnings)

    def test_native_flatpak_and_vesktop_paths_are_discovered(self):
        locations = cache_locations(home=self.directory)
        by_name = [(label, str(path)) for label, path in locations]
        self.assertTrue(any(".config/discord/Local Storage/leveldb" in path for _, path in by_name))
        self.assertTrue(any(".var/app/com.discordapp.Discord/" in path for _, path in by_name))
        self.assertTrue(any("vesktop/sessionData/Local Storage/leveldb" in path for _, path in by_name))
        self.assertFalse(any(label == "Chrome" for label, _ in by_name))

    def test_validation_skips_expired_tokens_and_combines_same_account(self):
        class Client:
            def __init__(self, value):
                self.value = value

            def request(self, method, route):
                if self.value == "expired":
                    raise DiscordError("Invalid", 401, True)
                return {"id": "123456789012345678", "username": "example", "discriminator": "0"}

        result = validate_candidates([Candidate("expired", ["Old"]), Candidate(token(), ["Native"]), Candidate(token(signature="T"), ["Flatpak"])], client_factory=Client)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].sources, ["Native", "Flatpak"])
        self.assertNotIn(token(), account_label(result[0]))

    def test_interactive_scan_selection_never_prints_token(self):
        args = parser().parse_args(["backup"])
        candidate = Candidate(token(), ["Discord"], {"id": "123456789012345678", "username": "example"})
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("discord_backup.cli.scan_accounts", return_value=[candidate]), patch("builtins.input", side_effect=["1", "y", "1"]), redirect_stdout(output):
            selected = select_token(args)
        self.assertEqual(selected, token())
        self.assertTrue(args.scan_browsers)
        self.assertNotIn(token(), output.getvalue())

    def test_manual_choice_and_empty_scan_fallback(self):
        for arguments, answers in ((["backup"], ["2"]), (["backup", "--scan"], [])):
            args = parser().parse_args(arguments)
            with patch("sys.stdin.isatty", return_value=True), patch("discord_backup.cli.scan_accounts", return_value=[]), patch("discord_backup.cli.hidden_token", return_value="manual-token"), patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()):
                self.assertEqual(select_token(args), "manual-token")
