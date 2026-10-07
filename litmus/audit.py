"""Audit results you already have: no new runs, no cost.

A two-arm `claude plugin eval` run (the default `--ablation with-without`)
already contains one free mutant: the without-arm is the plugin deleted
entirely. `litmus audit` reads an existing aggregate-result.json and reports:

- PLUGIN_REMOVAL_SURVIVED: a case that scored at or above the suite threshold
  with no plugin loaded. Its graders cannot tell the plugin from no plugin.
  Expected for a negative case (a scored "Skill was not invoked" check, or
  every scored grader is an absence check); such cases are labelled `negative`.
- NEVER_FAILED: a scored grader that passed in every run of both arms. This is
  an observation, not a proof: it may be a grader that cannot fail, or just an
  easy one. Graders with `scored: false` (plugin-fired indicators) are listed
  separately and never flagged.
"""

from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["audit_result"]

EPS = 1e-9


def _is_absence(g: Dict[str, Any]) -> bool:
    cfg = g.get("config") or {}
    t = g.get("type")
    if t == "regex":
        return str(cfg.get("match") or "contains") in ("not_contains", "count:0")
    if t == "tool_used":
        return cfg.get("max") is not None and int(cfg["max"]) == 0
    if t == "file_exists":
        return cfg.get("exists") is False
    return False


def audit_result(doc: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    threshold = float((doc.get("suite") or {}).get("threshold", 1.0) or 1.0)
    ablation = (doc.get("suite") or {}).get("ablation")
    cases_out: List[Dict[str, Any]] = []
    for c in doc.get("cases", []):
        agg = c.get("aggregates") or {}
        arms = c.get("arms") or {}
        with_runs, without_runs = arms.get("with") or [], arms.get("without") or []
        defs = {g.get("name"): g for g in c.get("graders") or []}
        tally: Dict[str, Dict[str, int]] = {}
        unscored: set = set()
        for arm, runs in (("with", with_runs), ("without", without_runs)):
            for r in runs:
                for g in r.get("graders") or []:
                    if g.get("scored") is False:
                        unscored.add(g.get("name"))
                        continue
                    t = tally.setdefault(g.get("name"), {"with_pass": 0, "with_n": 0, "without_pass": 0, "without_n": 0})
                    t[f"{arm}_n"] += 1
                    t[f"{arm}_pass"] += 1 if g.get("passed") else 0
        scored_defs = [defs[n] for n in tally if n in defs]
        # A negative case ("must not fire") is expected to pass with no plugin.
        no_fire = any(g.get("type") == "tool_used" and (g.get("config") or {}).get("tool") == "Skill"
                      and _is_absence(g) for g in scored_defs)
        negative = bool(scored_defs) and (no_fire or all(_is_absence(g) for g in scored_defs))
        findings = []
        sw = agg.get("scoreWithout")
        if without_runs and sw is not None and float(sw) >= threshold - EPS:
            findings.append({
                "kind": "PLUGIN_REMOVAL_SURVIVED",
                "detail": f"scored {float(sw):.2f} with no plugin loaded (threshold {threshold:.2f})"
                          + ("; negative case" if negative else ""),
                "expected": negative,
            })
        for name, t in tally.items():
            n = t["with_n"] + t["without_n"]
            if n and t["with_pass"] + t["without_pass"] == n and t["without_n"]:
                findings.append({
                    "kind": "NEVER_FAILED",
                    "grader": name,
                    "detail": f"passed {n}/{n} runs across both arms"
                              + (" (absence check)" if name in defs and _is_absence(defs[name]) else ""),
                    "expected": bool(name in defs and _is_absence(defs[name])),
                })
        cases_out.append({
            "case": c.get("name"),
            "score": agg.get("score"),
            "score_without": sw,
            "delta": agg.get("delta"),
            "negative": negative,
            "indicators": sorted(n for n in unscored if n),
            "findings": findings,
        })
    unexpected = [f for c in cases_out for f in c["findings"] if not f["expected"]]
    return {
        "source": source,
        "claude_version": doc.get("claudeVersion"),
        "started_at": doc.get("startedAt"),
        "ablation": ablation,
        "threshold": threshold,
        "partial": bool(doc.get("partial")),
        "two_arm": any((c.get("arms") or {}).get("without") for c in doc.get("cases", [])),
        "cases": cases_out,
        "counts": {
            "cases": len(cases_out),
            "plugin_removal_survived": sum(1 for c in cases_out for f in c["findings"]
                                           if f["kind"] == "PLUGIN_REMOVAL_SURVIVED" and not f["expected"]),
            "never_failed": sum(1 for c in cases_out for f in c["findings"]
                                if f["kind"] == "NEVER_FAILED" and not f["expected"]),
            "unexpected_findings": len(unexpected),
        },
    }
