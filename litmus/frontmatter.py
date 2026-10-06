"""Read `---` frontmatter from markdown files, and YAML files.

PyYAML is used when it is installed (`pip install litmus-ci[yaml]`). Without it,
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
        i += 1
        if rest:
            out[key] = _scalar_or_flow(rest)
            continue
        block: List[str] = []
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
            if lines[i].strip():
                block.append(lines[i].strip())
            i += 1
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
    if s.startswith("[") and s.endswith("]"):
        return [_scalar_or_flow(p) for p in _split_flow(s[1:-1])]
    if s.startswith("{") and s.endswith("}"):
        d: Dict[str, Any] = {}
        for part in _split_flow(s[1:-1]):
            k, sep, v = part.partition(":")
            if not sep:
                raise FrontmatterError(f"bad flow map entry: {part!r}")
            d[k.strip()] = _scalar_or_flow(v.strip())
        return d
    return _scalar(s)


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


def _scalar(s: str) -> Any:
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return _unescape_double(s[1:-1])
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            pass
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
