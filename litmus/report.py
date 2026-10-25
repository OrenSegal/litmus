"""Render a litmus report as terminal text or a self-contained HTML page."""

from __future__ import annotations

import html
from typing import Any, Dict, List

__all__ = ["text_vacuity", "text_mutation", "text_audit", "html_report"]


def _pct(x: Any) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def text_vacuity(v: Dict[str, Any]) -> List[str]:
    c = v["counts"]
    out = [f"vacuity: {c['vacuous']} vacuous, {c['always_fails']} always-fail, {c['null_pass']} null-pass grader(s); "
           f"{c['null_green_cases']} null-green case(s), {c['judge_only_cases']} judge-only case(s)"]
    for g in v["graders"]:
        if g["status"] in ("VACUOUS", "ALWAYS_FAILS") or (g["status"] == "NULL_PASS" and not g["guard"]):
            out.append(f"  {g['status']:<13} {g['case']}/{g['grader']} ({g['type']}): {g['reason']}")
        elif g["weak_rubric"]:
            out.append(f"  {'WEAK_RUBRIC':<13} {g['case']}/{g['grader']}: rubric never says what FAILs (heuristic)")
    for cf in v["cases"]:
        if cf["status"] == "NULL_GREEN":
            greens = ", ".join(p for p, s in cf["probes"].items() if s == "GREEN")
            out.append(f"  NULL_GREEN    {cf['case']} [{cf['mode']}]: green on a do-nothing run ({greens})")
    return out


def text_mutation(r: Dict[str, Any]) -> List[str]:
    s = r["score"]
    out = text_vacuity(r["vacuity"])
    if r["dry_run"]:
        out.append(f"dry run: {len(r['mutants'])} mutant(s) would run; estimate ${r['estimate_usd']:.2f} "
                   f"({len(r['suite']['cases'])} case(s) x {r['runs_per_case']} run(s) x (1 + mutants))")
        out.append(f"each run: {r['command']}")
        for m in r["mutants"]:
            out.append(f"  {m['id']}  {m['description']}")
        return out
    b = r["baseline"] or {}
    if b:
        out.append(f"baseline: {'ok' if b.get('ok') else 'UNTRUSTED: ' + str(b.get('error'))}; "
                   f"green cases: {', '.join(b.get('green_cases') or []) or 'none'}")
    out.append(f"mutation score: {_pct(s['mutation_score'])} ({s['killed']} killed / {s['total_run']} run; "
               f"{s['survived']} survived, {s['inconclusive']} inconclusive, {s['not_run']} not run)")
    for m in r["mutants"]:
        if m["verdict"] in ("SURVIVED", "INCONCLUSIVE", "NOT_RUN"):
            out.append(f"  {m['verdict']:<12} {m['id']}: {m['description']}")
            if m["verdict"] != "SURVIVED":
                out.append(f"               {m['reason']}")
    return out


def text_audit(a: Dict[str, Any]) -> List[str]:
    c = a["counts"]
    out = [f"{a['source']}: {c['cases']} case(s), {c['plugin_removal_survived']} survived plugin removal, "
           f"{c['never_failed']} grader(s) never failed" + ("" if a["two_arm"] else " (one-arm run: no without-arm)")]
    for case in a["cases"]:
        for f in case["findings"]:
            tag = " (expected)" if f["expected"] else ""
            who = f"{case['case']}/{f['grader']}" if f.get("grader") else case["case"]
            out.append(f"  {f['kind']:<24} {who}: {f['detail']}{tag}")
    return out


_CSS = """
:root{--bg:#fbfbfa;--fg:#1b1b1a;--muted:#6a6a66;--line:#e4e3df;--card:#fff;
--kill:#1a7f37;--surv:#cf222e;--inc:#9a6700;--nr:#8b8b86}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111110;--fg:#ecebe8;--muted:#9c9b96;
--line:#2a2a28;--card:#181817;--kill:#3fb950;--surv:#f85149;--inc:#d29922;--nr:#76756f}}
:root[data-theme="dark"]{--bg:#111110;--fg:#ecebe8;--muted:#9c9b96;--line:#2a2a28;--card:#181817;
--kill:#3fb950;--surv:#f85149;--inc:#d29922;--nr:#76756f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:1.5rem;margin:0}h2{font-size:1.1rem;margin:2rem 0 .5rem}
.sub{color:var(--muted);margin:.25rem 0 1.25rem;overflow-wrap:anywhere}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.tile b{display:block;font-size:1.6rem}.tile span{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.v{font:600 11px/1 ui-monospace,monospace;padding:4px 6px;border-radius:5px;color:#fff;white-space:nowrap}
.KILLED{background:var(--kill)}.SURVIVED,.VACUOUS,.NULL_GREEN,.ALWAYS_FAILS{background:var(--surv)}
.INCONCLUSIVE,.NULL_PASS,.JUDGE_ONLY{background:var(--inc)}.NOT_RUN,.OK,.DISCRIMINATES,.UNKNOWN{background:var(--nr)}
code,pre{font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto;margin:.4rem 0}
details summary{cursor:pointer}.wrap{overflow-x:auto}.muted{color:var(--muted)}
"""


