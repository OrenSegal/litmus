"""Malformed input is exit 2 ("could not evaluate"), never a traceback.

A Python traceback exits 1, which litmus documents as "the suite failed the
bar". A CI job reading exit codes would take a typo in a file name for a
finding about the suite.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from litmus.adapters.claude_plugin_eval import ClaudePluginEvalAdapter
from litmus.adapters.base import CommandResult
from litmus.graders import Outcome, ProbeRun, evaluate
from litmus.models import Grader
from litmus.vacuity import analyze

from .helpers import DEMO, TempDir, make_plugin, write_case
from .test_engine_cli import cli


class TestAuditInput(unittest.TestCase):
    def check(self, content: bytes) -> None:
        with TempDir() as d:
            p = d / "r.json"
            p.write_bytes(content)
            code, _, err = cli("audit", str(p))
            self.assertEqual(code, 2, err)
            self.assertIn("litmus: error:", err)

    def test_json_that_is_not_an_object(self):
        self.check(b"[]")

    def test_file_that_is_not_utf8(self):
        self.check(b"\xff\xfe\x00")

    def test_right_schema_version_wrong_shape(self):
        self.check(json.dumps({"schemaVersion": 1, "cases": [1]}).encode())
        self.check(json.dumps({"schemaVersion": 1, "suite": {"threshold": "high"}, "cases": []}).encode())


class TestManifestInput(unittest.TestCase):
    def check(self, content: object) -> str:
        with TempDir() as d:
            m = d / "m.json"
            if content is not None:
                m.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            code, _, err = cli("mutate", str(DEMO), "--dry-run", "--mutants", str(m), "--out", str(d / "o"))
            self.assertEqual(code, 2, err)
            self.assertIn("litmus: error:", err)
            return err

    def test_missing_manifest_file(self):
        self.assertIn("m.json", self.check(None))

    def test_manifest_that_is_not_json(self):
        self.check("{not json")

    def test_manifest_that_is_not_an_object(self):
        self.check([])

    def test_mutants_that_are_not_objects(self):
        self.check({"schema": "litmus.mutants/1", "mutants": [1]})
        self.check({"schema": "litmus.mutants/1", "mutants": {"a": 1}})

    def test_mutant_fields_of_the_wrong_type(self):
        err = self.check({"schema": "litmus.mutants/1", "mutants": [
            {"id": "x", "operator": "manual", "file": "skills/changelog/SKILL.md", "original_sha256": "0",
             "patched": 7}]})
        self.assertIn("patched", err)


class TestGraderConfigLitmusCannotRead(unittest.TestCase):
    """AGENTS.md: a grader litmus cannot evaluate is UNKNOWN, never PASS."""

    def test_bad_numbers_make_the_grader_unknown(self):
        run = ProbeRun(prompt="p", last_message="TODO")
        for g in (Grader("g", "regex", config={"pattern": "TODO", "match": "count:x"}),
                  Grader("g", "tool_used", config={"tool": "Bash", "min": "lots"}),
                  Grader("g", "tool_used", config={"tool": "Bash", "max": "none"})):
            self.assertIs(evaluate(g, run).outcome, Outcome.UNKNOWN, g.config)

    def test_vacuity_reports_instead_of_crashing(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            write_case(root, "c", "Do it.", {
                "count": "---\ntype: regex\npattern: TODO\nmatch: count:x\n---\n",
                "min": "---\ntype: tool_used\ntool: Bash\nmin: lots\n---\n",
                "max": "---\ntype: tool_used\ntool: Bash\nmax: none\n---\n",
            })
            rep = analyze(ClaudePluginEvalAdapter().load_suite(root))
            self.assertEqual({g["status"] for g in rep["graders"]}, {"UNKNOWN"})
            self.assertTrue(all(g["reason"] for g in rep["graders"]))
            code, out, err = cli("vacuity", str(root))
            self.assertEqual(code, 0, err)  # nothing proven vacuous; only a judge-only style UNKNOWN


class TestResultOfUnexpectedShape(unittest.TestCase):
    def test_a_result_litmus_cannot_read_is_an_untrusted_run_not_a_crash(self):
        for doc in ([], {"schemaVersion": 1, "cases": [1]}, {"schemaVersion": 1, "cases": [{"arms": {"with": [3]}}]}):
            def runner(argv, cwd, timeout, label, env=None, doc=doc):  # type: ignore[no-untyped-def]
                Path(argv[argv.index("--json") + 1]).write_text(json.dumps(doc), encoding="utf-8")
                return CommandResult(0, "", "")

            with TempDir() as d:
                plugin = d / "demo"
                shutil.copytree(DEMO, plugin)
                a = ClaudePluginEvalAdapter(runner)
                run = a.run(plugin, a.load_suite(plugin), d / "out", "baseline")
                self.assertFalse(run.ok, doc)
                self.assertIn("result", run.error or "")


if __name__ == "__main__":
    unittest.main()
