"""Terminal reporting — red/green tables, honest about INCONCLUSIVE and flaky.

Colour is opt-out via NO_COLOR (https://no-color.org). Every failure line
carries its evidence so a red is explainable, never just a score.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from .gate import GateReport
from .models import AssertionResult, Status, SuiteResult

_COLORS = {
    Status.PASS: "\033[32m",          # green
    Status.FAIL: "\033[31m",          # red
    Status.INCONCLUSIVE: "\033[33m",  # yellow
    Status.SKIP: "\033[90m",          # grey
}
_RESET = "\033[0m"
_GLYPH = {Status.PASS: "PASS", Status.FAIL: "FAIL", Status.INCONCLUSIVE: "INCONC", Status.SKIP: "skip"}


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def status_tag(status: Status) -> str:
    label = _GLYPH[status]
    if _use_color():
        return f"{_COLORS[status]}{label}{_RESET}"
    return label


def summary_line(result: SuiteResult) -> str:
    counts = result.counts()
    return (f"{counts[Status.PASS]}/{len(result.cases)} green · {counts[Status.FAIL]} failing · "
            f"{counts[Status.INCONCLUSIVE]} inconclusive · {counts[Status.SKIP]} skipped")


def rate_label(a: AssertionResult) -> str:
    """The pass-rate, shown only when the samples split."""
    return "" if a.pass_rate in (0.0, 1.0) else f"({a.pass_rate:.0%})"


def first_problem(a: AssertionResult) -> Optional[str]:
    """The detail of the first non-passing sample, for an assertion that did not pass."""
    if a.status is Status.PASS:
        return None
    return next((v.detail for v in a.verdicts if v.status is not Status.PASS and v.detail), None)


def render_suite(result: SuiteResult, verbose: bool = True) -> str:
    lines = [f"litmus · {result.name}" + (f"  [{result.target}]" if result.target else ""), ""]
    for case in result.cases:
        flaky = "  ~flaky" if case.flaky else ""
        lines.append(f"  {status_tag(case.status):<6}  {case.id}{flaky}")
        if case.error:
            lines.append(f"            ! {case.error}")
        if verbose:
            for a in case.assertions:
                rate = rate_label(a)
                lines.append(f"            {status_tag(a.status):<6} {a.name}" + (f"  {rate}" if rate else ""))
                problem = first_problem(a)
                if problem:
                    lines.append(f"                   → {problem}")
    lines.append("\n" + summary_line(result))
    return "\n".join(lines)


def render_gate(report: GateReport) -> str:
    lines = ["litmus gate"]
    def block(label: str, items: List[str]) -> None:
        if items:
            lines.append(f"  {label}:")
            lines.extend(f"    - {i}" for i in items)
    block("REGRESSIONS", report.regressions)
    block("new failing", report.new_failing)
    block("removed (in baseline, missing now)", report.removed)
    block("fixes", report.fixes)
    block("new green", report.new_green)
    block("still red", report.still_red)
    verdict = "PASS — no regressions" if report.ok else "FAIL — regressions present"
    if _use_color():
        color = _COLORS[Status.PASS] if report.ok else _COLORS[Status.FAIL]
        verdict = f"{color}{verdict}{_RESET}"
    lines.append("\n" + verdict)
    return "\n".join(lines)
