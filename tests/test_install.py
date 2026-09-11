"""Exercise installation in temporary homes without touching real harnesses."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NAME = "amplifier-skill-forge"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "test home"
        self.home.mkdir()
        self.source = self.base / "source checkout" / NAME
        (self.source / "scripts").mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/install.sh", self.source / "scripts/install.sh")
        self.write_source("SKILL.md", "---\nname: amplifier-skill-forge\ndescription: Test skill\n---\n")
        self.write_source("tools/forge.py", "print('original')\n")
        (self.source / "tools/forge.py").chmod(0o755)
        self.write_source("references/guide.md", "Reference\n")
        self.write_source("agents/openai.yaml", "interface: {}\n")
        for excluded in (".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".venv"):
            self.write_source(excluded + "/sentinel", "Do not install\n")
        self.write_source(".DS_Store", "Do not install\n")
        self.env = dict(os.environ, HOME=str(self.home), CODEX_HOME=str(self.home / ".codex"))

    def write_source(self, relative, content):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def install(self, *args, fallback=False):
        env = dict(self.env)
        if fallback:
            # Only the commands used by the fallback are visible; rsync is
            # deliberately absent even on hosts that have it installed.
            bindir = self.base / "fallback-bin"
            bindir.mkdir(exist_ok=True)
            for name in ("bash", "dirname", "mkdir", "ln", "unlink", "rm", "tar", "readlink", "mv", "date"):
                target = shutil.which(name)
                self.assertIsNotNone(target, name)
                link = bindir / name
                if not link.exists():
                    link.symlink_to(target)
            env["PATH"] = str(bindir)
        result = subprocess.run(
            ["/bin/bash", str(self.source / "scripts/install.sh"), *args],
            env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def assert_copies(self):
        for harness in (".agents", ".amplifier"):
            boundary = self.home / harness / "skills"
            dest = boundary / NAME
            self.assertTrue(dest.is_dir())
            self.assertFalse(dest.is_symlink())
            for relative in ("SKILL.md", "tools/forge.py", "references/guide.md", "agents/openai.yaml"):
                self.assertEqual((dest / relative).read_bytes(), (self.source / relative).read_bytes())
            self.assertTrue(os.access(dest / "tools/forge.py", os.X_OK))
            for excluded in (".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".venv", ".DS_Store"):
                self.assertFalse((dest / excluded).exists(), str(dest / excluded))
            # Mirrors the scanner's boundary check, including every descendant.
            for path in [dest, *dest.rglob("*")]:
                self.assertEqual(os.path.commonpath([path.resolve(), boundary.resolve()]), str(boundary.resolve()))
        self.assertEqual((self.home / ".claude/skills" / NAME).resolve(), self.source.resolve())

    def test_new_install_is_boundary_safe(self):
        self.install()
        self.assert_copies()

    def test_tar_fallback_installs_boundary_safe_copies(self):
        self.install(fallback=True)
        self.assert_copies()

    def test_migrates_external_symlinks_without_modifying_targets(self):
        outside = self.base / "old checkout"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("preserved")
        for harness in (".agents", ".amplifier"):
            dest = self.home / harness / "skills" / NAME
            dest.parent.mkdir(parents=True)
            dest.symlink_to(outside, target_is_directory=True)
        self.install()
        self.assert_copies()
        self.assertEqual(marker.read_text(), "preserved")
        self.assertEqual(list(outside.iterdir()), [marker])

    def test_reinstall_refreshes_changed_files_and_removes_stale_files(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                self.install(fallback=fallback)
                for harness in (".agents", ".amplifier"):
                    (self.home / harness / "skills" / NAME / "stale.txt").write_text("stale")
                self.write_source("tools/forge.py", "print('refreshed')\n")
                self.install(fallback=fallback)
                self.assert_copies()
                for harness in (".agents", ".amplifier"):
                    self.assertFalse((self.home / harness / "skills" / NAME / "stale.txt").exists())

    def test_dry_run_does_not_migrate_symlinks_or_create_directories(self):
        dest = self.home / ".agents/skills" / NAME
        dest.parent.mkdir(parents=True)
        dest.symlink_to(self.source, target_is_directory=True)
        before = sorted(str(p) for p in self.home.rglob("*"))
        output = self.install("--check").stdout
        self.assertIn("would copy:", output)
        self.assertTrue(dest.is_symlink())
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob("*")))


if __name__ == "__main__":
    unittest.main()
