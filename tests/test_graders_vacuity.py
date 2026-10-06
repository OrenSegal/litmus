from __future__ import annotations

import unittest

from litmus.frontmatter import FrontmatterError, _mini, split
from litmus.graders import Outcome, ProbeRun, UntranslatableRegex, evaluate, js_regex, trace_text
from litmus.models import Case, Grader, Suite
from litmus.vacuity import analyze, failing, scored_graders

from .helpers import DEMO


def g(type_: str, name: str = "g", weight: float = 1, arm=None, body: str = "", **config) -> Grader:  # type: ignore[no-untyped-def]
    return Grader(name=name, type=type_, weight=weight, arm=arm, config=config, body=body)


def suite_of(*cases: Case) -> Suite:
    return Suite(root=DEMO, eval_dir=DEMO / "evals", cases=list(cases), adapter="test")


class TestFrontmatter(unittest.TestCase):
    def test_split_and_body(self):
        meta, body = split("---\ntype: regex\nweight: 2\n---\n\nrubric\n")
        self.assertEqual(meta, {"type": "regex", "weight": 2})
        self.assertEqual(body.strip(), "rubric")

    def test_no_frontmatter(self):
        self.assertEqual(split("plain"), ({}, "plain"))

    def test_unclosed_frontmatter_is_an_error(self):
        with self.assertRaises(FrontmatterError):
            split("---\ntype: regex\n")

    def test_mini_parser_handles_eval_frontmatter(self):
        d = _mini("type: tool_used\ninput_match: '\"skill\"\\s*:\\s*\"x\"'\nmin: 0\nmax: 0\n"
                  "allowed_tools: [Read, Glob]\nbefore: { tool: Bash, input_match: 'a,b' }\n"
                  "flag: true\nnothing: null\ncontext:\n  scaffold_script: setup.sh\ntags:\n  - a\n  - b\n"
                  "dq: \"a\\\\b\\x27\"\n")
        self.assertEqual(d["input_match"], '"skill"\\s*:\\s*"x"')
        self.assertEqual((d["min"], d["max"]), (0, 0))
        self.assertEqual(d["allowed_tools"], ["Read", "Glob"])
        self.assertEqual(d["before"], {"tool": "Bash", "input_match": "a,b"})
        self.assertIs(d["flag"], True)
        self.assertIsNone(d["nothing"])
        self.assertEqual(d["context"], {"scaffold_script": "setup.sh"})
        self.assertEqual(d["tags"], ["a", "b"])
        self.assertEqual(d["dq"], "a\\b'")

    def test_mini_parser_refuses_what_it_cannot_read(self):
        with self.assertRaises(FrontmatterError):
            _mini("  indented: first\n")
        with self.assertRaises(FrontmatterError):
            _mini("not a key line\n")


class TestGraders(unittest.TestCase):
    R = ProbeRun(prompt="please", last_message="Hello World",
                   tool_calls=[("Read", {"file_path": "package.json"}), ("Bash", {"command": "ls"})],
                   files_created={"out/report.md": "# Report\nTODO"})

    def test_regex_modes_and_flags(self):
        self.assertIs(evaluate(g("regex", pattern="world", flags="i"), self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("regex", pattern="world"), self.R).outcome, Outcome.FAIL)
        self.assertIs(evaluate(g("regex", pattern="zzz", match="not_contains"), self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("regex", pattern="o", match="count:2"), self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("regex", pattern="o", match="count:3"), self.R).outcome, Outcome.FAIL)

    def test_regex_targets(self):
        self.assertIs(evaluate(g("regex", pattern="please", target="trace"), self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("regex", pattern=r"report\.md", target="files"), self.R).outcome, Outcome.PASS)
        fsrc = {"source": "file", "path": "out/report.md"}
        self.assertIs(evaluate(g("regex", pattern="TODO", target=fsrc), self.R).outcome, Outcome.PASS)
        missing = {"source": "file", "path": "nope.md"}
        self.assertIs(evaluate(g("regex", pattern="x", target=missing), self.R).outcome, Outcome.UNKNOWN)
        self.assertIs(evaluate(g("regex", pattern="x", target="mock_calls"), self.R).outcome, Outcome.UNKNOWN)

    def test_trace_is_compact_json_with_prompt_first(self):
        t = trace_text(self.R).splitlines()
        self.assertIn('"content":"please"', t[0])
        self.assertIn('"name":"Read"', t[1])

    def test_tool_used(self):
        self.assertIs(evaluate(g("tool_used", tool="Read", input_match=r"package\.json"), self.R).outcome,
                      Outcome.PASS)
        self.assertIs(evaluate(g("tool_used", tool="Write"), self.R).outcome, Outcome.FAIL)
        self.assertIs(evaluate(g("tool_used", tool="Bash", min=0, max=0), self.R).outcome, Outcome.FAIL)
        self.assertIs(evaluate(g("tool_used", tool="Write", min=0, max=0), self.R).outcome, Outcome.PASS)

    def test_tool_order_and_file_exists(self):
        both = g("tool_order", before="Read", after={"tool": "Bash", "input_match": "ls"})
        self.assertIs(evaluate(both, self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("tool_order", before="Bash", after="Read"), self.R).outcome, Outcome.FAIL)
        self.assertIs(evaluate(g("file_exists", path="out/*.md"), self.R).outcome, Outcome.PASS)
        self.assertIs(evaluate(g("file_exists", path="*.pdf", exists=False), self.R).outcome, Outcome.PASS)

    def test_judge_graders_are_unknown(self):
        self.assertIs(evaluate(g("llm", body="PASS if x"), self.R).outcome, Outcome.UNKNOWN)

    def test_js_regex_translation(self):
        py, _ = js_regex(r"(?<year>\d{4})-\k<year>")
        self.assertIn("(?P<year>", py)
        self.assertIn("(?P=year)", py)
        self.assertEqual(js_regex("[^]")[0], r"[\s\S]")
        with self.assertRaises(UntranslatableRegex):
            js_regex(r"\p{L}", "u")
        with self.assertRaises(UntranslatableRegex):
            js_regex("(unclosed")
        with self.assertRaises(UntranslatableRegex):
            js_regex("a", "q")

    def test_untranslatable_pattern_is_unknown_not_pass(self):
        self.assertIs(evaluate(g("regex", pattern="(unclosed"), self.R).outcome, Outcome.UNKNOWN)
        self.assertIs(evaluate(g("tool_used", tool="Read", input_match="(x"), self.R).outcome, Outcome.UNKNOWN)


