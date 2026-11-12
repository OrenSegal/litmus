"""How often does noise alone get a mutant reported KILLED?

A seeded simulation through the real scoring code. The suite has one case that
passes 90% of the time whatever the prompt says, and each simulated mutant is
equivalent: it changes nothing the case depends on, so every KILLED is false.

    python3 -m tests.test_false_kill_rate      # prints the table
"""

from __future__ import annotations

import random
import unittest
from typing import Dict, Tuple

from litmus.models import CaseRun, SuiteRun, Verdict
from litmus.scoring import classify, green_in_every

P_PASS, TRIALS, MUTANTS, SEED = 0.9, 2000, 10, 20261112


def _suite_run(rng: random.Random, runs: int) -> SuiteRun:
    scores = [1.0 if rng.random() < P_PASS else 0.0 for _ in range(runs)]
    return SuiteRun(ok=True, cases={"flaky": CaseRun(sum(scores) / runs, run_scores=scores)})


def false_kill_rate(runs: int, baseline_runs: int, majority: bool) -> Tuple[float, float]:
    """(share of equivalent mutants reported KILLED, share of trials where the case could kill at all)."""
    rng = random.Random(SEED + 1000 * runs + baseline_runs)
    killed = usable = 0
    for _ in range(TRIALS):
        bases = [_suite_run(rng, runs) for _ in range(baseline_runs)]
        greens = green_in_every(bases, 1.0)
        usable += bool(greens)
        for _ in range(MUTANTS):
            verdict = classify(bases[0], _suite_run(rng, runs), 1.0, greens, majority)[0]
            killed += verdict is Verdict.KILLED
    return killed / (TRIALS * MUTANTS), usable / TRIALS


def table() -> Dict[Tuple[int, str], Tuple[float, float]]:
    out = {}
    for runs in (1, 3, 5):
        out[(runs, "default")] = false_kill_rate(runs, 1, False)
        out[(runs, "repeat3+majority")] = false_kill_rate(runs, 3, True)
    return out


class TestFalseKillRate(unittest.TestCase):
    def test_more_runs_raise_false_kills_under_the_default_rule_and_lower_them_under_majority(self):
        t = table()
        d = [t[(r, "default")][0] for r in (1, 3, 5)]
        m = [t[(r, "repeat3+majority")][0] for r in (1, 3, 5)]
        self.assertLess(d[0], d[1])
        self.assertLess(d[1], d[2])
        self.assertGreater(m[0], m[1])
        self.assertGreater(m[1], m[2])
        for a, b in zip(d, m):
            self.assertLess(b, a)
        self.assertLess(m[1], 0.03)  # 3 runs, strict majority: about 2%, against about 20% by default


if __name__ == "__main__":
    print(f"one case passing {P_PASS:.0%} of runs; {TRIALS} trials x {MUTANTS} equivalent mutants; seed {SEED}")
    print("runs  rule               equivalent mutants KILLED   trials where the case was green at baseline")
    for (runs, rule), (fk, ok) in table().items():
        print(f"{runs:>4}  {rule:<17}  {fk:>10.1%}                  {ok:>6.1%}")
