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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import SuiteRun, Verdict

__all__ = ["MutantResult", "classify", "summarize", "green_cases"]

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


def classify(baseline: SuiteRun, mutant: SuiteRun, threshold: float) -> tuple:
    """(Verdict, killed_by, reason)."""
    if not baseline.ok:
        return Verdict.INCONCLUSIVE, [], f"baseline run untrusted: {baseline.error}"
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
        if c.score < threshold - EPS:
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
        "killed": k,
        "survived": s,
        "inconclusive": i,
        "not_run": len(results) - len(ran),
        "total_run": total,
        "decided_score": (k / (k + s)) if (k + s) else None,
        "by_operator": by_op,
    }
