"""Evaluate cases and suites: run every assertion against every sample,
aggregate into sample-based pass-rates, and roll up to case/suite status.

Non-determinism is first-class: a case runs over N samples, each assertion
reports a pass-rate, and `flaky` flags an assertion that is neither reliably
green nor reliably red (LITMUS_SPEC §7).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .assertions import EvalContext, run_assertion
from .case import load_runs, load_suite
from .models import (
    AgentRun,
    AssertionResult,
    Case,
    CaseResult,
    Status,
    SuiteResult,
    Verdict,
    worst,
)


def _entry_name(index: int, entry: dict) -> str:
    key = next(iter(entry)) if isinstance(entry, dict) and entry else "?"
    return f"{index:02d}:{key}"


def _aggregate(name: str, verdicts: List[Verdict], threshold: float) -> AssertionResult:
    statuses = [v.status for v in verdicts]
    effective = [s for s in statuses if s is not Status.SKIP]
    if not effective:
        return AssertionResult(name, Status.SKIP, 1.0, threshold, len(verdicts), verdicts)
    passes = sum(1 for s in effective if s is Status.PASS)
    pass_rate = passes / len(effective)
    if pass_rate >= threshold:
        status = Status.PASS
    elif any(s is Status.FAIL for s in effective):
        status = Status.FAIL
    else:
        status = Status.INCONCLUSIVE
    return AssertionResult(name, status, pass_rate, threshold, len(verdicts), verdicts)


def evaluate_case(
    case: Case,
    runs: List[AgentRun],
    ctx: EvalContext,
    threshold: float = 1.0,
) -> CaseResult:
    if not runs:
        return CaseResult(case.id, Status.SKIP, target=case.target, error="no samples")
    results: List[AssertionResult] = []
    for i, entry in enumerate(case.asserts):
        verdicts = [run_assertion(entry, run, ctx) for run in runs]
        results.append(_aggregate(_entry_name(i, entry), verdicts, threshold))
    # Case is green only if every assertion is PASS or SKIP.
    status = worst([r.status for r in results]) if results else Status.SKIP
    return CaseResult(case.id, status, results, target=case.target)


def evaluate_suite(suite_dir: Path, ctx: EvalContext | None = None) -> SuiteResult:
    suite_dir = Path(suite_dir)
    ctx = ctx or EvalContext(base_dir=suite_dir)
    if ctx.base_dir == Path("."):
        ctx.base_dir = suite_dir
    name, target, cases = load_suite(suite_dir)
    results: List[CaseResult] = []
    for case in cases:
        try:
            runs = load_runs(case, suite_dir)
        except FileNotFoundError as exc:
            results.append(CaseResult(case.id, Status.FAIL, target=case.target, error=str(exc)))
            continue
        results.append(evaluate_case(case, runs, ctx))
    return SuiteResult(name, results, target)
