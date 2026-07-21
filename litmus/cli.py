"""`litmus` command-line entry point.

    litmus run    <suite>                     # evaluate, print red/green, exit 1 on any FAIL
    litmus gate   <suite> --baseline <file>   # diff vs baseline, exit 1 on regressions
    litmus bless  <suite> [--out <file>]      # snapshot current result as the baseline
    litmus version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .assertions import EvalContext
from .gate import can_bless, diff, load_baseline, write_baseline
from .models import Status
from .report import render_gate, render_suite
from .runner import evaluate_suite


def _run(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    ctx = EvalContext(base_dir=suite_dir, timeout=args.timeout)
    result = evaluate_suite(suite_dir, ctx)
    print(render_suite(result, verbose=not args.quiet))
    return 1 if any(c.status is Status.FAIL for c in result.cases) else 0


def _gate(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    ctx = EvalContext(base_dir=suite_dir, timeout=args.timeout)
    result = evaluate_suite(suite_dir, ctx)
    baseline_path = Path(args.baseline) if args.baseline else suite_dir / "baseline.json"
    if not baseline_path.exists():
        print(f"no baseline at {baseline_path} — run `litmus bless {args.suite}` first", file=sys.stderr)
        return 2
    report = diff(result, load_baseline(baseline_path), drift_tol=args.drift_tol)
    print(render_suite(result, verbose=not args.quiet))
    print()
    print(render_gate(report))
    return 0 if report.ok else 1


def _bless(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    ctx = EvalContext(base_dir=suite_dir, timeout=args.timeout)
    result = evaluate_suite(suite_dir, ctx)
    ok, msg = can_bless(result)
    if not ok and not args.force:
        print(msg, file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else suite_dir / "baseline.json"
    write_baseline(result, out)
    print(f"blessed baseline → {out}  ({sum(1 for c in result.cases if c.status is Status.PASS)}/{len(result.cases)} green)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="litmus", description="Red/green CI for prompt-ware.")
    parser.add_argument("--version", action="version", version=f"litmus {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("suite", help="path to a suite directory")
    common.add_argument("--timeout", type=int, default=10, help="per-URL fetch timeout (s)")
    common.add_argument("--quiet", action="store_true", help="case-level output only")

    p_run = sub.add_parser("run", parents=[common], help="evaluate a suite")
    p_run.set_defaults(func=_run)

    p_gate = sub.add_parser("gate", parents=[common], help="diff vs baseline; fail on regressions")
    p_gate.add_argument("--baseline", help="baseline JSON (default: <suite>/baseline.json)")
    p_gate.add_argument("--drift-tol", type=float, default=0.10, help="allowed pass-rate drop before it's a regression")
    p_gate.set_defaults(func=_gate)

    p_bless = sub.add_parser("bless", parents=[common], help="snapshot current result as baseline")
    p_bless.add_argument("--out", help="output baseline path (default: <suite>/baseline.json)")
    p_bless.add_argument("--force", action="store_true", help="bless even with failing cases")
    p_bless.set_defaults(func=_bless)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
