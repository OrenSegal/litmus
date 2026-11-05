"""Render a mutation-score bar SVG from a committed litmus report.json.

Usage: python scripts/score_svg.py docs/scores/cited-2026-10-09-r3/report.json docs/score.svg
"""

from __future__ import annotations

import json
import sys

W, H, BAR_Y, BAR_H = 520, 64, 30, 18
COLORS = {"killed": "#2e7d32", "survived": "#c62828", "inconclusive": "#9e9e9e"}


def render(report: dict) -> str:
    s = report["score"]
    counts = {k: int(s[k]) for k in COLORS}
    total = sum(counts.values())
    assert total == s["total_run"], (counts, s["total_run"])
    suite = report["suite"]["root"].removesuffix("-evals")
    title = (
        f"{suite}: mutation score {s['mutation_score']:.0%} "
        f"({counts['killed']} killed, {counts['survived']} survived, {counts['inconclusive']} inconclusive)"
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="{title}"><title>{title}</title>',
        f'<rect width="{W}" height="{H}" rx="6" fill="#fff"/>',
        f'<text x="10" y="20" font-family="sans-serif" font-size="13" fill="#222">{title}</text>',
    ]
    x, span = 10.0, W - 20
    for k, color in COLORS.items():
        w = span * counts[k] / total if total else 0
        if w:
            parts.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{w:.1f}" height="{BAR_H}" fill="{color}"/>')
            parts.append(
                f'<text x="{x + w / 2:.1f}" y="{BAR_Y + 13}" font-family="sans-serif" font-size="11" '
                f'fill="#fff" text-anchor="middle">{counts[k]}</text>'
            )
        x += w
    parts.append("</svg>\n")
    return "\n".join(parts)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        svg = render(json.load(f))
    with open(dst, "w", encoding="utf-8") as f:
        f.write(svg)
