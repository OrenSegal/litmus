"""Facts that live in more than one file must agree.

The one-line description is written once per manifest because each format
needs its own copy; these tests are what keeps the copies equal. Docs never
carry a hand-counted number of tests, and every assertion the engine registers
is documented.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from litmus.assertions import _REGISTRY

ROOT = Path(__file__).resolve().parents[1]

ONE_LINER = ("Red/green regression tests for skills, prompts and tool definitions. "
             "A green only ever comes from a check that could have failed.")
BRAND_LINE = ("Part of [sous](https://github.com/OrenSegal/sous): "
              "tools for checking what coding agents actually do.")


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class TestOneDescription(unittest.TestCase):
    def test_every_manifest_carries_the_same_description(self):
        # tomllib is 3.11+, and the engine supports 3.10.
        pyproject = re.search(r'^description = "([^"]*)"$',
                              (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
        found = {
            "pyproject.toml": pyproject,
            "package.json": _json("package.json")["description"],
            "plugin.json": _json(".claude-plugin/plugin.json")["description"],
            "marketplace.json plugin": _json(".claude-plugin/marketplace.json")["plugins"][0]["description"],
        }
        for where, text in found.items():
            with self.subTest(where=where):
                self.assertEqual(text, ONE_LINER)

    def test_readme_opens_with_the_brand_line_then_the_description(self):
        lines = [ln for ln in (ROOT / "README.md").read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(lines[0], "# litmus")
        self.assertEqual(lines[1], BRAND_LINE)
        self.assertIn(ONE_LINER.split(". ")[0].lower(), lines[2].lower())


class TestNoHandCountedNumbers(unittest.TestCase):
    def test_docs_do_not_hardcode_test_or_assertion_counts(self):
        pattern = re.compile(r"\b\d+\s+(?:unit\s+)?(?:tests|passing|deterministic assertions)\b", re.I)
        for rel in ("README.md", "AGENTS.md", "CONTRIBUTING.md"):
            with self.subTest(file=rel):
                self.assertEqual(pattern.findall((ROOT / rel).read_text(encoding="utf-8")), [])


class TestEveryAssertionIsDocumented(unittest.TestCase):
    def test_registry_names_appear_in_the_spec_readme_and_skill_reference(self):
        for rel in ("LITMUS_SPEC.md", "README.md", "skills/litmus/references/assertions.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for name in _REGISTRY:
                with self.subTest(file=rel, assertion=name):
                    self.assertIn(f"`{name}`", text)


if __name__ == "__main__":
    unittest.main()
