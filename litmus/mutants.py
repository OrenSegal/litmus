"""Mutants: generate them, record them, replay them, and build the mutated copy.

Every mutant carries the full patched file and the SHA-256 of the original it
was made from, so a manifest replays exactly: deterministic operators and
LLM-written mutants go through the same path. A mutant whose original file has
changed since it was recorded is stale and is reported INCONCLUSIVE, never run.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import __version__
from .operators import OPERATORS, mutate_text

__all__ = ["Mutant", "generate", "select", "write_manifest", "load_manifest", "materialize", "sha256"]

MANIFEST_SCHEMA = "litmus.mutants/1"

# Never copied into a mutant workspace. Large dependency trees are symlinked.
_SKIP = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".litmus"}
_LINK = {"node_modules", ".venv", "venv"}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Mutant:
    id: str
    operator: str
    file: str  # relative to the suite root, POSIX separators
    site: int
    description: str
    original_sha256: str
    patched: str
    generator: Dict[str, Any] = field(default_factory=lambda: {"kind": "deterministic"})

    def diff(self, original: str, context: int = 2) -> str:
        return "".join(difflib.unified_diff(
            original.splitlines(keepends=True), self.patched.splitlines(keepends=True),
            fromfile=f"a/{self.file}", tofile=f"b/{self.file}", n=context))

    def to_obj(self) -> Dict[str, Any]:
        d = asdict(self)
        d["patched_sha256"] = sha256(self.patched)
        return d


def generate(root: Path, files: Iterable[Path], operators: Sequence[str], max_sites: int) -> List[Mutant]:
    out: List[Mutant] = []
    for path in files:  # adapter order is priority order
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        orig = sha256(text)
        for op in operators:
            for n, site in enumerate(mutate_text(text, op)[:max_sites]):
                mid = f"{op}:{rel}:{n}:{sha256(site.patched)[:8]}"
                out.append(Mutant(mid, op, rel, n, site.description, orig, site.patched))
    return out


def select(mutants: List[Mutant], limit: Optional[int]) -> List[Mutant]:
    """Round-robin across operators so a cap keeps every operator represented."""
    if limit is None or len(mutants) <= limit:
        return list(mutants)
    order = [op for op in OPERATORS if any(m.operator == op for m in mutants)]
    order += sorted({m.operator for m in mutants} - set(order))
    queues = {op: [m for m in mutants if m.operator == op] for op in order}
    picked: List[Mutant] = []
    while len(picked) < limit and any(queues.values()):
        for op in order:
            if queues[op] and len(picked) < limit:
                picked.append(queues[op].pop(0))
    return picked


def write_manifest(path: Path, root: Path, mutants: List[Mutant]) -> None:
    doc = {
        "schema": MANIFEST_SCHEMA,
        "litmus_version": __version__,
        "root": str(root),
        "mutants": [m.to_obj() for m in mutants],
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class UnsafeMutantPath(ValueError):
    """A mutant's file resolves outside its workspace (through a symlink), so
    writing it could modify the original plugin."""


class ManifestError(ValueError):
    pass


def load_manifest(path: Path) -> List[Mutant]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise ManifestError(f"{path}: schema is {doc.get('schema')!r}, expected {MANIFEST_SCHEMA!r}")
    out = []
    for i, m in enumerate(doc.get("mutants", [])):
        try:
            mut = Mutant(m["id"], m["operator"], m["file"], int(m.get("site", 0)), m.get("description", ""),
                         m["original_sha256"], m["patched"], m.get("generator") or {"kind": "deterministic"})
        except KeyError as exc:
            raise ManifestError(f"{path}: mutant {i} is missing {exc}") from exc
        if "patched_sha256" in m and m["patched_sha256"] != sha256(mut.patched):
            raise ManifestError(f"{path}: mutant {mut.id} patched content does not match its patched_sha256")
        if Path(mut.file).is_absolute() or ".." in Path(mut.file).parts:
            raise ManifestError(f"{path}: mutant {mut.id} names a file outside the suite root")
        out.append(mut)
    return out


def stale(root: Path, m: Mutant) -> Optional[str]:
    """Why this mutant can't be applied to `root` as it is now, or None."""
    target = root / m.file
    if not target.is_file():
        return f"{m.file} no longer exists"
    if sha256(target.read_text(encoding="utf-8")) != m.original_sha256:
        return f"{m.file} changed since the mutant was recorded"
    return None


def _ignore(results_rel: Optional[str]):  # type: ignore[no-untyped-def]
    def ignore(dirpath: str, names: List[str]) -> List[str]:
        skip = [n for n in names if n in _SKIP or n in _LINK]
        if results_rel:
            for n in names:
                if Path(dirpath, n).as_posix().endswith("/" + results_rel):
                    skip.append(n)
        return skip
    return ignore


def materialize(root: Path, dest: Path, mutant: Optional[Mutant], results_rel: Optional[str] = None) -> Path:
    """Copy `root` to `dest` (dependency dirs symlinked) and apply `mutant` if given."""
    shutil.copytree(root, dest, ignore=_ignore(results_rel), symlinks=True)
    for name in _LINK:
        src = root / name
        if src.exists():
            os.symlink(src, dest / name)
    if mutant is not None:
        target = dest / mutant.file
        dest_real = dest.resolve()
        parent_real = target.parent.resolve()
        if parent_real != dest_real and dest_real not in parent_real.parents:
            raise UnsafeMutantPath(f"{mutant.file} resolves outside the mutant workspace (symlinked directory)")
        if target.is_symlink():
            target.unlink()  # never write through a file symlink into the original
        target.write_text(mutant.patched, encoding="utf-8")
    return dest
