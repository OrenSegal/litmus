"""`litmus` command-line entry point.

    litmus run    <suite> [--html out.html]   # evaluate, print red/green, exit 1 on any FAIL
    litmus gate   <suite> --baseline <file>   # diff vs baseline, exit 1 on regressions
    litmus bless  <suite> [--out <file>]      # snapshot current result as the baseline
    litmus matrix <suite> [--models a,b]      # case x model grid across model-tagged runs
    litmus index  <suite> [<suite> ...]       # rank suites worst-first by green rate
    litmus capture "<prompt>" --out run.json  # capture a live AgentRun via the Claude CLI
    litmus calibrate <labels.jsonl>           # judge vs human labels: recall, precision, kappa
    litmus status <suite>                     # what a green proves: captured vs fixture runs
    litmus --version

Exit codes, for every command:

    0  green: nothing failed (run), no regression (gate, matrix --reference)
    1  red: a case FAILed (run), a regression (gate, matrix), bless refused
    2  could not evaluate: bad suite/case/baseline file, a path outside the
       suite, unknown --reference, a judge or capture that could not run

run, gate, bless, matrix, index and calibrate also take `--judge claude` (and optionally
`--judge-model <id>`) to grade `judge` assertions with the Claude CLI. Without
`--judge`, no judge is built, nothing is sent to a model, and every `judge`
assertion is INCONCLUSIVE. If a requested judge can't run, the command prints
the reason to stderr and exits 2. A judge never grades a run produced by its own
model (the run is INCONCLUSIVE); if a run's model is unknown it is graded and a
warning is printed to stderr once per command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__
from .assertions import EvalContext, JudgeError, JudgeFn
from .case import SuiteError
from .calibrate import CalibrationError, calibrate, fill_judge, load_samples, render_calibration, write_samples
from .gate import baseline_warnings, can_bless, diff, load_baseline, write_baseline
from .index import IndexEntry, render_index
from .judge import DEFAULT_JUDGE_MODEL, ClaudeJudge
from .matrix import evaluate_matrix, render_matrix
from .model_ids import UNKNOWN_MODEL
from .models import Status, SuiteResult
from .report import render_gate, render_suite
from .report_html import render_html
from .runner import evaluate_suite


def _build_judge(args: argparse.Namespace) -> Optional[JudgeFn]:
    """Return the judge named by --judge, or None. None keeps judge assertions
    INCONCLUSIVE and means no model is ever called."""
    name = getattr(args, "judge", None)
    if name is None:
        return None
    if name == "claude":
        ClaudeJudge.check_available()
        return ClaudeJudge(model=args.judge_model) if args.judge_model else ClaudeJudge()
    raise JudgeError(f"unknown judge {name!r}")  # argparse choices should stop this first


def _ctx(args: argparse.Namespace, suite_dir: Path) -> EvalContext:
    # One warnings list per invocation, so `index` over several suites still
    # prints each warning once.
    return EvalContext(base_dir=suite_dir, timeout=args.timeout, judge=args.judge_fn,
                       warnings=args.warnings)


def _print_warnings(args: argparse.Namespace) -> None:
    for message in getattr(args, "warnings", []):
        print(f"litmus: warning: {message}", file=sys.stderr)


def _judge_model(args: argparse.Namespace) -> Optional[str]:
    """The judge model id this invocation grades with, or None for no judge."""
    return getattr(args.judge_fn, "model", None) if args.judge_fn is not None else None


def _maybe_html(args: argparse.Namespace, result: SuiteResult) -> None:
    if getattr(args, "html", None):
        Path(args.html).write_text(render_html(result), encoding="utf-8")
        print(f"\nHTML report → {args.html}")


def _run(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    result = evaluate_suite(suite_dir, _ctx(args, suite_dir))
    print(render_suite(result, verbose=not args.quiet))
    _maybe_html(args, result)
    return 1 if any(c.status is Status.FAIL for c in result.cases) else 0


def _matrix(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    models = args.models.split(",") if args.models else None
    result = evaluate_matrix(suite_dir, _ctx(args, suite_dir), models)
    print(render_matrix(result))
    if args.reference:
        try:
            regs = result.regressions_vs(args.reference)
        except ValueError as exc:
            print(f"litmus: error: {exc}", file=sys.stderr)
            return 2
        if regs:
            print("\ncross-model regressions:")
            for r in regs:
                print(f"  - {r}")
            return 1
    return 0


def _index(args: argparse.Namespace) -> int:
    entries = []
    for suite in args.suites:
        suite_dir = Path(suite)
        result = evaluate_suite(suite_dir, _ctx(args, suite_dir))
        target = result.target or {}
        entries.append(IndexEntry.from_suite(
            target.get("skill", suite_dir.name), target.get("model", UNKNOWN_MODEL), result))
    print(render_index(entries))
    return 0


def _capture(args: argparse.Namespace) -> int:
    from .adapters.claude_code import capture

    run = capture(args.prompt, model=args.model, cwd=args.cwd)  # CaptureError -> exit 2 in main
    text = json.dumps(run.to_obj(), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"captured AgentRun → {args.out}")
    else:
        print(text)
    return 0


def _status(args: argparse.Namespace) -> int:
    from .status import render_status, suite_status

    print(render_status(suite_status(Path(args.suite))))
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    try:
        samples = load_samples(Path(args.labels))
    except CalibrationError as exc:
        print(f"litmus: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"litmus: cannot read {args.labels}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    if args.judge_fn is not None:
        try:
            fill_judge(samples, args.judge_fn, rejudge=args.rejudge, warnings=args.warnings)
        except JudgeError as exc:
            # Keep the verdicts already paid for: write what was judged so far.
            if args.out:
                write_samples(Path(args.out), samples)
                print(f"litmus: judge failed, partial labels written to {args.out}", file=sys.stderr)
            print(f"litmus: judge error: {exc}", file=sys.stderr)
            return 2
        if args.out:
            write_samples(Path(args.out), samples)
            print(f"judged labels → {args.out}", file=sys.stderr)
    elif args.out or args.rejudge:
        args.warnings.append("--out and --rejudge do nothing without --judge")
    result = calibrate(samples)
    if result.unjudged and args.judge_fn is None:
        args.warnings.append(f"{result.unjudged} row(s) have no judge verdict; pass --judge to fill them")
    print(json.dumps(result.to_json(), indent=2) if args.json else render_calibration(result))
    if args.min_kappa is not None:
        if result.kappa is None:
            print(f"\nkappa is undefined for this set, so --min-kappa {args.min_kappa} cannot pass",
                  file=sys.stderr)
            return 1
        # Tolerance: kappa 0.4 on paper can compute as 0.39999..., which would fail --min-kappa 0.4.
        if result.kappa < args.min_kappa - 1e-9:
            print(f"\nkappa {result.kappa:.3f} is below --min-kappa {args.min_kappa}", file=sys.stderr)
            return 1
    return 0


def _bounded_float(lo: float, hi: float) -> Callable[[str], float]:
    """An argparse type: a float in [lo, hi]. Also rejects nan and inf."""
    def parse(value: str) -> float:
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {value!r}")
        if not lo <= number <= hi:
            raise argparse.ArgumentTypeError(f"must be between {lo:g} and {hi:g}")
        return number
    return parse


def _gate(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    result = evaluate_suite(suite_dir, _ctx(args, suite_dir))
    baseline_path = Path(args.baseline) if args.baseline else suite_dir / "baseline.json"
    if not baseline_path.exists():
        print(f"no baseline at {baseline_path} — run `litmus bless {args.suite}` first", file=sys.stderr)
        return 2
    baseline = load_baseline(baseline_path)
    args.warnings.extend(baseline_warnings(result, baseline, _judge_model(args)))
    report = diff(result, baseline, drift_tol=args.drift_tol)
    print(render_suite(result, verbose=not args.quiet))
    print()
    print(render_gate(report))
    _maybe_html(args, result)
    return 0 if report.ok else 1


def _bless(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    result = evaluate_suite(suite_dir, _ctx(args, suite_dir))
    ok, msg = can_bless(result)
    if not ok and not args.force:
        print(msg, file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else suite_dir / "baseline.json"
    write_baseline(result, out, judge=_judge_model(args))
    print(f"blessed baseline → {out}  ({result.counts()[Status.PASS]}/{len(result.cases)} green)")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="litmus", description="Red/green regression tests for skills, prompts and tool definitions.")
    parser.add_argument("--version", action="version", version=f"litmus {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("suite", help="path to a suite directory")
    common.add_argument("--timeout", type=int, default=10, help="per-URL fetch timeout (s)")
    common.add_argument("--quiet", action="store_true", help="case-level output only")

    judging = argparse.ArgumentParser(add_help=False)
    judging.add_argument(
        "--judge", choices=["claude"], default=None,
        help="grade `judge` assertions with this judge (default: none, so they are INCONCLUSIVE)")
    judging.add_argument(
        "--judge-model", default=None,
        help=f"model id for --judge claude (default: {DEFAULT_JUDGE_MODEL})")

    p_run = sub.add_parser("run", parents=[common, judging], help="evaluate a suite")
    p_run.add_argument("--html", help="also write a self-contained HTML report here")
    p_run.set_defaults(func=_run)

    p_gate = sub.add_parser("gate", parents=[common, judging], help="diff vs baseline; fail on regressions")
    p_gate.add_argument("--baseline", help="baseline JSON (default: <suite>/baseline.json)")
    p_gate.add_argument("--drift-tol", type=_bounded_float(0.0, 1.0), default=0.10,
                        help="allowed pass-rate drop (0-1) before it's a regression")
    p_gate.add_argument("--html", help="also write a self-contained HTML report here")
    p_gate.set_defaults(func=_gate)

    p_bless = sub.add_parser("bless", parents=[common, judging], help="snapshot current result as baseline")
    p_bless.add_argument("--out", help="output baseline path (default: <suite>/baseline.json)")
    p_bless.add_argument("--force", action="store_true", help="bless even with failing cases")
    p_bless.set_defaults(func=_bless)

    p_matrix = sub.add_parser("matrix", parents=[common, judging], help="case x model grid across model-tagged runs")
    p_matrix.add_argument("--models", help="comma-separated model filter (default: all found)")
    p_matrix.add_argument("--reference", help="model to treat as baseline; exit 1 on cross-model regressions")
    p_matrix.set_defaults(func=_matrix)

    p_index = sub.add_parser("index", parents=[judging], help="rank suites worst-first by green rate")
    p_index.add_argument("suites", nargs="+", help="one or more suite directories")
    p_index.add_argument("--timeout", type=int, default=10)
    p_index.set_defaults(func=_index)

    p_cap = sub.add_parser("capture", help="capture a live AgentRun via the Claude CLI")
    p_cap.add_argument("prompt", help="the task prompt to run")
    p_cap.add_argument("--model", help="model to run (CLI default if omitted)")
    p_cap.add_argument("--cwd", help="working dir the CLI resolves skills from")
    p_cap.add_argument("--out", help="write the AgentRun JSON here (default: stdout)")
    p_cap.set_defaults(func=_capture)

    p_status = sub.add_parser("status", help="what a green proves: captured vs fixture runs, judge coverage")
    p_status.add_argument("suite", help="path to a suite directory")
    p_status.set_defaults(func=_status)

    p_cal = sub.add_parser("calibrate", parents=[judging],
                           help="measure judge agreement with human pass/fail labels")
    p_cal.add_argument("labels", help="JSONL: {id, artifact, rubric, human, judge?, model?} per line")
    p_cal.add_argument("--out", help="with --judge, write the labels plus judge verdicts here")
    p_cal.add_argument("--rejudge", action="store_true", help="with --judge, re-grade rows that already have a verdict")
    p_cal.add_argument("--min-kappa", type=_bounded_float(-1.0, 1.0), help="exit 1 if Cohen's kappa is below this")
    p_cal.add_argument("--json", action="store_true", help="print the metrics as JSON")
    p_cal.set_defaults(func=_calibrate)

    args = parser.parse_args(argv)
    if getattr(args, "judge_model", None) and not args.judge:
        parser.error("--judge-model only applies together with --judge")
    from .adapters.claude_code import CaptureError

    args.warnings = []
    try:
        args.judge_fn = _build_judge(args)
        code: int = args.func(args)
        return code
    except JudgeError as exc:
        print(f"litmus: judge error: {exc}", file=sys.stderr)
        return 2
    except CaptureError as exc:
        print(f"litmus: capture error: {exc}", file=sys.stderr)
        return 2
    except (SuiteError, OSError) as exc:
        print(f"litmus: error: {exc}", file=sys.stderr)
        return 2
    finally:
        _print_warnings(args)


if __name__ == "__main__":
    sys.exit(main())
