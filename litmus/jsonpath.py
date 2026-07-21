"""A tiny, dependency-free JSONPath resolver.

Supports exactly the selectors Litmus assertions need — nothing more, so it
stays small and auditable:

    $                root
    .field           object member
    [n]              list index (negative allowed)
    [*]              wildcard over a list's items or an object's values
    ..field          recursive descent collecting `field` anywhere below

`resolve` always returns a *list* of matched values (empty if nothing
matched). Callers distinguish "field absent" from "field present but null"
by inspecting the list length, never by a sentinel.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_TOKEN = re.compile(
    r"""
    \.\.(?P<rfield>[A-Za-z_][\w-]*)   # ..field  (recursive descent)
  | \.(?P<field>[A-Za-z_][\w-]*)      # .field
  | \[(?P<index>-?\d+)\]              # [n]
  | (?P<wild>\[\*\])                  # [*]
    """,
    re.VERBOSE,
)


def _tokenize(path: str) -> List[Tuple[str, Any]]:
    if not path.startswith("$"):
        raise ValueError(f"JSONPath must start with '$': {path!r}")
    rest = path[1:]
    tokens: List[Tuple[str, Any]] = []
    pos = 0
    while pos < len(rest):
        m = _TOKEN.match(rest, pos)
        if not m:
            raise ValueError(f"Unparseable JSONPath near {rest[pos:]!r} in {path!r}")
        if m.lastgroup == "rfield":
            tokens.append(("rfield", m.group("rfield")))
        elif m.lastgroup == "field":
            tokens.append(("field", m.group("field")))
        elif m.lastgroup == "index":
            tokens.append(("index", int(m.group("index"))))
        else:
            tokens.append(("wild", None))
        pos = m.end()
    return tokens


def _recursive_collect(node: Any, key: str) -> List[Any]:
    out: List[Any] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            out.extend(_recursive_collect(v, key))
    elif isinstance(node, list):
        for item in node:
            out.extend(_recursive_collect(item, key))
    return out


def resolve(path: str, data: Any) -> List[Any]:
    """Return every value matching `path` within `data` (possibly empty)."""
    current: List[Any] = [data]
    for kind, val in _tokenize(path):
        nxt: List[Any] = []
        for node in current:
            if kind == "field":
                if isinstance(node, dict) and val in node:
                    nxt.append(node[val])
            elif kind == "index":
                if isinstance(node, list) and -len(node) <= val < len(node):
                    nxt.append(node[val])
            elif kind == "wild":
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif kind == "rfield":
                nxt.extend(_recursive_collect(node, val))
        current = nxt
    return current


def exists(path: str, data: Any) -> bool:
    """True if `path` matches at least one value."""
    return len(resolve(path, data)) > 0
