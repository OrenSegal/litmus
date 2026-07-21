"""Litmus engine tests — pure, offline, no model, no network, no API key.

The grounding assertions use a DictFetcher so even `resolves`/`grounded` run
with no network. This file is the proof that the graded core is deterministic.
"""

from __future__ import annotations

import unittest

from litmus.assertions import EvalContext, run_assertion
from litmus.fetch import DictFetcher, FetchResult, grounding_ratio
from litmus.jsonpath import exists, resolve
from litmus.models import AgentRun, Status, Case, ToolCall
from litmus.runner import evaluate_case
from litmus.gate import diff, can_bless
from litmus.models import SuiteResult, CaseResult, AssertionResult
from litmus import schema as schema_mod


def run(output=None, tools=None, **kw) -> AgentRun:
    return AgentRun(
        output=output,
        tool_calls=[ToolCall(t) if isinstance(t, str) else ToolCall(**t) for t in (tools or [])],
        **kw,
    )


def verdict(entry, agent_run, ctx=None):
    return run_assertion(entry, agent_run, ctx or EvalContext())


# --------------------------------------------------------------------------- #
class TestJsonPath(unittest.TestCase):
    DATA = {
        "individuals": [{"type": "Individual", "source_url": "u1", "evidence": "alpha"}],
        "segments": [{"name": "s", "opener": "hi"}, {"name": "t"}],
    }

    def test_index_and_field(self):
        self.assertEqual(resolve("$.individuals[0].type", self.DATA), ["Individual"])

    def test_wildcard(self):
        self.assertEqual(resolve("$.segments[*].name", self.DATA), ["s", "t"])

    def test_wildcard_missing_field_skipped(self):
        # only one segment has an opener
        self.assertEqual(resolve("$.segments[*].opener", self.DATA), ["hi"])

    def test_recursive_descent(self):
        self.assertEqual(set(resolve("$..source_url", self.DATA)), {"u1"})

    def test_exists(self):
        self.assertTrue(exists("$.segments[*].opener", self.DATA))
        self.assertFalse(exists("$.individuals[*].opener", self.DATA))

    def test_negative_index(self):
        self.assertEqual(resolve("$.segments[-1].name", self.DATA), ["t"])

    def test_bad_path_raises(self):
        with self.assertRaises(ValueError):
            resolve("individuals", self.DATA)


class TestSchema(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["type"],
        "properties": {"type": {"type": "string", "enum": ["Individual", "Segment", "Company"]}},
    }

    def test_valid(self):
        self.assertEqual(schema_mod.validate({"type": "Segment"}, self.SCHEMA), [])

    def test_missing_required(self):
        errs = schema_mod.validate({}, self.SCHEMA)
        self.assertTrue(any("required" in e for e in errs))

    def test_enum_violation(self):
        errs = schema_mod.validate({"type": "Robot"}, self.SCHEMA)
        self.assertTrue(any("enum" in e for e in errs))

    def test_bool_not_number(self):
        errs = schema_mod.validate(True, {"type": "number"})
        self.assertTrue(errs)


class TestToolAssertions(unittest.TestCase):
    def test_must_run_pass(self):
        v = verdict({"must_run": "finalize.py"}, run(tools=["finalize.py"]))
        self.assertIs(v.status, Status.PASS)

    def test_must_run_fail(self):
        v = verdict({"must_run": "finalize.py"}, run(tools=["generate_report.py"]))
        self.assertIs(v.status, Status.FAIL)

    def test_must_run_args_subset(self):
        r = run(tools=[{"name": "fetch", "input": {"url": "x", "timeout": 10}}])
        self.assertIs(verdict({"must_run": {"tool": "fetch", "args": {"url": "x"}}}, r).status, Status.PASS)
        self.assertIs(verdict({"must_run": {"tool": "fetch", "args": {"url": "y"}}}, r).status, Status.FAIL)

    def test_ordering(self):
        r = run(tools=["a", "b"])
        self.assertIs(verdict({"ordering": {"first": "a", "then": "b"}}, r).status, Status.PASS)
        self.assertIs(verdict({"ordering": {"first": "b", "then": "a"}}, r).status, Status.FAIL)

    def test_must_not_tool(self):
        self.assertIs(verdict({"must_not": {"tool": "rm"}}, run(tools=["rm"])).status, Status.FAIL)
        self.assertIs(verdict({"must_not": {"tool": "rm"}}, run(tools=["ls"])).status, Status.PASS)

    def test_must_not_field(self):
        r = run(output={"segments": [{"opener": "hi"}]})
        self.assertIs(verdict({"must_not": {"field": "$.segments[*].opener"}}, r).status, Status.FAIL)
        r2 = run(output={"segments": [{"name": "s"}]})
        self.assertIs(verdict({"must_not": {"field": "$.segments[*].opener"}}, r2).status, Status.PASS)

    def test_must_not_phrase(self):
        r = run(final_text="As an AI language model I cannot")
        self.assertIs(verdict({"must_not": {"phrase": "as an ai language model"}}, r).status, Status.FAIL)


