"""Release selection and privacy regressions; all candidate secrets are synthetic."""

import hashlib
import importlib.util
import os
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_tool", ROOT / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def tree(self, path):
        (path / "discord_backup").mkdir()
        (path / "discord_backup/__init__.py").write_text('__version__ = "1.0.0"\n')
        (path / "packaging/arch").mkdir(parents=True)
        (path / "packaging/arch/PKGBUILD").write_text("sha256sums=('@SOURCE_SHA256@')\n")
        (path / "release-files.txt").write_text(
            "discord_backup/__init__.py\npackaging/arch/PKGBUILD\nrelease-files.txt\n")

    def test_manifest_blocks_unreviewed_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root)
            extra = root / "discord_backup/private-secret"
            extra.write_text("synthetic secret")
            with self.assertRaisesRegex(ValueError, "Unlisted"):
                release.verify_tree(root)
            extra.unlink()
            extra.symlink_to(root / "release-files.txt")
            with self.assertRaisesRegex(ValueError, "symlink"):
                release.verify_tree(root)

    def test_secret_check_reports_location_without_value(self):
        fake = b"a" * 24 + b"." + b"b" * 6 + b"." + b"c" * 30
        with self.assertRaises(ValueError) as result:
            release.check_content("candidate.py", fake)
        self.assertIn("candidate.py", str(result.exception))
        self.assertNotIn(fake.decode(), str(result.exception))
        with self.assertRaises(ValueError):
            release.check_content("candidate.py", b"/" + b"home/private-user/file")

    @patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1234"})
    def test_archive_is_deterministic_and_uses_only_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.tree(root)
            private = root / "dist"
            private.mkdir()
            (private / "never-publish.bkup").write_bytes(b"synthetic private data")
            one = release.build(root, output=root / "dist/first")
            before = one.read_bytes()
            (root / "discord_backup/__init__.py").touch()
            two = release.build(root, output=root / "dist/second")
            self.assertEqual(before, two.read_bytes())
            with tarfile.open(one) as archive:
                self.assertEqual(len(archive.getmembers()), 3)
                self.assertTrue(all(m.uid == m.gid == 0 and m.mtime == 1234 and m.uname == m.gname == "root" for m in archive))
                self.assertFalse(any("never-publish" in m.name for m in archive))
            recipe = (root / "dist/first/arch/PKGBUILD").read_text()
            self.assertNotIn("@SOURCE_SHA256@", recipe)
            self.assertIn(hashlib.sha256(before).hexdigest(), recipe)

    def test_source_stage_contains_only_reviewed_files_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root, stage = Path(directory) / "source", Path(directory) / "stage"
            root.mkdir()
            self.tree(root)
            release.build(root, stage=stage)
            self.assertEqual(release.verify_tree(stage), release.verify_tree(root))
            with self.assertRaisesRegex(ValueError, "already exists"):
                release.build(root, stage=stage)

    def test_current_source_manifest_is_clean(self):
        self.assertIn("LICENSE", release.verify_tree(ROOT))


if __name__ == "__main__":
    unittest.main()
