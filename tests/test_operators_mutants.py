from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from litmus.mutants import (ManifestError, Mutant, UnsafeMutantPath, generate, load_manifest, materialize, select,
                            sha256, stale, write_manifest)
from litmus.operators import OPERATORS, mutate_text, split_raw

from .helpers import TempDir, make_plugin

SKILL = """---
name: demo
description: Write release notes.
  Use when asked for a changelog.
---

# demo

Read the diff first.

1. Group changes under Added and Fixed.
- Never write a "Features" heading; say "No user-facing changes." instead.
- Always end with the version from `package.json`, then run `npm test`.
- Use Read before Bash. Keep bullets under 20 words.

```bash
never-touch-this --always 42
```
"""


class TestOperators(unittest.TestCase):
    def test_every_operator_is_deterministic_and_changes_text(self):
        for op in OPERATORS:
            a, b = mutate_text(SKILL, op), mutate_text(SKILL, op)
            self.assertTrue(a, f"{op} found no site")
            self.assertEqual([s.patched for s in a], [s.patched for s in b])
            for s in a:
                self.assertNotEqual(s.patched, SKILL)

    def test_body_operators_keep_frontmatter(self):
        head, _ = split_raw(SKILL)
        for op in OPERATORS:
            if op == "drop-description":
                continue
            for s in mutate_text(SKILL, op):
                self.assertTrue(s.patched.startswith(head), op)

    def test_code_fences_are_never_mutated(self):
        for op in ("delete-instruction", "invert-rule", "wrong-fact"):
            for s in mutate_text(SKILL, op):
                self.assertIn("never-touch-this --always 42", s.patched, op)

    def test_delete_body_and_truncate(self):
        (s,) = mutate_text(SKILL, "delete-body")
        self.assertEqual(s.patched.strip(), split_raw(SKILL)[0].strip())
        (t,) = mutate_text(SKILL, "truncate")
        self.assertLess(len(t.patched), len(SKILL))

    def test_invert_rule_flips_the_first_rule_word(self):
        patched = [s.patched for s in mutate_text(SKILL, "invert-rule")]
        self.assertTrue(any('- Always write a "Features"' in p for p in patched))
        self.assertTrue(any("- Never end with the version" in p for p in patched))

    def test_wrong_fact_skips_list_numbering(self):
        descs = [s.description for s in mutate_text(SKILL, "wrong-fact")]
        self.assertFalse(any("'1' ->" in d for d in descs))
        self.assertTrue(any("'20' -> '40'" in d for d in descs))
        self.assertTrue(any("'before' -> 'after'" in d for d in descs))

    def test_swap_tool_names_and_spans(self):
        sites = mutate_text(SKILL, "swap-tool-names")
        self.assertTrue(any("Use Bash before Read" in s.patched for s in sites))
        self.assertTrue(any("`npm test`" in s.description for s in sites))

    def test_drop_description_replaces_multiline_value(self):
        (s,) = mutate_text(SKILL, "drop-description")
        head, body = split_raw(s.patched)
        self.assertIn("description: General helper.", head)
        self.assertNotIn("changelog", head)
        self.assertEqual(body, split_raw(SKILL)[1])

    def test_no_frontmatter_no_description_mutant(self):
        self.assertEqual(mutate_text("just text\n- Never do x\n", "drop-description"), [])