class TestOutputAssertions(unittest.TestCase):
    def test_schema_assertion(self):
        r = run(output={"type": "Segment"})
        sch = {"type": "object", "required": ["type"]}
        self.assertIs(verdict({"schema": {"path": "$", "schema": sch}}, r).status, Status.PASS)

    def test_equals(self):
        r = run(output={"individuals": [{"type": "Individual"}]})
        self.assertIs(verdict({"equals": {"path": "$.individuals[0].type", "value": "Individual"}}, r).status, Status.PASS)
        self.assertIs(verdict({"equals": {"path": "$.individuals[0].type", "value": "Segment"}}, r).status, Status.FAIL)

    def test_equals_absent_fails(self):
        self.assertIs(verdict({"equals": {"path": "$.nope", "value": 1}}, run(output={})).status, Status.FAIL)

    def test_contains_and_matches(self):
        r = run(output={"msg": ["hello world"]})
        self.assertIs(verdict({"contains": {"path": "$.msg[*]", "value": "world"}}, r).status, Status.PASS)
        self.assertIs(verdict({"matches": {"path": "$.msg[*]", "pattern": r"^hello"}}, r).status, Status.PASS)

    def test_count(self):
        r = run(output={"individuals": [1, 2, 3]})
        self.assertIs(verdict({"count": {"path": "$.individuals[*]", "op": ">=", "value": 3}}, r).status, Status.PASS)
        self.assertIs(verdict({"count": {"path": "$.individuals[*]", "op": "<", "value": 3}}, r).status, Status.FAIL)

    def test_budget(self):
        self.assertIs(verdict({"budget": {"latency_ms": 5000}}, run(latency_ms=4000)).status, Status.PASS)
        self.assertIs(verdict({"budget": {"latency_ms": 5000}}, run(latency_ms=6000)).status, Status.FAIL)
        # missing telemetry can't be verified -> INCONCLUSIVE, never PASS
        self.assertIs(verdict({"budget": {"latency_ms": 5000}}, run()).status, Status.INCONCLUSIVE)


class TestGrounding(unittest.TestCase):
    def test_grounding_ratio_page_length_invariant(self):
        page = "lorem ipsum " * 5000 + "the maintainer said fixtures leak memory"
        self.assertGreater(grounding_ratio("fixtures leak memory", page), 0.5)

    def test_resolves_offline(self):
        r = run(output={"individuals": [{"source_url": "https://ok.com"}]})
        ctx = EvalContext(fetcher=DictFetcher({"https://ok.com": "live page"}))
        self.assertIs(verdict({"resolves": {"path": "$..source_url"}}, r, ctx).status, Status.PASS)

    def test_resolves_dead_link_fails(self):
        r = run(output={"individuals": [{"source_url": "https://dead.com"}]})
        ctx = EvalContext(fetcher=DictFetcher({}))  # 404
        self.assertIs(verdict({"resolves": {"path": "$..source_url"}}, r, ctx).status, Status.FAIL)

    def test_resolves_bot_walled_inconclusive(self):
        r = run(output={"individuals": [{"source_url": "https://reddit.com/r/x"}]})
        ctx = EvalContext(fetcher=DictFetcher({"https://reddit.com/r/x": FetchResult(403, "", bot_walled=True)}))
        self.assertIs(verdict({"resolves": {"path": "$..source_url"}}, r, ctx).status, Status.INCONCLUSIVE)

    def test_grounded_pass_and_fail(self):
        r = run(output={"individuals": [{"evidence": "fixtures leak memory", "source_url": "https://p.com"}]})
        good = EvalContext(fetcher=DictFetcher({"https://p.com": "the maintainer said fixtures leak memory in CI"}))
        bad = EvalContext(fetcher=DictFetcher({"https://p.com": "completely unrelated cooking blog"}))
        entry = {"grounded": {"claim": "$..evidence", "source": "$..source_url"}}
        self.assertIs(verdict(entry, r, good).status, Status.PASS)
        self.assertIs(verdict(entry, r, bad).status, Status.FAIL)


