"""The ratchet: diff a SuiteResult against a stored baseline and decide pass/fail.

A *regression* is the only thing that breaks the build:

- a case that was green and is now not;
- an assertion whose pass-rate dropped past tolerance (drift) on a green case;
- an assertion that PASSed in the baseline and FAILs now, even when the case
  was already not green (a judge case gated without `--judge` is INCONCLUSIVE,
  and its deterministic assertions must still be gated);
- a case in the baseline that is missing from the current run (deleting a red
  case must not be a way to turn the gate green).

Fixes and brand-new green cases never fail a gate. `bless` writes a new
baseline but refuses to enshrine a live deterministic failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .case import SuiteError
from .models import CaseResult, Status, SuiteResult


@dataclass
class GateReport:
    regressions: List[str] = field(default_factory=list)   # case was green, now not / drifted
    new_failing: List[str] = field(default_factory=list)   # new case, not green
    fixes: List[str] = field(default_factory=list)         # was not green, now green
    still_red: List[str] = field(default_factory=list)     # not green in both
    new_green: List[str] = field(default_factory=list)     # new case, green
    removed: List[str] = field(default_factory=list)       # in the baseline, gone now

    @property
    def ok(self) -> bool:
        return not self.regressions and not self.new_failing and not self.removed


def load_baseline(path: Path) -> Dict[str, Any]:
    """Read a baseline written by `bless`, refusing anything else.

    Raises SuiteError (CLI exit 2) when the file is not JSON or has no `cases`
    object, so a mistyped `--baseline` path is never read as an empty baseline.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SuiteError(f"{path}: not a litmus baseline (invalid JSON: {exc.msg})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("cases"), dict):
        raise SuiteError(f"{path}: not a litmus baseline (no `cases` object); write one with `litmus bless`")
    for cid, entry in doc["cases"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("status"), str):
            raise SuiteError(f"{path}: not a litmus baseline (case {cid!r} has no status)")
    return doc


def baseline_warnings(current: SuiteResult, baseline: Dict[str, Any], judge: Optional[str]) -> List[str]:
    """Mismatches that make a gate comparison suspect without failing it."""
    out: List[str] = []
    name = baseline.get("name")
    if name is not None and name != current.name:
        out.append(f"baseline is for suite {name!r}, not {current.name!r}")
    meta = baseline.get("litmus")
    if isinstance(meta, dict) and "judge" in meta and meta.get("judge") != judge:
        out.append(
            f"baseline was blessed with judge {meta.get('judge')!r} but this gate runs with "
            f"{judge!r}; judge assertions are not comparable across that change")
    return out


def _newly_failing(case: CaseResult, base: Dict[str, Any]) -> List[str]:
    base_asserts = base.get("assertions", {})
    if not isinstance(base_asserts, dict):
        return []
    out = []
    for a in case.assertions:
        b = base_asserts.get(a.name)
        if isinstance(b, dict) and b.get("status") == Status.PASS.value and a.status is Status.FAIL:
            out.append(f"{case.id} ({a.name} PASS->FAIL)")
    return out


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
            newly = _newly_failing(case, base)
            if newly:
                report.regressions.extend(newly)
            elif case.status is Status.FAIL and base.get("status") != Status.FAIL.value:
                report.regressions.append(f"{case.id} ({base.get('status')}->FAIL)")
            else:
                report.still_red.append(case.id)
        elif base_green and cur_green:
            # both green at case level — still catch per-assertion pass-rate drift
            base_asserts = base.get("assertions", {})
            for a in case.assertions:
                b = base_asserts.get(a.name)
                if b is not None and b.get("pass_rate", 1.0) - a.pass_rate > drift_tol:
                    report.regressions.append(f"{case.id} ({a.name} drift {b['pass_rate']:.2f}->{a.pass_rate:.2f})")
    seen = {c.id for c in current.cases}
    report.removed = sorted(cid for cid in base_cases if cid not in seen)
    return report


def can_bless(current: SuiteResult) -> Tuple[bool, str]:
    """Refuse to bless a baseline that contains a live failure — you can't
    paper over a broken citation by snapshotting it green."""
    failing = [c.id for c in current.cases if c.status is Status.FAIL]
    if failing:
        return False, f"refusing to bless: {len(failing)} case(s) failing ({', '.join(failing)}). Fix them or pass --force."
    return True, "ok"


def write_baseline(current: SuiteResult, path: Path, judge: Optional[str] = None) -> None:
    """Write the baseline, stamped with the Litmus version and judge model it
    was blessed under so a later gate can warn when those change."""
    doc = current.to_baseline()
    doc["litmus"] = {"version": __version__, "judge": judge}
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
