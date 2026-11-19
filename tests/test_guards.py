"""Tests added after mutation-testing litmus's own critical paths by hand.

Each one fails when a single line of the rule it names is changed; before
they existed that change left the whole suite green.
"""

from __future__ import annotations

import json
import unittest
from typing import List

from litmus.adapters.claude_plugin_eval import ClaudePluginEvalAdapter, parse_result
from litmus.engine import MutateOptions, mutate
from litmus.models import CaseRun, SuiteRun, Verdict
from litmus.scoring import classify, green_cases

from .helpers import DEMO, ROOT, FakeRunner, TempDir, demo_scores, make_plugin, result_doc, write_case
from .test_engine_cli import cli


class TestScoringGuards(unittest.TestCase):
    def test_a_baseline_case_with_an_error_is_not_green_whatever_its_score(self):
        base = SuiteRun(ok=True, cases={"a": CaseRun(1.0, error="infrastructure error in 1 run(s): 429"),
                                        "b": CaseRun(1.0)})
        self.assertEqual(green_cases(base, 1.0), ["b"])
        mutant = SuiteRun(ok=True, cases={"a": CaseRun(0.0), "b": CaseRun(1.0)})
        self.assertIs(classify(base, mutant, 1.0)[0], Verdict.SURVIVED)  # `a` cannot show a kill

    def test_majority_rule_is_a_strict_majority(self):
        base = SuiteRun(ok=True, cases={"a": CaseRun(1.0)})
        tie = SuiteRun(ok=True, cases={"a": CaseRun(0.5, run_scores=[0.0, 1.0])})
        self.assertIs(classify(base, tie, 1.0, majority=True)[0], Verdict.SURVIVED)
        self.assertIs(classify(base, tie, 1.0)[0], Verdict.KILLED)

    def test_a_run_that_skipped_paid_graders_is_untrusted_for_that_case(self):
        doc = result_doc({"a": 0.0, "b": 1.0})
        doc["cases"][0]["arms"]["with"][0]["skippedPaidGraders"] = True
        r = parse_result(doc, 1)
        self.assertIn("cost ceiling", r.cases["a"].error or "")
        self.assertIsNone(r.cases["b"].error)
        base = parse_result(result_doc({"a": 1.0, "b": 1.0}))
        self.assertIs(classify(base, r, 1.0)[0], Verdict.INCONCLUSIVE)


class TestEngineSpendGuards(unittest.TestCase):
    def test_no_green_baseline_case_launches_no_mutant_run(self):
        with TempDir() as d:
            runner = FakeRunner(lambda w: result_doc({"tests-only-diff": 0.0, "ends-with-version": 0.0}))
            rep = mutate(ClaudePluginEvalAdapter(runner), DEMO, d, MutateOptions(max_mutants=3))
            self.assertEqual(runner.labels, ["baseline"], "mutant runs were paid for with nothing to kill")
            self.assertEqual({m["verdict"] for m in rep["mutants"]}, {"INCONCLUSIVE"})

    def test_an_untrusted_baseline_stops_the_repeats_and_launches_no_mutant(self):
        with TempDir() as d:
            runner = FakeRunner(lambda w: result_doc({"tests-only-diff": 1.0}, partial=True))
            rep = mutate(ClaudePluginEvalAdapter(runner), DEMO, d, MutateOptions(max_mutants=3, baseline_runs=3))
            self.assertEqual(runner.labels, ["baseline"])
            self.assertFalse(rep["baseline"]["ok"])

    def test_a_case_red_in_a_later_baseline_repeat_cannot_show_a_kill(self):
        seen: List[int] = []

        def score(workdir):  # type: ignore[no-untyped-def]
            seen.append(1)
            doc = demo_scores(workdir)
            if len(seen) == 2:  # green in the first baseline, red in the second
                doc["cases"][0]["aggregates"]["score"] = 0.0
            return doc

        with TempDir() as d:
            rep = mutate(ClaudePluginEvalAdapter(FakeRunner(score)), DEMO, d,
                         MutateOptions(max_mutants=4, baseline_runs=2))
            self.assertEqual(rep["baseline"]["red_cases"], ["tests-only-diff"])
            self.assertNotIn("KILLED", {m["verdict"] for m in rep["mutants"]})


class TestSubjectAndGate(unittest.TestCase):
    def test_prose_inside_the_eval_directory_is_never_a_subject(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            (root / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "p", "version": "0.0.1", "experimental": {"evals": "skills/evals"}}))
            case = write_case(root, "c", "Do it.", {"g": "---\ntype: regex\npattern: x\n---\n"}, eval_dir="skills/evals")
            (case / "SKILL.md").write_text("---\nname: fixture\n---\n- Never mutate me.\n")
            a = ClaudePluginEvalAdapter()
            files = [p.relative_to(root.resolve()).as_posix() for p in a.subject_files(a.load_suite(root))]
            self.assertEqual(files, ["skills/s/SKILL.md"])

    def test_min_score_is_the_gate_between_exit_0_and_exit_1(self):
        rec = str(ROOT / "examples/demo-recordings")  # the demo scores 50%
        with TempDir() as d:
            common = ("mutate", str(DEMO), "--replay-results", rec, "--allow-vacuous", "--quiet")
            self.assertEqual(cli(*common, "--out", str(d / "a"), "--min-score", "0.5")[0], 0)
            self.assertEqual(cli(*common, "--out", str(d / "b"), "--min-score", "0.51")[0], 1)


if __name__ == "__main__":
    unittest.main()
