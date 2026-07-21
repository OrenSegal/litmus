"""A deliberately small JSON-Schema subset validator — dependency-free.

Supported keywords: type, required, properties, additionalProperties,
items, enum, minItems, maxItems, minimum, maximum, minLength, maxLength.
Returns a list of human-readable error strings (empty == valid). This is
enough to pin a skill's output contract; reach for `jsonschema` only if a
case genuinely needs the full spec.
"""

from __future__ import annotations

from typing import Any, Dict, List

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _type_matches(data: Any, name: str) -> bool:
    # bool is a subclass of int in Python — never let it satisfy number/integer
    if name == "boolean":
        return isinstance(data, bool)
    if name in ("integer", "number"):
        return isinstance(data, _TYPES[name]) and not isinstance(data, bool)
    return name in _TYPES and isinstance(data, _TYPES[name])


def validate(data: Any, schema: Dict[str, Any], _path: str = "$") -> List[str]:
    errs: List[str] = []
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_type_matches(data, name) for name in types):
            errs.append(f"{_path}: expected type {t}, got {type(data).__name__}")
            return errs  # further checks are meaningless on a type mismatch

    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errs.append(f"{_path}: missing required property '{key}'")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in data:
                errs.extend(validate(data[key], subschema, f"{_path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = set(data) - set(props)
            if extra:
                errs.append(f"{_path}: unexpected properties {sorted(extra)}")

    if isinstance(data, list):
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                errs.extend(validate(item, item_schema, f"{_path}[{i}]"))
        if "minItems" in schema and len(data) < schema["minItems"]:
            errs.append(f"{_path}: expected >= {schema['minItems']} items, got {len(data)}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errs.append(f"{_path}: expected <= {schema['maxItems']} items, got {len(data)}")

    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errs.append(f"{_path}: string shorter than {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errs.append(f"{_path}: string longer than {schema['maxLength']}")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errs.append(f"{_path}: {data} < minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errs.append(f"{_path}: {data} > maximum {schema['maximum']}")

    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{_path}: {data!r} not in enum {schema['enum']}")

    return errs