def _v(s: str) -> str:
    return f'<span class="v {html.escape(s)}">{html.escape(s)}</span>'


def html_report(r: Dict[str, Any]) -> str:
    e = html.escape
    s = r["score"]
    vac = r["vacuity"]
    p: List[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>litmus mutation report</title><style>{_CSS}</style></head><body><main>",
        "<h1>Can your eval fail?</h1>",
        f"<div class='sub'>{e(r['suite']['root'])} &middot; adapter {e(r['adapter'])} &middot; "
        f"litmus {e(r['litmus_version'])} &middot; {e(r['generated_at'])}</div>",
        "<div class='tiles'>",
        f"<div class='tile'><b>{_pct(s['mutation_score'])}</b><span>mutation score</span></div>",
        f"<div class='tile'><b>{s['killed']}</b><span>killed</span></div>",
        f"<div class='tile'><b>{s['survived']}</b><span>survived</span></div>",
        f"<div class='tile'><b>{s['inconclusive']}</b><span>inconclusive (not killed)</span></div>",
        f"<div class='tile'><b>{vac['counts']['vacuous'] + vac['counts']['null_green_cases']}</b>"
        "<span>vacuous graders + null-green cases</span></div>",
    ]
    b = r.get("baseline") or {}
    if b:
        greens = b.get("green_cases") or []
        p.append(f"<div class='tile'><b>{len(greens)} of {len(r['suite']['cases'])}</b>"
                 "<span>cases green at baseline (only these can kill)</span></div>")
    p.append("</div>")
    if b:
        p.append("<h2>Baseline (unmutated copy)</h2><div class='wrap'><table>"
                 "<tr><th>case</th><th>score</th><th>counts toward kills</th></tr>")
        if not b.get("ok"):
            p.append(f"<tr><td colspan='3'>{_v('UNTRUSTED')} {e(str(b.get('error')))}</td></tr>")
        for name, c in (b.get("cases") or {}).items():
            green = name in (b.get("green_cases") or [])
            p.append(f"<tr><td>{e(name)}</td><td>{e(str(c.get('score')))}{' ' + e(str(c['error'])) if c.get('error') else ''}"
                     f"</td><td>{'yes' if green else 'no, not green at baseline'}</td></tr>")
        p.append("</table></div>")
    if r["dry_run"]:
        p.append(f"<p class='muted'>Dry run: nothing was executed. Estimated cost ${r['estimate_usd']:.2f}.</p>")
    p.append("<h2>Graders and cases on do-nothing runs</h2><div class='wrap'><table>"
             "<tr><th>status</th><th>case / grader</th><th>type</th><th>why</th></tr>")
    for g in vac["graders"]:
        label = g["status"] + (" (guard)" if g["guard"] and g["status"] == "NULL_PASS" else "")
        p.append(f"<tr><td>{_v(g['status'])}</td><td>{e(g['case'])} / {e(g['grader'])}</td><td>{e(g['type'])}</td>"
                 f"<td>{e(label if g['guard'] else '')} {e(g['reason'])}"
                 f"{' Rubric never says what FAILs.' if g['weak_rubric'] else ''}</td></tr>")
    for cf in vac["cases"]:
        probes = ", ".join(f"{k}: {v}" for k, v in cf["probes"].items())
        p.append(f"<tr><td>{_v(cf['status'])}</td><td>{e(cf['case'])}</td><td>case [{e(cf['mode'])}]</td>"
                 f"<td>{e(probes)}</td></tr>")
    p.append("</table></div>")
    p.append("<h2>Mutants</h2><div class='wrap'><table>"
             "<tr><th>verdict</th><th>mutant</th><th>detail</th></tr>")
    for m in r["mutants"]:
        scores = ", ".join(f"{k}: {v}" for k, v in (m.get("case_scores") or {}).items())
        p.append(f"<tr><td>{_v(m['verdict'])}</td><td><code>{e(m['id'])}</code><br>{e(m['description'])}</td>"
                 f"<td>{e(m['reason'])}{('<br><span class=muted>' + e(scores) + '</span>') if scores else ''}"
                 f"<details><summary>diff</summary><pre>{e(m['diff'])}</pre></details></td></tr>")
    p.append("</table></div>")
    p.append(f"<h2>How this was run</h2><pre>{e(r['command'])}</pre>"
             f"<p class='muted'>Mutants from {e(r['mutant_source'])}. INCONCLUSIVE never counts as killed. "
             "Probe runs are synthetic and judge graders are not called on them.</p>")
    p.append("</main></body></html>")
    return "".join(p)