class TestVacuity(unittest.TestCase):
    def status(self, rep, name):  # type: ignore[no-untyped-def]
        return next(x for x in rep["graders"] if x["grader"] == name)

    def test_static_vacuous_and_always_fails(self):
        case = Case("c", DEMO, "p", [
            g("tool_used", "min0", tool="Read", min=0),
            g("regex", "empty", pattern="x*"),
            g("regex", "neverabsent", pattern="", match="not_contains"),
            g("tool_used", "inverted", tool="Read", min=3, max=1),
            g("regex", "real", pattern="def "),
        ])
        rep = analyze(suite_of(case))
        self.assertEqual(self.status(rep, "min0")["status"], "VACUOUS")
        self.assertEqual(self.status(rep, "empty")["status"], "VACUOUS")
        self.assertEqual(self.status(rep, "neverabsent")["status"], "ALWAYS_FAILS")
        self.assertEqual(self.status(rep, "inverted")["status"], "ALWAYS_FAILS")
        self.assertEqual(self.status(rep, "real")["status"], "DISCRIMINATES")
        self.assertTrue(failing(rep))

    def test_null_green_case_from_guards_only(self):
        case = Case("c", DEMO, "p", [g("regex", "no-todo", pattern="TODO", match="not_contains")])
        rep = analyze(suite_of(case))
        f = self.status(rep, "no-todo")
        self.assertEqual(f["status"], "NULL_PASS")
        self.assertTrue(f["guard"])
        self.assertEqual({c["status"] for c in rep["cases"]}, {"NULL_GREEN"})
        self.assertTrue(failing(rep))

    def test_echo_probe_catches_answer_in_prompt(self):
        case = Case("c", DEMO, "Reply with the word banana.", [g("regex", "banana", pattern="banana")])
        rep = analyze(suite_of(case))
        self.assertEqual(rep["cases"][0]["probes"]["echo"], "GREEN")
        self.assertEqual(rep["cases"][0]["probes"]["silent"], "RED")

    def test_positive_grader_makes_case_ok(self):
        case = Case("c", DEMO, "p", [g("regex", "no-todo", pattern="TODO", match="not_contains"),
                                     g("regex", "has-def", pattern=r"def\s+\w+")])
        rep = analyze(suite_of(case))
        self.assertEqual({c["status"] for c in rep["cases"]}, {"OK"})
        self.assertFalse(failing(rep))

    def test_with_without_excludes_skill_graders(self):
        case = Case("c", DEMO, "p", [g("tool_used", "fired", tool="Skill"),
                                     g("tool_used", "ran", tool="Bash", arm="with-only"),
                                     g("llm", "judge", body="PASS if good. FAIL otherwise.")])
        self.assertEqual([x.name for x in scored_graders(case, "with-without")], ["judge"])
        rep = analyze(suite_of(case))
        modes = {c["mode"]: c["status"] for c in rep["cases"]}
        self.assertEqual(modes, {"ablation-none": "OK", "with-without": "JUDGE_ONLY"})

    def test_arm_both_keeps_grader_and_all_excluded_scores_all(self):
        both = g("tool_used", "nofire", tool="Skill", min=0, max=0, arm="both")
        case = Case("c", DEMO, "p", [both])
        self.assertEqual([x.name for x in scored_graders(case, "with-without")], ["nofire"])
        only = Case("c", DEMO, "p", [g("tool_used", "fired", tool="Skill")])
        self.assertEqual([x.name for x in scored_graders(only, "with-without")], ["fired"])

    def test_weak_rubric_heuristic(self):
        case = Case("c", DEMO, "p", [g("llm", "weak", body="PASS if it mentions a version."),
                                     g("llm", "strong", body="PASS if a. FAIL if b.")])
        rep = analyze(suite_of(case))
        self.assertTrue(self.status(rep, "weak")["weak_rubric"])
        self.assertFalse(self.status(rep, "strong")["weak_rubric"])

    def test_weighted_threshold(self):
        case = Case("c", DEMO, "p", [g("regex", "guard", weight=3, pattern="TODO", match="not_contains"),
                                     g("regex", "work", weight=1, pattern="def ")])
        self.assertEqual(analyze(suite_of(case), threshold=0.7)["cases"][0]["status"], "NULL_GREEN")
        self.assertEqual(analyze(suite_of(case), threshold=1.0)["cases"][0]["status"], "OK")


if __name__ == "__main__":
    unittest.main()
