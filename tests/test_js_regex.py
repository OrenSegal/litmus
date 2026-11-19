"""Grader patterns are JavaScript regexes evaluated in Python. Where the two
languages can give different answers, the grader is UNKNOWN, never PASS or
FAIL. The JavaScript facts in the comments were checked with node 22."""

from __future__ import annotations

import unittest

from litmus.graders import Outcome, ProbeRun, evaluate
from litmus.models import Grader


class TestJsRegexSemantics(unittest.TestCase):
    def test_js_classes_are_ascii_with_or_without_the_u_flag(self):
        # node: /\d/u.test("\u0663") is false, /\w/u.test("\u00e9") is false.
        for flags in ("", "u"):
            for pattern, text in ((r"\d", "\u0663"), (r"\w", "\u00e9")):
                g = Grader("g", "regex", config={"pattern": pattern, "flags": flags})
                self.assertIsNot(evaluate(g, ProbeRun(prompt="", last_message=text)).outcome, Outcome.PASS,
                                 (pattern, flags))

    def test_where_js_and_python_may_disagree_the_grader_is_unknown(self):
        # node: /\u00e9/i.test("\u00c9") is true and /\s/.test("\u00a0") is true; Python's ASCII
        # mode says no to both. Neither answer is safe to report, so: UNKNOWN.
        for pattern, flags, text in (("\u00e9", "i", "\u00c9"), (r"\s", "", "\u00a0")):
            g = Grader("g", "regex", config={"pattern": pattern, "flags": flags})
            r = evaluate(g, ProbeRun(prompt="", last_message=text))
            self.assertIs(r.outcome, Outcome.UNKNOWN, (pattern, flags))
            self.assertIn("JavaScript", r.reason)

    def test_plain_ascii_and_agreeing_non_ascii_matches_stay_decided(self):
        def out(pattern: str, text: str, flags: str = "") -> Outcome:
            return evaluate(Grader("g", "regex", config={"pattern": pattern, "flags": flags}),
                            ProbeRun(prompt="", last_message=text)).outcome

        self.assertIs(out("todo", "a TODO here", "i"), Outcome.PASS)
        self.assertIs(out("caf\u00e9", "un caf\u00e9 noir"), Outcome.PASS)  # both modes agree: decided
        self.assertIs(out(r"\d+", "r\u00e9sum\u00e9 without digits"), Outcome.FAIL)

    def test_the_sticky_flag_is_not_translated(self):
        # node: /b/y.test("ab") is false (sticky anchors at index 0); a plain search says true.
        g = Grader("g", "regex", config={"pattern": "b", "flags": "y"})
        self.assertIs(evaluate(g, ProbeRun(prompt="", last_message="ab")).outcome, Outcome.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
