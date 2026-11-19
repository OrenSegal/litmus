"""Read `---` frontmatter from markdown files, and YAML files.

PyYAML is used when it is installed (`pip install pyyaml`). Without it,
a small parser handles the subset eval frontmatter uses in practice: scalars,
single and double quoted strings, flow lists `[a, b]`, flow maps `{a: b}` and
one level of indented block maps or `- item` lists. Anything it cannot read
raises FrontmatterError rather than guessing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

__all__ = ["FrontmatterError", "split", "parse_yaml"]


class FrontmatterError(ValueError):
    pass


def split(text: str) -> Tuple[Dict[str, Any], str]:
    """Return (frontmatter dict, body). A file without frontmatter has {}."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            head = "".join(lines[1:i])
            body = "".join(lines[i + 1:])
            data = parse_yaml(head) if head.strip() else {}
            if not isinstance(data, dict):
                raise FrontmatterError("frontmatter is not a mapping")
            return data, body
    raise FrontmatterError("frontmatter opened with --- but never closed")


def parse_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError:
        return _mini(text)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FrontmatterError(str(exc)) from exc


# ---- minimal fallback parser ------------------------------------------------

_KEY = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?:\s+(.*))?$")


def _mini(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw[0] in " \t":
            raise FrontmatterError(f"unexpected indentation: {raw!r}")
        m = _KEY.match(raw)
        if not m:
            raise FrontmatterError(f"cannot parse line: {raw!r}")
        key, rest = m.group(1), (m.group(2) or "").strip()
        if rest.startswith("#"):
            rest = ""  # `key: # comment`: the value is on the following lines, or null
        i += 1
        if rest:
            out[key] = _scalar_or_flow(rest)
            continue
        block: List[str] = []
        indents = set()
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                block.append(lines[i].strip())
                indents.add(len(lines[i]) - len(lines[i].lstrip()))
            i += 1
        if len(indents) > 1:
            # Two indentation depths under one key: a nested map or a folded value.
            # Reading it as one flat level would silently change what it means.
            raise FrontmatterError(f"{key!r} is nested deeper than one level (install PyYAML to read it)")
        if not block:
            out[key] = None
        elif all(b.startswith("- ") or b == "-" for b in block):
            out[key] = [_scalar_or_flow(b[1:].strip()) for b in block]
        else:
            sub: Dict[str, Any] = {}
            for b in block:
                sm = _KEY.match(b)
                if not sm:
                    raise FrontmatterError(f"cannot parse nested line: {b!r}")
                sub[sm.group(1)] = _scalar_or_flow((sm.group(2) or "").strip())
            out[key] = sub
    return out


def _scalar_or_flow(s: str) -> Any:
    if s[:1] in ("[", "{"):
        s = _strip_comment(s)
        close = "]" if s[0] == "[" else "}"
        if not s.endswith(close):
            raise FrontmatterError(f"flow collection is not closed on its line: {s!r}")
        if close == "]":
            return [_scalar_or_flow(p) for p in _split_flow(s[1:-1])]
        d: Dict[str, Any] = {}
        for part in _split_flow(s[1:-1]):
            k, sep, v = part.partition(":")
            if not sep:
                raise FrontmatterError(f"bad flow map entry: {part!r}")
            k = k.strip()
            d[str(_scalar(k)) if k[:1] in ("'", '"') else k] = _scalar_or_flow(v.strip())
        return d
    return _scalar(s)


def _strip_comment(s: str) -> str:
    """Drop a trailing ` # comment` that is outside quotes."""
    quote = ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s


def _split_flow(s: str) -> List[str]:
    parts: List[str] = []
    depth, quote, cur = 0, "", ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


_INT = [(re.compile(r"[-+]?(?:0|[1-9][0-9_]*)$"), 10), (re.compile(r"[-+]?0[0-7_]+$"), 8),
        (re.compile(r"[-+]?0x[0-9a-fA-F_]+$"), 16), (re.compile(r"[-+]?0b[01_]+$"), 2)]
_FLOAT = re.compile(r"(?:[-+]?[0-9][0-9_]*\.[0-9_]*|\.[0-9][0-9_]*)(?:[eE][-+][0-9]+)?$")
_SEXAGESIMAL = re.compile(r"[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?$")
_TRUE = {"yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON"}
_FALSE = {"no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF"}
_NULL = {"", "~", "null", "Null", "NULL"}


def _quoted(s: str) -> str:
    """The value of a scalar that opens with a quote. Only a comment may follow it."""
    q, i = s[0], 1
    while i < len(s):
        if q == '"' and s[i] == "\\":
            i += 2
            continue
        if s[i] == q:
            if q == "'" and s[i + 1:i + 2] == "'":  # '' is an escaped quote
                i += 2
                continue
            rest = s[i + 1:].strip()
            if rest and not rest.startswith("#"):
                raise FrontmatterError(f"unexpected text after the closing quote: {s!r}")
            inner = s[1:i]
            return inner.replace("''", "'") if q == "'" else _unescape_double(inner)
        i += 1
    raise FrontmatterError(f"quoted string is never closed: {s!r}")


def _scalar(s: str) -> Any:
    """One scalar, read as PyYAML reads it; FrontmatterError where the two would differ."""
    if s[:1] in ("'", '"'):
        return _quoted(s)
    # A plain scalar: quotes inside it are ordinary characters (`don't # note`),
    # so the comment starts at the first ` #` whatever precedes it.
    s = re.split(r"(?:^|\s)#", s, maxsplit=1)[0].rstrip()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if s in _NULL:
        return None
    if s[0] in "&*!|>@%`" or re.search(r":(?:\s|$)", s) or _SEXAGESIMAL.match(s):
        # anchors, tags, block scalars, a nested `key: value`, base-60 numbers
        raise FrontmatterError(f"cannot parse value: {s!r} (quote it, or install PyYAML)")
    for rx, base in _INT:
        if rx.match(s):
            digits = s.replace("_", "")
            try:
                return int(digits, base) if base == 10 else int(digits.replace("0x", "").replace("0b", ""), base)
            except ValueError:  # `0x_`: no digits at all (PyYAML crashes on it too)
                raise FrontmatterError(f"cannot parse value: {s!r}") from None
    if _FLOAT.match(s):
        return float(s.replace("_", ""))
    if s in (".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF"):
        return float("inf")
    if s in ("-.inf", "-.Inf", "-.INF"):
        return float("-inf")
    if s in (".nan", ".NaN", ".NAN"):
        return float("nan")
    return s


_ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0", "r": "\r"}


def _unescape_double(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESC:
                out.append(_ESC[nxt])
                i += 2
                continue
            if nxt == "x" and i + 3 < len(s):
                out.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
                continue
            raise FrontmatterError(f"unsupported escape \\{nxt} in double-quoted string")
        out.append(ch)
        i += 1
    return "".join(out)
