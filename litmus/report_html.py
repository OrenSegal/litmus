"""Self-contained HTML report for a SuiteResult — theme-aware, no external assets.

Pure string builder: takes a SuiteResult, returns one HTML document. Every fail
carries its evidence, so a red is explainable, never just a colour.
"""

from __future__ import annotations

import html
import json

from .models import Status, SuiteResult

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#6b6b6b;--line:#e6e6e6;
--pass:#1a7f37;--fail:#cf222e;--inc:#9a6700;--skip:#8b8b8b;--card:#fafafa}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--fg:#eaeaea;--muted:#9a9a9a;
--line:#262626;--pass:#3fb950;--fail:#f85149;--inc:#d29922;--skip:#6e6e6e;--card:#141414}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:2rem;max-width:900px;margin:auto}
h1{font-size:1.4rem;margin:0 0 .25rem}.sub{color:var(--muted);margin-bottom:1.5rem}
.case{border:1px solid var(--line);border-radius:10px;margin:.75rem 0;overflow:hidden}
.case>summary{cursor:pointer;padding:.75rem 1rem;display:flex;gap:.6rem;align-items:center;background:var(--card)}
.badge{font:600 11px/1 ui-monospace,monospace;padding:.3rem .5rem;border-radius:6px;color:#fff}
.PASS{background:var(--pass)}.FAIL{background:var(--fail)}.INCONCLUSIVE{background:var(--inc)}.SKIP{background:var(--skip)}
.flaky{color:var(--inc);font-size:12px}.a{padding:.4rem 1rem;border-top:1px solid var(--line);
display:flex;gap:.5rem;align-items:baseline}.a code{color:var(--muted);font-size:13px}
.detail{color:var(--fail);font-size:13px;margin:0 1rem .5rem 2.4rem}
.summary-bar{margin:1.5rem 0;font-weight:600}
"""


def _badge(status: Status) -> str:
    return f'<span class="badge {status.value}">{status.value}</span>'


def render_html(result: SuiteResult) -> str:
    counts = {s: sum(1 for c in result.cases if c.status is s) for s in Status}
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>litmus · {html.escape(result.name)}</title><style>{_CSS}</style></head><body>",
        f"<h1>litmus · {html.escape(result.name)}</h1>",
        f"<div class='sub'>{html.escape(json.dumps(result.target))}</div>",
        f"<div class='summary-bar'>{counts[Status.PASS]}/{len(result.cases)} green · "
        f"{counts[Status.FAIL]} failing · {counts[Status.INCONCLUSIVE]} inconclusive · {counts[Status.SKIP]} skipped</div>",
    ]
    for case in result.cases:
        openattr = "" if case.status is Status.PASS else " open"
        flaky = "<span class='flaky'>~flaky</span>" if case.flaky else ""
        parts.append(f"<details class='case'{openattr}><summary>{_badge(case.status)}"
                     f"<strong>{html.escape(case.id)}</strong>{flaky}</summary>")
        if case.error:
            parts.append(f"<div class='detail'>{html.escape(case.error)}</div>")
        for a in case.assertions:
            rate = "" if a.pass_rate in (0.0, 1.0) else f" ({a.pass_rate:.0%})"
            parts.append(f"<div class='a'>{_badge(a.status)}<code>{html.escape(a.name)}{rate}</code></div>")
            bad = next((v for v in a.verdicts if v.status is not Status.PASS and v.detail), None)
            if bad and a.status is not Status.PASS:
                parts.append(f"<div class='detail'>→ {html.escape(bad.detail)}</div>")
        parts.append("</details>")
    parts.append("</body></html>")
    return "".join(parts)