class TestMutants(unittest.TestCase):
    def test_generate_ids_are_stable_and_select_round_robins(self):
        with TempDir() as d:
            root = make_plugin(d / "p", SKILL.split("---\n", 2)[2])
            files = [root / "skills/s/SKILL.md"]
            a = generate(root, files, list(OPERATORS), 5)
            b = generate(root, files, list(OPERATORS), 5)
            self.assertEqual([m.id for m in a], [m.id for m in b])
            picked = select(a, len(OPERATORS))
            self.assertEqual({m.operator for m in picked}, set(OPERATORS))
            self.assertEqual(select(a, None), a)

    def test_manifest_round_trip_and_tamper_detection(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            ms = generate(root, [root / "skills/s/SKILL.md"], ["invert-rule"], 5)
            path = d / "m.json"
            write_manifest(path, root, ms)
            back = load_manifest(path)
            self.assertEqual([m.patched for m in back], [m.patched for m in ms])
            doc = json.loads(path.read_text())
            doc["mutants"][0]["patched"] += "x"
            path.write_text(json.dumps(doc))
            with self.assertRaises(ManifestError):
                load_manifest(path)

    def test_manifest_rejects_paths_outside_root_and_wrong_schema(self):
        with TempDir() as d:
            m = Mutant("x", "llm:test", "../etc/passwd", 0, "", "0", "p")
            path = d / "m.json"
            write_manifest(path, d, [m])
            with self.assertRaises(ManifestError):
                load_manifest(path)
            path.write_text(json.dumps({"schema": "other"}))
            with self.assertRaises(ManifestError):
                load_manifest(path)

    def test_llm_mutant_replays_with_generator_recorded(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            orig = (root / "skills/s/SKILL.md").read_text()
            m = Mutant("llm:1", "llm:plausible-wrong-step", "skills/s/SKILL.md", 0, "skip step 2 politely",
                       sha256(orig), orig.replace("Never skip", "You may skip"),
                       {"kind": "llm", "model": "example-model", "prompt": "..."})
            write_manifest(d / "m.json", root, [m])
            (back,) = load_manifest(d / "m.json")
            self.assertEqual(back.generator["kind"], "llm")
            self.assertIsNone(stale(root, back))
            (root / "skills/s/SKILL.md").write_text(orig + "\nedited\n")
            self.assertIn("changed", stale(root, back) or "")

    def test_materialize_skips_results_and_git_and_links_node_modules(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            (root / "evals/results/old").mkdir(parents=True)
            (root / "evals/results/old/x.json").write_text("{}")
            (root / "evals/c").mkdir(parents=True)
            (root / ".git").mkdir()
            (root / "node_modules/dep").mkdir(parents=True)
            ms = generate(root, [root / "skills/s/SKILL.md"], ["delete-body"], 1)
            dest = materialize(root, d / "copy", ms[0], "evals/results")
            self.assertFalse((dest / "evals/results").exists())
            self.assertTrue((dest / "evals/c").is_dir())
            self.assertFalse((dest / ".git").exists())
            self.assertTrue(os.path.islink(dest / "node_modules"))
            self.assertEqual((dest / "skills/s/SKILL.md").read_text(), ms[0].patched)
            self.assertNotEqual((root / "skills/s/SKILL.md").read_text(), ms[0].patched)

    def test_materialize_never_writes_through_a_file_symlink(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            shared = d / "shared.md"
            shared.write_text("shared original\n")
            os.symlink(shared, root / "skills/s/LINKED.md")
            m = Mutant("x", "op", "skills/s/LINKED.md", 0, "", sha256("shared original\n"), "mutated\n")
            dest = materialize(root, d / "copy", m)
            self.assertFalse(os.path.islink(dest / "skills/s/LINKED.md"))
            self.assertEqual((dest / "skills/s/LINKED.md").read_text(), "mutated\n")
            self.assertEqual(shared.read_text(), "shared original\n")

    def test_materialize_refuses_a_target_under_a_symlinked_directory(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            outside = d / "outside"
            outside.mkdir()
            (outside / "x.md").write_text("original\n")
            os.symlink(outside, root / "shared")
            (root / "node_modules/dep").mkdir(parents=True)
            (root / "node_modules/dep/README.md").write_text("dep\n")
            for rel, path in (("shared/x.md", outside / "x.md"),
                              ("node_modules/dep/README.md", root / "node_modules/dep/README.md")):
                m = Mutant("x", "op", rel, 0, "", "0", "mutated\n")
                with self.assertRaises(UnsafeMutantPath):
                    materialize(root, d / ("copy-" + rel.split("/")[0]), m)
                self.assertNotEqual(path.read_text(), "mutated\n")

    def test_diff_is_unified(self):
        m = Mutant("x", "op", "f.md", 0, "", "0", "a\nc\n")
        self.assertIn("-b", m.diff("a\nb\n"))
        self.assertTrue(Path("f.md").as_posix() in m.diff("a\nb\n"))


if __name__ == "__main__":
    unittest.main()
