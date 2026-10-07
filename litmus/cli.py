"""litmus command line.

    litmus mutate <suite>       vacuity probes + mutation run (or --dry-run)
    litmus vacuity <suite>      only the offline grader checks, free
    litmus audit <result.json>  free mutant hidden in an existing two-arm run
    litmus operators            list mutation operators

Exit codes: 0 pass, 1 the eval suite failed litmus's bar (vacuous grader,
null-green case, unexpected audit finding, or mutation score below
--min-score), 2 litmus could not evaluate (bad suite, untrusted or non-green
baseline, runner missing).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .adapters import ADAPTERS, ReplayRunner
from .adapters.claude_plugin_eval import SuiteError
from .audit import audit_result
from .engine import MutateOptions, mutate
from .mutants import ManifestError
from .operators import DESCRIPTIONS, OPERATORS
from .report import html_report, text_audit, text_mutation, text_vacuity
from .vacuity import analyze, failing

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def _err(msg: str) -> int:
    print(f"litmus: error: {msg}", file=sys.stderr)
    return EXIT_ERROR


def _adapter(args: argparse.Namespace, runner=None):  # type: ignore[no-untyped-def]
    cls = ADAPTERS[args.adapter]
    return cls(runner, eval_dir=getattr(args, "eval_dir", None), runs=getattr(args, "runs", 1),
               threshold=args.threshold, model=getattr(args, "model", None),
               judge_model=getattr(args, "judge_model", None), allow_tools=getattr(args, "allow_tools", None),
               scaffold=getattr(args, "scaffold", False), case_glob=getattr(args, "case", None),
               max_cost_usd=None, files_glob=getattr(args, "files", None))


def cmd_operators(args: argparse.Namespace) -> int:
    for name in OPERATORS:
        print(f"{name:<20} {DESCRIPTIONS[name]}")
    return EXIT_OK


def cmd_vacuity(args: argparse.Namespace) -> int:
    try:
        suite = _adapter(args).load_suite(Path(args.suite))
    except (SuiteError, ValueError) as exc:
        return _err(str(exc))
    rep = analyze(suite, args.threshold)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print("\n".join(text_vacuity(rep)))
    return EXIT_FAIL if failing(rep) else EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    worst = EXIT_OK
    reports = []
    for f in args.results:
        p = Path(f)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _err(f"{p}: {exc}")
        if doc.get("schemaVersion") != 1:
            return _err(f"{p}: not a claude plugin eval aggregate-result.json (schemaVersion 1)")
        a = audit_result(doc, str(p))
        reports.append(a)
        if a["counts"]["unexpected_findings"]:
            worst = EXIT_FAIL
    if args.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    else:
        for a in reports:
            print("\n".join(text_audit(a)))
    return worst


def cmd_mutate(args: argparse.Namespace) -> int:
    ops = args.operators.split(",") if args.operators else list(OPERATORS)
    unknown = [o for o in ops if o not in OPERATORS]
    if unknown:
        return _err(f"unknown operator(s): {', '.join(unknown)} (see `litmus operators`)")
    runner = ReplayRunner(Path(args.replay_results)) if args.replay_results else None
    if not args.dry_run and runner is None and not args.yes:
        return _err("a real mutation run calls `claude plugin eval` once per mutant and spends model credit. "
                    "Run with --dry-run first to see the mutants and the estimate, then pass --yes.")
    adapter = _adapter(args, runner)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(".litmus") / stamp
    opts = MutateOptions(operators=ops, max_mutants=args.max_mutants or None, max_sites=args.max_sites,
                         manifest=Path(args.mutants) if args.mutants else None, threshold=args.threshold,
                         budget_usd=args.max_cost_usd, dry_run=args.dry_run, keep_workdirs=args.keep,
                         runs=args.runs)
    log = (lambda s: None) if args.quiet else (lambda s: print(s, file=sys.stderr))
    try:
        rep = mutate(adapter, Path(args.suite), out, opts, log)
    except (SuiteError, ManifestError, ValueError) as exc:
        return _err(str(exc))
    rep_path = out / "report.json"
    rep_path.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "report.html").write_text(html_report(rep), encoding="utf-8")
    print("\n".join(text_mutation(rep)))
    print(f"report: {rep_path} and {out / 'report.html'}")

    vac_fail = failing(rep["vacuity"]) and not args.allow_vacuous
    if rep["dry_run"]:
        code = EXIT_FAIL if vac_fail else EXIT_OK
    else:
        b = rep["baseline"] or {}
        if not b.get("ok") or not b.get("green_cases"):
            print("litmus: the baseline must run cleanly with at least one green case before mutants mean anything",
                  file=sys.stderr)
            code = EXIT_ERROR
        else:
            score = rep["score"]["mutation_score"]
            low = score is None or score < args.min_score - 1e-9
            code = EXIT_FAIL if (vac_fail or low) else EXIT_OK
    rep["exit_code"] = code
    rep_path.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return code


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("suite", help="plugin directory (holds .claude-plugin/plugin.json and evals/)")
    p.add_argument("--adapter", default="claude-plugin-eval", choices=sorted(ADAPTERS))
    p.add_argument("--eval-dir", help="eval directory below the plugin (default: manifest value, else evals)")
    p.add_argument("--threshold", type=float, default=1.0, help="case pass threshold, as in claude plugin eval")
    p.add_argument("--case", help="only cases whose name matches this glob")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="litmus", description="Mutation testing for LLM and agent eval suites.")
    ap.add_argument("--version", action="version", version=f"litmus {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mutate", help="break the subject on purpose and check the evals notice")
    _common(m)
    m.add_argument("--operators", help="comma-separated operator names (default: all)")
    m.add_argument("--max-mutants", type=int, default=20, help="cap, spread across operators (0 = no cap)")
    m.add_argument("--max-sites", type=int, default=5, help="max sites per operator per file")
    m.add_argument("--files", help="only mutate subject files matching this glob, e.g. 'skills/cited/*'")
    m.add_argument("--mutants", help="replay a recorded mutants.json instead of generating")
    m.add_argument("--runs", type=int, default=1, help="runs per case per mutant (passed to --runs)")
    m.add_argument("--min-score", type=float, default=0.5, help="exit 1 below this mutation score")
    m.add_argument("--max-cost-usd", type=float, help="stop launching mutants past this total spend")
    m.add_argument("--model", help="model for the agent under test")
    m.add_argument("--judge-model", help="judge for llm graders")
    m.add_argument("--allow-tools", nargs="+", help="passed to claude plugin eval --allow-tools")
    m.add_argument("--scaffold", action="store_true", help="passed through: run case scaffold scripts")
    m.add_argument("--dry-run", action="store_true", help="list mutants, probes and the estimate; run nothing")
    m.add_argument("--yes", action="store_true", help="confirm a real (paid) run")
    m.add_argument("--replay-results", help="directory of recorded result JSON per label (offline demo/tests)")
    m.add_argument("--out", help="output directory (default .litmus/<timestamp>)")
    m.add_argument("--keep", action="store_true", help="keep mutant working copies")
    m.add_argument("--allow-vacuous", action="store_true", help="do not fail on vacuity findings")
    m.add_argument("--quiet", action="store_true")
    m.set_defaults(fn=cmd_mutate)

    v = sub.add_parser("vacuity", help="offline: graders that cannot fail, cases a do-nothing run passes")
    _common(v)
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_vacuity)

    a = sub.add_parser("audit", help="offline: read existing aggregate-result.json files")
    a.add_argument("results", nargs="+")
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_audit)

    o = sub.add_parser("operators", help="list mutation operators")
    o.set_defaults(fn=cmd_operators)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
