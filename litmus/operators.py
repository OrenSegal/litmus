"""Deterministic mutation operators for prose that steers a model.

Each operator takes one markdown file (a SKILL.md, a command, an agent, a
system prompt) and returns the sites it can break, each as a fully patched
copy of the file. Sites are enumerated in file order, so the same input always
yields the same mutants with the same ids. No operator calls a model.

Frontmatter is left alone except by `drop-description`, which exists to test
whether the evals notice that a skill no longer triggers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

__all__ = ["OPERATORS", "Site", "mutate_text", "split_raw"]


@dataclass
class Site:
    description: str
    patched: str


def split_raw(text: str) -> Tuple[str, str]:
    """(frontmatter block including both --- lines, body). Verbatim, no parsing."""
    if text.startswith("---"):
        m = re.match(r"---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
        if m:
            return text[:m.end()], text[m.end():]
    return "", text


def _prose_lines(body: str) -> List[Tuple[int, str]]:
    """(index, line) for body lines outside fenced code blocks."""
    out, fenced = [], False
    for i, line in enumerate(body.split("\n")):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            out.append((i, line))
    return out


def _short(s: str, n: int = 70) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "..."


# ---- operators -------------------------------------------------------------

def op_delete_body(text: str) -> List[Site]:
    head, body = split_raw(text)
    if not body.strip():
        return []
    return [Site("empty the body; keep only the frontmatter", head + "\n")]


def op_truncate(text: str) -> List[Site]:
    head, body = split_raw(text)
    lines = body.split("\n")
    if sum(1 for ln in lines if ln.strip()) < 4:
        return []
    keep = len(lines) // 2
    return [Site(f"keep the first {keep} of {len(lines)} body lines", head + "\n".join(lines[:keep]) + "\n")]


_DIRECTIVE = re.compile(r"\b(must|never|always|do not|don't|should|only|required?|before|after|refuse|ask)\b", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


def op_delete_instruction(text: str) -> List[Site]:
    head, body = split_raw(text)
    lines = body.split("\n")
    sites = []
    for i, line in _prose_lines(body):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if _LIST_ITEM.match(line) or _DIRECTIVE.search(line):
            patched = lines[:i] + lines[i + 1:]
            sites.append(Site(f"delete line {i + 1}: {_short(s)}", head + "\n".join(patched)))
    return sites


_INVERSIONS = [
    ("must not", "must"), ("mustn't", "must"), ("do not", "do"), ("don't", "do"), ("does not", "does"),
    ("should not", "should"), ("shouldn't", "should"), ("cannot", "can"), ("can't", "can"),
    ("never", "always"), ("always", "never"), ("must", "must not"), ("should", "should not"),
]
_INV_RX = re.compile(r"\b(" + "|".join(re.escape(a) for a, _ in _INVERSIONS) + r")\b", re.I)
_INV_MAP = {a: b for a, b in _INVERSIONS}


def _keep_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def op_invert_rule(text: str) -> List[Site]:
    head, body = split_raw(text)
    lines = body.split("\n")
    sites = []
    for i, line in _prose_lines(body):
        m = _INV_RX.search(line)
        if not m:
            continue
        repl = _keep_case(m.group(1), _INV_MAP[m.group(1).lower()])
        new = line[: m.start()] + repl + line[m.end():]
        patched = lines[:i] + [new] + lines[i + 1:]
        sites.append(Site(f"line {i + 1}: '{m.group(1)}' -> '{repl}' in: {_short(line.strip())}",
                          head + "\n".join(patched)))
    return sites


_TOOL_NAMES = ["Bash", "Read", "Write", "Edit", "Grep", "Glob", "WebFetch", "WebSearch", "Skill", "Task", "Agent"]
_CODE_SPAN = re.compile(r"`([^`\n]{2,60})`")


def _swap(body: str, a: str, b: str, rx_a: str, rx_b: str) -> str:
    token = "\x00LITMUS_SWAP\x00"
    out = re.sub(rx_a, token, body)
    out = re.sub(rx_b, a.replace("\\", r"\\"), out)
    return out.replace(token, b)


def op_swap_tool_names(text: str) -> List[Site]:
    """Swap two tool names, or two inline-code spans (commands, flags, files), throughout the body."""
    head, body = split_raw(text)
    sites = []
    tools = [t for t in _TOOL_NAMES if re.search(r"\b" + t + r"\b", body)]
    tools.sort(key=lambda t: re.search(r"\b" + t + r"\b", body).start())  # type: ignore[union-attr]
    for a, b in zip(tools, tools[1:]):
        patched = _swap(body, a, b, r"\b" + a + r"\b", r"\b" + b + r"\b")
        if patched != body:
            sites.append(Site(f"swap tool names {a} <-> {b}", head + patched))
    spans: List[str] = []
    for m in _CODE_SPAN.finditer(body):
        if m.group(1).startswith("$"):
            continue  # $ARGUMENTS and similar placeholders are not commands
        if m.group(1) not in spans:
            spans.append(m.group(1))
    for a, b in zip(spans, spans[1:]):
        ta, tb = f"`{a}`", f"`{b}`"
        patched = _swap(body, ta, tb, re.escape(ta), re.escape(tb))
        if patched != body:
            sites.append(Site(f"swap code spans {ta} <-> {tb}", head + patched))
    return sites


_WORD_FLIPS = [("before", "after"), ("first", "last"), ("true", "false"), ("allow", "deny"),
               ("include", "exclude"), ("increase", "decrease"), ("more", "fewer"), ("above", "below")]
_FLIP_MAP = {**{a: b for a, b in _WORD_FLIPS}, **{b: a for a, b in _WORD_FLIPS}}
_FACT_RX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.]*\w)|\b(" + "|".join(_FLIP_MAP) + r")\b", re.I)


def _wrong_number(s: str) -> str:
    if "." in s:
        return str(round(float(s) * 2, 6))
    n = int(s)
    if n >= 1900:
        return str(n + 2)  # years and other large ids: close but wrong
    return str(n * 2 if n >= 2 else n + 2)


def op_wrong_fact(text: str) -> List[Site]:
    """Replace one number or one directional word with a plausible wrong one."""
    head, body = split_raw(text)
    lines = body.split("\n")
    sites = []
    for i, line in _prose_lines(body):
        if line.strip().startswith("#"):
            continue
        marker = _LIST_ITEM.match(line)
        for m in _FACT_RX.finditer(line):
            if marker and m.start() < marker.end():
                continue  # "1." list numbering is not a fact
            if m.group(1):
                repl = _wrong_number(m.group(1))
            else:
                repl = _keep_case(m.group(2), _FLIP_MAP[m.group(2).lower()])
            new = line[: m.start()] + repl + line[m.end():]
            patched = lines[:i] + [new] + lines[i + 1:]
            sites.append(Site(f"line {i + 1}: '{m.group(0)}' -> '{repl}' in: {_short(line.strip())}",
                              head + "\n".join(patched)))
    return sites


_DESC_RX = re.compile(r"^description:[^\n]*(?:\n[ \t]+[^\n]*)*", re.M)


def op_drop_description(text: str) -> List[Site]:
    head, body = split_raw(text)
    if not head:
        return []
    m = _DESC_RX.search(head)
    if not m:
        return []
    new_head = head[: m.start()] + "description: General helper." + head[m.end():]
    return [Site("replace the frontmatter description with 'General helper.' (tests triggering)", new_head + body)]


OPERATORS: Dict[str, Callable[[str], List[Site]]] = {
    "delete-body": op_delete_body,
    "delete-instruction": op_delete_instruction,
    "invert-rule": op_invert_rule,
    "swap-tool-names": op_swap_tool_names,
    "truncate": op_truncate,
    "wrong-fact": op_wrong_fact,
    "drop-description": op_drop_description,
}

DESCRIPTIONS = {
    "delete-body": "Empty the file's body, keep its frontmatter. The strongest mutant: evals that survive it do not depend on the prose at all.",
    "delete-instruction": "Delete one directive line (a list item, or a line with must/never/always/only/...).",
    "invert-rule": "Flip one rule: never<->always, must<->must not, do not->do, should<->should not.",
    "swap-tool-names": "Swap two tool names (Bash<->Read) or two inline-code spans (commands, flags, paths) everywhere in the body.",
    "truncate": "Keep only the first half of the body.",
    "wrong-fact": "Change one number (2 -> 4, 1999 -> 2001) or one directional word (before<->after, allow<->deny).",
    "drop-description": "Replace the frontmatter description with a generic one, so the skill should stop triggering.",
}


def mutate_text(text: str, operator: str) -> List[Site]:
    sites = OPERATORS[operator](text)
    return [s for s in sites if s.patched != text]
