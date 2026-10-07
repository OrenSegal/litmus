from __future__ import annotations

import unittest

from litmus.adapters.claude_plugin_eval import ClaudePluginEvalAdapter, SuiteError, parse_result
from litmus.models import CaseRun, SuiteRun, Verdict
from litmus.scoring import MutantResult, classify, summarize

from .helpers import DEMO, TempDir, make_plugin, result_doc, write_case

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


class TestLoadSuite(unittest.TestCase):
    def test_demo_suite_loads(self):
        a = ClaudePluginEvalAdapter()
        s = a.load_suite(DEMO)
        self.assertEqual(sorted(c.name for c in s.cases), ["ends-with-version", "no-todo-left", "tests-only-diff"])
        case = next(c for c in s.cases if c.name == "tests-only-diff")
        g = next(x for x in case.graders if x.name == "no-features-heading")
        self.assertEqual((g.type, g.config["match"], g.config["flags"]), ("regex", "not_contains", "m"))
        self.assertIn("release notes", case.prompt)
        self.assertEqual([p.relative_to(DEMO).as_posix() for p in a.subject_files(s)],
                         ["skills/changelog/SKILL.md"])

    @unittest.skipUnless(HAVE_YAML, "case.yaml with a graders list needs PyYAML")
    def test_case_yaml_and_manifest_eval_dir(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            (root / ".claude-plugin/plugin.json").write_text('{"name":"p","experimental":{"evals":"qa"}}')
            c = root / "qa" / "yaml-case"
            c.mkdir(parents=True)
            (c / "case.yaml").write_text(
                'schema_version: "1.1"\nname: yaml-case\nexecution:\n  prompt: hello\n  max_turns: 3\n'
                "graders:\n  - name: said-hi\n    type: regex\n    pattern: hi\n")
            write_case(root, "md-case", "p", {"g": "---\ntype: llm\n---\nPASS if x. FAIL if y.\n"}, eval_dir="qa")
            (root / "qa/results/2026/x").mkdir(parents=True)
            (root / "qa/results/2026/x/prompt.md").write_text("ignored")
            s = ClaudePluginEvalAdapter().load_suite(root)
            names = sorted(c.name for c in s.cases)
            self.assertEqual(names, ["md-case", "yaml-case"])
            yc = next(c for c in s.cases if c.name == "yaml-case")
            self.assertEqual((yc.prompt, yc.graders[0].config["pattern"]), ("hello", "hi"))
            judge = next(c for c in s.cases if c.name == "md-case").graders[0]
            self.assertIn("FAIL if y", judge.config["criteria"])

    def test_bad_suites_raise_readable_errors(self):
        with TempDir() as d:
            root = make_plugin(d / "p")
            with self.assertRaises(SuiteError):
                ClaudePluginEvalAdapter().load_suite(root)
            write_case(root, "c", "p", {"g": "---\nweight: 1\n---\n"})
            with self.assertRaisesRegex(SuiteError, "no type"):
                ClaudePluginEvalAdapter().load_suite(root)

    def test_command_uses_one_arm_and_passes_options(self):
        a = ClaudePluginEvalAdapter(runs=3, threshold=0.8, model="sonnet", judge_model="haiku",
                                    allow_tools=["Bash"], scaffold=True, case_glob="x*", eval_dir="qa",
                                    max_cost_usd=1.5)
        argv = a.command(DEMO, DEMO / "out.json")
        joined = " ".join(argv)
        for frag in ("plugin eval", "--ablation none", "--runs 3", "--threshold 0.8", "--trust-plugin",
                     "--no-publish", "--json", "--model sonnet", "--judge-model haiku", "--allow-tools Bash",
                     "--scaffold", "--case x*", "--eval-dir qa", "--max-cost-usd 1.50"):
            self.assertIn(frag, joined)


class TestParseResult(unittest.TestCase):
    def test_exit_one_is_a_normal_run(self):
        r = parse_result(result_doc({"a": 0.5}), returncode=1)
        self.assertTrue(r.ok)
        self.assertEqual(r.cases["a"].score, 0.5)

    def test_partial_or_crash_is_untrusted(self):
        self.assertFalse(parse_result(result_doc({"a": 1.0}, partial=True)).ok)
        self.assertFalse(parse_result(result_doc({"a": 1.0}), returncode=2).ok)
        self.assertFalse(parse_result({"schemaVersion": 2}).ok)

    def test_infra_error_marks_case_but_timeout_does_not(self):
        r = parse_result(result_doc({"a": 0.0, "b": 0.0},
                                    errors={"a": "API rate limit exceeded", "b": "timed out after 300s"}))
        self.assertIsNotNone(r.cases["a"].error)
        self.assertIsNone(r.cases["b"].error)


def run(**scores) -> SuiteRun:  # type: ignore[no-untyped-def]
    return SuiteRun(ok=True, cases={k: CaseRun(v) for k, v in scores.items()})


class TestClassify(unittest.TestCase):
    def test_killed_only_when_a_baseline_green_case_drops(self):
        base = run(a=1.0, b=0.5)
        self.assertIs(classify(base, run(a=0.0, b=0.5), 1.0)[0], Verdict.KILLED)
        self.assertEqual(classify(base, run(a=0.0, b=0.5), 1.0)[1], ["a"])
        self.assertIs(classify(base, run(a=1.0, b=0.0), 1.0)[0], Verdict.SURVIVED)

    def test_inconclusive_never_counts_as_killed(self):
        base = run(a=1.0)
        self.assertIs(classify(base, SuiteRun(ok=False, error="partial"), 1.0)[0], Verdict.INCONCLUSIVE)
        errored = SuiteRun(ok=True, cases={"a": CaseRun(0.0, error="rate limit")})
        self.assertIs(classify(base, errored, 1.0)[0], Verdict.INCONCLUSIVE)
        self.assertIs(classify(base, run(), 1.0)[0], Verdict.INCONCLUSIVE)
        self.assertIs(classify(run(a=0.5), run(a=0.0), 1.0)[0], Verdict.INCONCLUSIVE)
        self.assertIs(classify(SuiteRun(ok=False, error="x"), run(a=0.0), 1.0)[0], Verdict.INCONCLUSIVE)

    def test_a_real_kill_beats_an_errored_case(self):
        base = run(a=1.0, b=1.0)
        mixed = SuiteRun(ok=True, cases={"a": CaseRun(0.0), "b": CaseRun(None, error="auth failed")})
        self.assertIs(classify(base, mixed, 1.0)[0], Verdict.KILLED)

    def test_score_counts_inconclusive_in_the_denominator(self):
        rs = [MutantResult("1", "a", "f", "", Verdict.KILLED), MutantResult("2", "a", "f", "", Verdict.SURVIVED),
              MutantResult("3", "b", "f", "", Verdict.INCONCLUSIVE), MutantResult("4", "b", "f", "", None)]
        s = summarize(rs)
        self.assertAlmostEqual(s["mutation_score"], 1 / 3)
        self.assertAlmostEqual(s["decided_score"], 1 / 2)
        self.assertEqual((s["not_run"], s["total_run"]), (1, 3))
        self.assertEqual(s["by_operator"]["b"]["INCONCLUSIVE"], 1)
        self.assertIsNone(summarize([])["mutation_score"])


if __name__ == "__main__":
    unittest.main()
