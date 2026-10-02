"""Model ids: normalize two ids and decide whether they name the same model.

Used by the no-self-grading guardrail (LITMUS_SPEC.md §6) and by
`litmus calibrate`. Pure string handling, no model calls.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# What `litmus capture` and `matrix` use for a run whose model is not known.
UNKNOWN_MODEL = "default"

# Values that name no model.
_UNKNOWN_MODELS = {"", UNKNOWN_MODEL, "unknown", "none", "null"}
_DATE_SUFFIX = re.compile(r"[-@]\d{8}$")
_BEDROCK_VERSION = re.compile(r"-v\d+(:\d+)?$")
_BEDROCK_PREFIX = re.compile(r"^(?:[a-z]+\.)?anthropic\.")


def normalize_model_id(model: Any) -> Optional[str]:
    """Reduce a model id to a comparable key, or None if it names no model.

    Rules, applied in order:
      1. lowercase and trim; "", "default", "unknown", "none" and "null" mean unknown
      2. keep only the part after the last "/" (drops "anthropic/", "models/")
      3. drop a Bedrock "<region>.anthropic." or "anthropic." prefix
      4. drop a Bedrock "-vN" or "-vN:M" suffix, then "-latest"
      5. drop a date suffix "-YYYYMMDD" or "@YYYYMMDD"
      6. turn "." into "-" and drop a leading "claude-"
      7. put the name words before the version numbers, so the older
         "3-5-sonnet" order equals "sonnet-3-5"

    So "claude-haiku-4-5-20251001", "anthropic/claude-haiku-4-5",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0" and "haiku-4.5" all become
    "haiku-4-5". A bare alias such as "haiku" stays "haiku".
    """
    if model is None:
        return None
    m = str(model).strip().lower()
    if m in _UNKNOWN_MODELS:
        return None
    m = m.rsplit("/", 1)[-1]
    m = _BEDROCK_PREFIX.sub("", m)
    m = _BEDROCK_VERSION.sub("", m)
    if m.endswith("-latest"):
        m = m[: -len("-latest")]
    m = _DATE_SUFFIX.sub("", m)
    m = m.replace(".", "-")
    if m.startswith("claude-"):
        m = m[len("claude-"):]
    parts = [p for p in m.split("-") if p]
    words = [p for p in parts if not p.isdigit()]
    numbers = [p for p in parts if p.isdigit()]
    key = "-".join(words + numbers)
    return key or None


def same_model(a: Any, b: Any) -> bool:
    """True if two model ids name the same model after `normalize_model_id`.

    A bare alias with no version number ("haiku", "sonnet", "opus") matches any
    model whose normalized id contains that word, because the alias can resolve
    to any of them. Refusing to grade is the safe side of that ambiguity.
    Unknown ids never match.
    """
    na, nb = normalize_model_id(a), normalize_model_id(b)
    if na is None or nb is None:
        return False
    if na == nb:
        return True
    for alias, other in ((na, nb), (nb, na)):
        if not any(ch.isdigit() for ch in alias) and "-" not in alias:
            if alias in other.split("-"):
                return True
    return False
