"""`litmus mutate`: vacuity probes, then baseline run, then one run per mutant."""

from __future__ import annotations

import datetime as _dt
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import __version__
from .adapters.base import Adapter
from .models import SuiteRun, Verdict
from .mutants import Mutant, UnsafeMutantPath, generate, load_manifest, materialize, select, stale, write_manifest
from .operators import OPERATORS
from .scoring import MutantResult, classify, green_cases, summarize
from .vacuity import analyze

__all__ = ["MutateOptions", "mutate", "REPORT_SCHEMA", "DEFAULT_RUN_COST_USD"]

REPORT_SCHEMA = "litmus.report/1"
# Mean list-price cost of one agent run in litmus's own suite (12 runs, $1.14,
# claude plugin eval 2026-10-02). Used only for the estimate before a baseline
# exists; after the baseline, its real cost per run is used.
DEFAULT_RUN_COST_USD = 0.10


class MutateOptions:
    def __init__(self, *, operators: Sequence[str] = tuple(OPERATORS), max_mutants: Optional[int] = 20,
                 max_sites: int = 5, manifest: Optional[Path] = None, threshold: float = 1.0,
                 budget_usd: Optional[float] = None, dry_run: bool = False, keep_workdirs: bool = False,
                 runs: int = 1) -> None:
        self.operators = list(operators)
        self.max_mutants = max_mutants
        self.max_sites = max_sites
        self.manifest = manifest
        self.threshold = threshold
        self.budget_usd = budget_usd
        self.dry_run = dry_run
        self.keep_workdirs = keep_workdirs
        self.runs = runs


def _run_once(adapter: Adapter, suite: Any, source: Path, mutant: Optional[Mutant], out_dir: Path, label: str,
              keep: bool) -> SuiteRun:
    work = Path(tempfile.mkdtemp(prefix="litmus-"))
    try:
        ws = materialize(source, work / suite.root.name, mutant, adapter.results_rel(suite))
        return adapter.run(ws, suite, out_dir, label)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def _safe(label: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)


def mutate(adapter: Adapter, target: Path, out_dir: Path, opts: MutateOptions,
           log: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    suite = adapter.load_suite(target)
    out_dir.mkdir(parents=True, exist_ok=True)
    vac = analyze(suite, opts.threshold)

    if opts.manifest:
        mutants = load_manifest(opts.manifest)
        source = str(opts.manifest)
    else:
        files = adapter.subject_files(suite)
        mutants = select(generate(suite.root, files, opts.operators, opts.max_sites), opts.max_mutants)
        source = "deterministic operators: " + ", ".join(opts.operators)
    write_manifest(out_dir / "mutants.json", suite.root, mutants)

    n_cases = len(suite.cases)
    est = (1 + len(mutants)) * n_cases * opts.runs * DEFAULT_RUN_COST_USD
    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "litmus_version": __version__,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "adapter": adapter.name,
        "suite": {"root": str(suite.root), "eval_dir": str(suite.eval_dir),
                  "cases": [c.name for c in suite.cases]},
        "threshold": opts.threshold,
        "runs_per_case": opts.runs,
        "command": adapter.describe_command(suite.root),
        "mutant_source": source,
        "estimate_usd": round(est, 2),
        "vacuity": vac,
        "baseline": None,
        "mutants": [],
        "score": None,
        "dry_run": opts.dry_run,
    }

    def originals(m: Mutant) -> str:
        p = suite.root / m.file
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    results: List[MutantResult] = []
    if opts.dry_run:
        for m in mutants:
            results.append(MutantResult(m.id, m.operator, m.file, m.description, None,
                                        reason="dry run", diff=m.diff(originals(m)), generator=m.generator))
        report["mutants"] = [r.to_obj() for r in results]
        report["score"] = summarize(results)
        return report

    # Every run copies from one snapshot taken now, so an edit to the plugin
    # while the run is in flight cannot reach some mutants and not others.
    snap_dir = Path(tempfile.mkdtemp(prefix="litmus-snapshot-"))
    try:
        snapshot = materialize(suite.root, snap_dir / suite.root.name, None, adapter.results_rel(suite))
        results = _run_all(adapter, suite, snapshot, mutants, out_dir, opts, report, n_cases, originals, log)
    finally:
        if not opts.keep_workdirs:
            shutil.rmtree(snap_dir, ignore_errors=True)
    report["mutants"] = [r.to_obj() for r in results]
    report["score"] = summarize(results)
    return report


def _run_all(adapter: Adapter, suite: Any, snapshot: Path, mutants: List[Mutant], out_dir: Path,
             opts: MutateOptions, report: Dict[str, Any], n_cases: int, originals: Callable[[Mutant], str],
             log: Callable[[str], None]) -> List[MutantResult]:
    results: List[MutantResult] = []
    log(f"baseline: running {n_cases} case(s) x {opts.runs} run(s) on the unmutated copy")
    base = _run_once(adapter, suite, snapshot, None, out_dir / "runs" / "baseline", "baseline", opts.keep_workdirs)
    greens = green_cases(base, opts.threshold) if base.ok else []
    report["baseline"] = {
        "ok": base.ok, "error": base.error, "cost_usd": base.cost_usd,
        "cases": {k: {"score": v.score, "error": v.error} for k, v in base.cases.items()},
        "green_cases": greens,
    }
    spent = base.cost_usd or 0.0
    per_run = (base.cost_usd / (n_cases * opts.runs)) if base.cost_usd else DEFAULT_RUN_COST_USD
    stop_all = None
    if not base.ok:
        stop_all = f"baseline run untrusted: {base.error}"
    elif not greens:
        stop_all = "no case is green on the baseline, so nothing can be killed; fix the suite first"

    for i, m in enumerate(mutants, 1):
        r = MutantResult(m.id, m.operator, m.file, m.description, None, diff=m.diff(originals(m)),
                         generator=m.generator)
        if stop_all:
            r.verdict, r.reason = Verdict.INCONCLUSIVE, stop_all
            results.append(r)
            continue
        why = stale(snapshot, m)
        if why:
            r.verdict, r.reason = Verdict.INCONCLUSIVE, f"stale mutant: {why}"
            results.append(r)
            continue
        if opts.budget_usd is not None and spent + per_run * n_cases * opts.runs > opts.budget_usd:
            r.reason = f"not run: budget ${opts.budget_usd:.2f} would be exceeded (spent ${spent:.2f})"
            results.append(r)
            continue
        log(f"[{i}/{len(mutants)}] {m.id}")
        try:
            run = _run_once(adapter, suite, snapshot, m, out_dir / "runs" / _safe(m.id), m.id, opts.keep_workdirs)
        except UnsafeMutantPath as exc:
            r.verdict, r.reason = Verdict.INCONCLUSIVE, f"unsafe mutant: {exc}"
            results.append(r)
            log(f"    {r.verdict.value}: {r.reason}")
            continue
        spent += run.cost_usd or 0.0
        verdict, killed_by, reason = classify(base, run, opts.threshold)
        r.verdict, r.killed_by, r.reason, r.cost_usd = verdict, killed_by, reason, run.cost_usd
        r.case_scores = {k: v.score for k, v in run.cases.items()}
        results.append(r)
        log(f"    {verdict.value}: {reason}")

    report["spent_usd"] = round(spent, 4)
    return results
