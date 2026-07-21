"""Terminal reporting — red/green tables, honest about INCONCLUSIVE and flaky.

Colour is opt-out via NO_COLOR (https://no-color.org). Every failure line
carries its evidence so a red is explainable, never just a score.
"""

from __future__ import annotations

import os
import sys

from .gate import GateReport
from .models import Status, SuiteResult

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


def _tag(status: Status) -> str:
    label = _GLYPH[status]
    if _use_color():
        return f"{_COLORS[status]}{label}{_RESET}"
    return label


def render_suite(result: SuiteResult, verbose: bool = True) -> str:
    lines = [f"litmus · {result.name}" + (f"  [{result.target}]" if result.target else ""), ""]
    counts = {s: 0 for s in Status}
    for case in result.cases:
        counts[case.status] += 1
        flaky = "  ~flaky" if case.flaky else ""
        lines.append(f"  {_tag(case.status):<6}  {case.id}{flaky}")
        if case.error:
            lines.append(f"            ! {case.error}")
        if verbose:
            for a in case.assertions:
                rate = "" if a.pass_rate in (0.0, 1.0) else f"  ({a.pass_rate:.0%})"
                lines.append(f"            {_tag(a.status):<6} {a.name}{rate}")
                bad = next((v for v in a.verdicts if v.status is not Status.PASS and v.detail), None)
                if bad and a.status is not Status.PASS:
                    lines.append(f"                   → {bad.detail}")
    total = len(result.cases)
    green = counts[Status.PASS]
    summary = (
        f"\n{green}/{total} green · {counts[Status.FAIL]} failing · "
        f"{counts[Status.INCONCLUSIVE]} inconclusive · {counts[Status.SKIP]} skipped"
    )
    lines.append(summary)
    return "\n".join(lines)


def render_gate(report: GateReport) -> str:
    lines = ["litmus gate"]
    def block(label: str, items):
        if items:
            lines.append(f"  {label}:")
            lines.extend(f"    - {i}" for i in items)
    block("REGRESSIONS", report.regressions)
    block("new failing", report.new_failing)
    block("fixes", report.fixes)
    block("new green", report.new_green)
    block("still red", report.still_red)
    verdict = "PASS — no regressions" if report.ok else "FAIL — regressions present"
    if _use_color():
        color = _COLORS[Status.PASS] if report.ok else _COLORS[Status.FAIL]
        verdict = f"{color}{verdict}{_RESET}"
    lines.append("\n" + verdict)
    return "\n".join(lines)
