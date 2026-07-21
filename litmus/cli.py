"""`litmus` command-line entry point.

    litmus run    <suite> [--html out.html]   # evaluate, print red/green, exit 1 on any FAIL
    litmus gate   <suite> --baseline <file>   # diff vs baseline, exit 1 on regressions
    litmus bless  <suite> [--out <file>]      # snapshot current result as the baseline
    litmus matrix <suite> [--models a,b]      # case x model grid across model-tagged runs
    litmus index  <suite> [<suite> ...]       # Hallucination Index leaderboard
    litmus capture "<prompt>" --out run.json  # capture a live AgentRun via the Claude CLI
    litmus version
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .assertions import EvalContext
from .gate import can_bless, diff, load_baseline, write_baseline
from .index import IndexEntry, render_index
from .matrix import evaluate_matrix, render_matrix
from .models import Status
from .report import render_gate, render_suite
from .report_html import render_html
from .runner import evaluate_suite


def _maybe_html(args: argparse.Namespace, result) -> None:
    if getattr(args, "html", None):
        Path(args.html).write_text(render_html(result), encoding="utf-8")
        print(f"\nHTML report → {args.html}")


def _run(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    ctx = EvalContext(base_dir=suite_dir, timeout=args.timeout)
    result = evaluate_suite(suite_dir, ctx)
    print(render_suite(result, verbose=not args.quiet))
    _maybe_html(args, result)
    return 1 if any(c.status is Status.FAIL for c in result.cases) else 0


def _matrix(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite)
    ctx = EvalContext(base_dir=suite_dir, timeout=args.timeout)
    models = args.models.split(",") if args.models else None
    result = evaluate_matrix(suite_dir, ctx, models)
    print(render_matrix(result))
    if args.reference:
        regs = result.regressions_vs(args.reference)
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
        result = evaluate_suite(suite_dir, EvalContext(base_dir=suite_dir, timeout=args.timeout))
        target = result.target or {}
        entries.append(IndexEntry.from_suite(
            target.get("skill", suite_dir.name), target.get("model", "default"), result))
    print(render_index(entries))
    return 0


def _capture(args: argparse.Namespace) -> int:
    from .adapters.claude_code import capture

    run = capture(args.prompt, model=args.model, cwd=args.cwd)
    payload = {
        "meta": run.meta,
        "tool_calls": [{"name": c.name, "input": c.input} for c in run.tool_calls],
        "final_text": run.final_text,
        "output": run.output,
        "cost_usd": run.cost_usd,
        "tokens": run.tokens,
        "latency_ms": run.latency_ms,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"captured AgentRun → {args.out}")
    else:
        print(text)
    return 0


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
    _maybe_html(args, result)
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
    p_run.add_argument("--html", help="also write a self-contained HTML report here")
    p_run.set_defaults(func=_run)

    p_gate = sub.add_parser("gate", parents=[common], help="diff vs baseline; fail on regressions")
    p_gate.add_argument("--baseline", help="baseline JSON (default: <suite>/baseline.json)")
    p_gate.add_argument("--drift-tol", type=float, default=0.10, help="allowed pass-rate drop before it's a regression")
    p_gate.add_argument("--html", help="also write a self-contained HTML report here")
    p_gate.set_defaults(func=_gate)

    p_bless = sub.add_parser("bless", parents=[common], help="snapshot current result as baseline")
    p_bless.add_argument("--out", help="output baseline path (default: <suite>/baseline.json)")
    p_bless.add_argument("--force", action="store_true", help="bless even with failing cases")
    p_bless.set_defaults(func=_bless)

    p_matrix = sub.add_parser("matrix", parents=[common], help="case x model grid across model-tagged runs")
    p_matrix.add_argument("--models", help="comma-separated model filter (default: all found)")
    p_matrix.add_argument("--reference", help="model to treat as baseline; exit 1 on cross-model regressions")
    p_matrix.set_defaults(func=_matrix)

    p_index = sub.add_parser("index", help="Hallucination Index across suites")
    p_index.add_argument("suites", nargs="+", help="one or more suite directories")
    p_index.add_argument("--timeout", type=int, default=10)
    p_index.set_defaults(func=_index)

    p_cap = sub.add_parser("capture", help="capture a live AgentRun via the Claude CLI")
    p_cap.add_argument("prompt", help="the task prompt to run")
    p_cap.add_argument("--model", help="model to run (CLI default if omitted)")
    p_cap.add_argument("--cwd", help="working dir the CLI resolves skills from")
    p_cap.add_argument("--out", help="write the AgentRun JSON here (default: stdout)")
    p_cap.set_defaults(func=_capture)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
