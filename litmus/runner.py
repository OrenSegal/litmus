"""Evaluate cases and suites: run every assertion against every sample,
aggregate into sample-based pass-rates, and roll up to case/suite status.

Non-determinism is first-class: a case runs over N samples, each assertion
reports a pass-rate, and `flaky` flags an assertion that is neither reliably
green nor reliably red (LITMUS_SPEC.md §7).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, List, Optional

from .assertions import EvalContext, run_assertion
from .case import load_suite, runs_or_error
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


def _entry_name(index: int, entry: Any) -> str:
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
    # The case target (suite target merged with the case's own) names the model
    # a run came from when the run itself doesn't; the judge's no-self-grading
    # check reads it. `replace` keeps `warnings` shared with the caller's ctx.
    ctx = replace(ctx, target_model=(case.target or {}).get("model"))
    results: List[AssertionResult] = []
    for i, entry in enumerate(case.asserts):
        verdicts = [run_assertion(entry, run, ctx) for run in runs]
        results.append(_aggregate(_entry_name(i, entry), verdicts, threshold))
    # Case is green only if every assertion is PASS or SKIP (and at least one
    # PASSed): a SKIP proved nothing, so it neither greens nor reddens a case.
    checked = [r.status for r in results if r.status is not Status.SKIP]
    status = worst(checked) if checked else Status.SKIP
    error = ""
    # `samples: N` promises N captured runs. Fewer means the sampling the case
    # declares never happened, so a green would claim more than was checked.
    # A FAIL stays a FAIL: one failing sample is already a real failure.
    if len(runs) < case.samples and status is not Status.FAIL:
        error = (f"declared samples: {case.samples} but found {len(runs)} run(s); "
                 "capture the rest or lower `samples`")
        status = Status.INCONCLUSIVE
    return CaseResult(case.id, status, results, target=case.target, error=error)


def suite_context(suite_dir: Path, ctx: Optional[EvalContext]) -> EvalContext:
    """The caller's context (or a default one), with suite paths resolved
    against `suite_dir` unless the caller set a base directory."""
    ctx = ctx or EvalContext(base_dir=suite_dir)
    if ctx.base_dir == Path("."):
        ctx.base_dir = suite_dir
    return ctx


def evaluate_suite(suite_dir: Path, ctx: Optional[EvalContext] = None) -> SuiteResult:
    suite_dir = Path(suite_dir)
    ctx = suite_context(suite_dir, ctx)
    name, target, cases = load_suite(suite_dir)
    results: List[CaseResult] = []
    for case in cases:
        runs, error = runs_or_error(case, suite_dir)
        if error:
            results.append(CaseResult(case.id, Status.FAIL, target=case.target, error=error))
            continue
        results.append(evaluate_case(case, runs, ctx))
    return SuiteResult(name, results, target)
