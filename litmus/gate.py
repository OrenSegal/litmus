"""The ratchet: diff a SuiteResult against a stored baseline and decide pass/fail.

A *regression* is the only thing that breaks the build: a case that was green
and is now not, or an assertion whose pass-rate dropped past tolerance (drift).
Fixes and brand-new green cases never fail a gate. `bless` writes a new
baseline but refuses to enshrine a live deterministic failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .models import Status, SuiteResult


@dataclass
class GateReport:
    regressions: List[str] = field(default_factory=list)   # case was green, now not / drifted
    new_failing: List[str] = field(default_factory=list)   # new case, not green
    fixes: List[str] = field(default_factory=list)         # was not green, now green
    still_red: List[str] = field(default_factory=list)     # not green in both
    new_green: List[str] = field(default_factory=list)     # new case, green

    @property
    def ok(self) -> bool:
        return not self.regressions and not self.new_failing


def load_baseline(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff(current: SuiteResult, baseline: Dict[str, Any], drift_tol: float = 0.10) -> GateReport:
    base_cases: Dict[str, Any] = baseline.get("cases", {})
    report = GateReport()
    for case in current.cases:
        cur_green = case.status is Status.PASS
        base = base_cases.get(case.id)
        if base is None:
            (report.new_green if cur_green else report.new_failing).append(case.id)
            continue
        base_green = base.get("status") == Status.PASS.value
        if base_green and not cur_green:
            report.regressions.append(case.id)
        elif not base_green and cur_green:
            report.fixes.append(case.id)
        elif not base_green and not cur_green:
            report.still_red.append(case.id)
        elif base_green and cur_green:
            # both green at case level — still catch per-assertion pass-rate drift
            base_asserts = base.get("assertions", {})
            for a in case.assertions:
                b = base_asserts.get(a.name)
                if b is not None and b.get("pass_rate", 1.0) - a.pass_rate > drift_tol:
                    report.regressions.append(f"{case.id} ({a.name} drift {b['pass_rate']:.2f}->{a.pass_rate:.2f})")
    return report


def can_bless(current: SuiteResult) -> Tuple[bool, str]:
    """Refuse to bless a baseline that contains a live failure — you can't
    paper over a broken citation by snapshotting it green."""
    failing = [c.id for c in current.cases if c.status is Status.FAIL]
    if failing:
        return False, f"refusing to bless: {len(failing)} case(s) failing ({', '.join(failing)}). Fix them or pass --force."
    return True, "ok"


def write_baseline(current: SuiteResult, path: Path) -> None:
    Path(path).write_text(json.dumps(current.to_baseline(), indent=2) + "\n", encoding="utf-8")
