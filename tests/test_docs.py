"""Facts that live in more than one file must agree."""

from __future__ import annotations

import json
import re
import unittest

from litmus import __version__
from litmus.operators import DESCRIPTIONS, OPERATORS

from .helpers import ROOT


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class TestDocs(unittest.TestCase):
    def test_one_description_everywhere(self):
        pyproject = re.search(r'^description = "([^"]*)"$',
                              (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)  # type: ignore[union-attr]
        found = {
            "pyproject.toml": pyproject,
            "package.json": _json("package.json")["description"],
            "plugin.json": _json(".claude-plugin/plugin.json")["description"],
            "marketplace.json": _json(".claude-plugin/marketplace.json")["plugins"][0]["description"],
        }
        self.assertEqual(len(set(found.values())), 1, found)

    def test_one_version_everywhere(self):
        versions = {
            "package.json": _json("package.json")["version"],
            "plugin.json": _json(".claude-plugin/plugin.json")["version"],
            "marketplace.json": _json(".claude-plugin/marketplace.json")["plugins"][0]["version"],
        }
        self.assertEqual(set(versions.values()), {__version__}, versions)
        self.assertIn(f"## {__version__}", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_every_operator_is_documented(self):
        spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(set(DESCRIPTIONS), set(OPERATORS))
        for op in OPERATORS:
            self.assertIn(f"`{op}`", spec, op)
            self.assertIn(f"`{op}`", readme, op)

    def test_no_em_dashes_in_prose(self):
        for rel in ("README.md", "SPEC.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md",
                    "skills/litmus/SKILL.md", "commands/mutate.md"):
            self.assertNotIn("—", (ROOT / rel).read_text(encoding="utf-8"), rel)

    def test_mutate_command_passes_only_the_plugin_dir_to_vacuity(self):
        text = (ROOT / "commands/mutate.md").read_text(encoding="utf-8")
        vacuity = [ln for ln in text.splitlines() if "/bin/litmus\" vacuity" in ln]
        self.assertTrue(vacuity)
        for ln in vacuity:
            self.assertNotIn("$ARGUMENTS", ln)
            self.assertNotIn("--max-mutants", ln)
            self.assertNotIn("--files", ln)


if __name__ == "__main__":
    unittest.main()