class TestJudgeGuardrail(unittest.TestCase):
    def test_no_judge_is_inconclusive_never_pass(self):
        v = verdict({"judge": {"rubric": "opener is personalized"}}, run(output={}))
        self.assertIs(v.status, Status.INCONCLUSIVE)


class TestRunnerAggregation(unittest.TestCase):
    def test_flaky_detection(self):
        case = Case(id="c", asserts=[{"must_run": "finalize.py"}])
        runs = [run(tools=["finalize.py"]), run(tools=[]), run(tools=["finalize.py"])]
        res = evaluate_case(case, runs, EvalContext(), threshold=1.0)
        a = res.assertions[0]
        self.assertAlmostEqual(a.pass_rate, 2 / 3)
        self.assertTrue(a.flaky)
        self.assertIs(res.status, Status.FAIL)  # below threshold 1.0

    def test_all_pass_green(self):
        case = Case(id="c", asserts=[{"must_run": "finalize.py"}, {"equals": {"path": "$.x", "value": 1}}])
        runs = [run(output={"x": 1}, tools=["finalize.py"])]
        res = evaluate_case(case, runs, EvalContext())
        self.assertIs(res.status, Status.PASS)

    def test_inconclusive_does_not_read_as_green(self):
        case = Case(id="c", asserts=[{"judge": {"rubric": "vibes"}}])
        res = evaluate_case(case, [run(output={})], EvalContext())
        self.assertIs(res.status, Status.INCONCLUSIVE)
        self.assertFalse(res.status.is_green)


class TestGate(unittest.TestCase):
    def _suite(self, statuses):
        cases = [CaseResult(id=cid, status=st) for cid, st in statuses.items()]
        return SuiteResult("s", cases)

    def test_regression_detected(self):
        cur = self._suite({"a": Status.FAIL})
        base = {"cases": {"a": {"status": "PASS", "assertions": {}}}}
        report = diff(cur, base)
        self.assertEqual(report.regressions, ["a"])
        self.assertFalse(report.ok)

    def test_fix_is_not_regression(self):
        cur = self._suite({"a": Status.PASS})
        base = {"cases": {"a": {"status": "FAIL", "assertions": {}}}}
        report = diff(cur, base)
        self.assertEqual(report.fixes, ["a"])
        self.assertTrue(report.ok)

    def test_new_failing_breaks_gate(self):
        cur = self._suite({"b": Status.FAIL})
        report = diff(cur, {"cases": {}})
        self.assertEqual(report.new_failing, ["b"])
        self.assertFalse(report.ok)

    def test_pass_rate_drift_is_regression(self):
        case = CaseResult(
            id="a", status=Status.PASS,
            assertions=[AssertionResult("00:judge", Status.PASS, pass_rate=0.7, threshold=0.6, samples=10)],
        )
        cur = SuiteResult("s", [case])
        base = {"cases": {"a": {"status": "PASS", "assertions": {"00:judge": {"status": "PASS", "pass_rate": 0.95}}}}}
        report = diff(cur, base, drift_tol=0.1)
        self.assertTrue(report.regressions)
        self.assertFalse(report.ok)

    def test_cannot_bless_failing(self):
        ok, _ = can_bless(self._suite({"a": Status.FAIL}))
        self.assertFalse(ok)
        ok2, _ = can_bless(self._suite({"a": Status.PASS}))
        self.assertTrue(ok2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
