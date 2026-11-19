"""bin/install.js copies the skill into a directory it may have to replace.
It must never delete a directory that is not a previous copy of this skill."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from .helpers import ROOT, TempDir

NODE = shutil.which("node")


def install(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run([NODE or "node", str(ROOT / "bin" / "install.js"), "--dir", str(target)],
                          capture_output=True, text=True, timeout=60)


@unittest.skipUnless(NODE, "node is not installed")
class TestInstaller(unittest.TestCase):
    def test_installs_into_a_new_or_empty_directory(self):
        with TempDir() as d:
            for target in (d / "new" / "litmus", d / "empty"):
                (d / "empty").mkdir(exist_ok=True)
                res = install(target)
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertTrue((target / "SKILL.md").is_file())

    def test_replaces_a_previous_install_and_drops_its_stale_files(self):
        with TempDir() as d:
            self.assertEqual(install(d / "s").returncode, 0)
            (d / "s" / "stale.md").write_text("from an older version\n")
            self.assertEqual(install(d / "s").returncode, 0)
            self.assertFalse((d / "s" / "stale.md").exists())
            self.assertTrue((d / "s" / "SKILL.md").is_file())

    def test_refuses_to_delete_a_directory_that_is_not_this_skill(self):
        # `--dir ~/.claude/skills` (the parent, not the skill's own folder) used
        # to delete every installed skill and leave one SKILL.md behind.
        with TempDir() as d:
            skills = d / "skills"
            (skills / "other-skill").mkdir(parents=True)
            (skills / "other-skill" / "SKILL.md").write_text("---\nname: other-skill\n---\nprecious\n")
            res = install(skills)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("not a litmus skill", res.stderr)
            self.assertEqual((skills / "other-skill" / "SKILL.md").read_text(), "---\nname: other-skill\n---\nprecious\n")
            self.assertFalse((skills / "SKILL.md").exists())

    def test_refuses_another_skill_s_own_folder(self):
        with TempDir() as d:
            other = d / "other"
            other.mkdir()
            (other / "SKILL.md").write_text("---\nname: other\n---\nprecious\n")
            self.assertNotEqual(install(other).returncode, 0)
            self.assertIn("precious", (other / "SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()
