"""Classify each mutant and compute the mutation score.

A mutant is KILLED only when a case that was green on the unmutated baseline
scores below the threshold on the mutant, in a run litmus can trust. Anything
litmus cannot trust is INCONCLUSIVE, and INCONCLUSIVE never counts as killed:

- the mutant run crashed, was partial, or hit an infrastructure error;
- no case was green on the baseline (there is nothing to kill);
- the mutant was recorded against a file that has since changed.

The mutation score is killed / (killed + survived + inconclusive): an
inconclusive mutant lowers the score exactly like a survivor. Mutants that
were never run (budget) are listed and excluded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .models import SuiteRun, Verdict

__all__ = ["MutantResult", "classify", "summarize", "green_cases", "green_in_every", "wilson"]

EPS = 1e-9


@dataclass
class MutantResult:
    id: str
    operator: str
    file: str
    description: str
    verdict: Optional[Verdict]  # None: not run
    reason: str = ""
    killed_by: List[str] = field(default_factory=list)
    case_scores: Dict[str, Optional[float]] = field(default_factory=dict)
    cost_usd: Optional[float] = None
    diff: str = ""
    generator: Dict[str, Any] = field(default_factory=dict)

    def to_obj(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["verdict"] = self.verdict.value if self.verdict else "NOT_RUN"
        return d


def green_cases(baseline: SuiteRun, threshold: float) -> List[str]:
    return [name for name, c in baseline.cases.items()
            if c.error is None and c.score is not None and c.score >= threshold - EPS]


def green_in_every(baselines: Sequence[SuiteRun], threshold: float) -> List[str]:
    """Cases green in every baseline repeat, in the first repeat's order."""
    if not baselines:
        return []
    rest = [set(green_cases(b, threshold)) for b in baselines[1:]]
    return [n for n in green_cases(baselines[0], threshold) if all(n in g for g in rest)]


def _red(c: Any, threshold: float, majority: bool) -> bool:
    if majority and c.run_scores:
        return 2 * sum(1 for s in c.run_scores if s < threshold - EPS) > len(c.run_scores)
    return bool(c.score < threshold - EPS)


def wilson(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """95% Wilson score interval for k of n, or None when n is 0."""
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0.0, (p + z * z / (2 * n) - half) / d), min(1.0, (p + z * z / (2 * n) + half) / d)]


def classify(baseline: SuiteRun, mutant: SuiteRun, threshold: float, greens: Optional[List[str]] = None,
             majority: bool = False) -> tuple:
    """(Verdict, killed_by, reason). `greens` overrides the baseline's own green
    cases (repeated baselines); `majority` reddens a case only when a strict
    majority of its mutant runs score below the threshold."""
    if not baseline.ok:
        return Verdict.INCONCLUSIVE, [], f"baseline run untrusted: {baseline.error}"
    if greens is None:
        greens = green_cases(baseline, threshold)
    if not greens:
        return Verdict.INCONCLUSIVE, [], "no case is green on the baseline, so nothing can be killed"
    if not mutant.ok:
        return Verdict.INCONCLUSIVE, [], f"mutant run untrusted: {mutant.error}"
    killed, unsure = [], []
    for name in greens:
        c = mutant.cases.get(name)
        if c is None or c.error is not None or c.score is None:
            unsure.append(f"{name}: {c.error if c else 'missing from mutant run'}")
            continue
        if _red(c, threshold, majority):
            killed.append(name)
    if killed:
        return Verdict.KILLED, killed, "case(s) dropped below threshold: " + ", ".join(killed)
    if unsure:
        return Verdict.INCONCLUSIVE, [], "; ".join(unsure)
    return Verdict.SURVIVED, [], "every baseline-green case stayed green"


def summarize(results: List[MutantResult]) -> Dict[str, Any]:
    ran = [r for r in results if r.verdict is not None]
    k = sum(1 for r in ran if r.verdict is Verdict.KILLED)
    s = sum(1 for r in ran if r.verdict is Verdict.SURVIVED)
    i = sum(1 for r in ran if r.verdict is Verdict.INCONCLUSIVE)
    total = k + s + i
    by_op: Dict[str, Dict[str, int]] = {}
    for r in ran:
        row = by_op.setdefault(r.operator, {"KILLED": 0, "SURVIVED": 0, "INCONCLUSIVE": 0})
        row[r.verdict.value] += 1  # type: ignore[union-attr]
    return {
        "mutation_score": (k / total) if total else None,
        "mutation_score_ci95": wilson(k, total),
        "killed": k,
        "survived": s,
        "inconclusive": i,
        "not_run": len(results) - len(ran),
        "total_run": total,
        "decided_score": (k / (k + s)) if (k + s) else None,
        "by_operator": by_op,
    }
