"""Judge calibration: how often does the judge agree with a human?

Input is a JSONL file, one labeled sample per line:

    {"id": "s1", "artifact": ..., "rubric": "...", "human": "pass" | "fail",
     "judge": "pass" | "fail",   # optional, filled by `fill_judge`
     "model": "..."}             # optional, the model that produced the artifact

FAIL is the positive class, because the judge's job is to catch failures:
recall is the share of human-labeled failures the judge also failed, precision
is the share of judge failures a human agrees with. Cohen's kappa corrects raw
agreement for the agreement two raters would reach by chance, which matters when
most samples pass: a judge that always says PASS scores high accuracy on a
pass-heavy set and a kappa of 0.

Everything here is pure except `fill_judge`, which calls whatever JudgeFn it is
given. The human labels are the ground truth and are never generated here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .assertions import same_model

VERDICTS = ("pass", "fail")
_FIELDS = ("id", "artifact", "rubric", "human", "judge", "model")


class CalibrationError(ValueError):
    """A labels file row is malformed."""


@dataclass
class Sample:
    id: str
    artifact: Any
    rubric: str
    human: str
    judge: Optional[str] = None
    model: Optional[str] = None
    # Any other fields in the row (a rationale, a source), kept so `--out` writes them back.
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        row: Dict[str, Any] = {"id": self.id, "artifact": self.artifact, "rubric": self.rubric,
                               "human": self.human, **self.extra}
        if self.judge is not None:
            row["judge"] = self.judge
        if self.model is not None:
            row["model"] = self.model
        return row


def _verdict(value: Any, where: str, required: bool) -> Optional[str]:
    if value is None and not required:
        return None
    if isinstance(value, str) and value.strip().lower() in VERDICTS:
        return value.strip().lower()
    raise CalibrationError(f"{where}: expected \"pass\" or \"fail\", got {value!r}")


def load_samples(path: Path) -> List[Sample]:
    samples: List[Sample] = []
    seen = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path}:{lineno}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"{where}: not valid JSON ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise CalibrationError(f"{where}: each line must be a JSON object")
        for key in ("id", "artifact", "rubric", "human"):
            if key not in row:
                raise CalibrationError(f"{where}: missing {key!r}")
        if not isinstance(row["rubric"], str) or not row["rubric"].strip():
            raise CalibrationError(f"{where}: rubric must be a non-empty string")
        sid = str(row["id"])
        if sid in seen:
            raise CalibrationError(f"{where}: duplicate id {sid!r}")
        seen.add(sid)
        samples.append(Sample(
            id=sid,
            artifact=row["artifact"],
            rubric=row["rubric"],
            human=_verdict(row["human"], f"{where} human", required=True),
            judge=_verdict(row.get("judge"), f"{where} judge", required=False),
            model=row.get("model"),
            extra={k: v for k, v in row.items() if k not in _FIELDS},
        ))
    return samples


def write_samples(path: Path, samples: List[Sample]) -> None:
    Path(path).write_text("".join(json.dumps(s.to_json(), ensure_ascii=False) + "\n" for s in samples),
                          encoding="utf-8")


def fill_judge(samples: List[Sample], judge: Callable[[Any, str], bool],
               rejudge: bool = False) -> List[str]:
    """Set `judge` on each sample that lacks one (all of them if `rejudge`).

    A sample whose producing model is the judge's model is left unjudged, so
    it drops out of the metrics (no self-grading), even if it already had a
    verdict. Returns one warning per skipped sample.
    """
    judge_model = getattr(judge, "model", None)
    warnings: List[str] = []
    for s in samples:
        if same_model(judge_model, s.model):
            s.judge = None
            warnings.append(f"{s.id}: not judged, the judge model {judge_model!r} produced it ({s.model!r})")
            continue
        if s.judge is not None and not rejudge:
            continue
        s.judge = "pass" if judge(s.artifact, s.rubric) else "fail"
    return warnings


@dataclass
class Disagreement:
    id: str
    human: str
    judge: str


@dataclass
class Calibration:
    tp: int = 0  # judge fail, human fail
    fp: int = 0  # judge fail, human pass
    fn: int = 0  # judge pass, human fail
    tn: int = 0  # judge pass, human pass
    unjudged: int = 0
    disagreements: List[Disagreement] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def human_failures(self) -> int:
        return self.tp + self.fn

    @staticmethod
    def _ratio(num: int, den: int) -> Optional[float]:
        return num / den if den else None

    @property
    def precision(self) -> Optional[float]:
        return self._ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Optional[float]:
        return self._ratio(self.tp, self.tp + self.fn)

    @property
    def accuracy(self) -> Optional[float]:
        return self._ratio(self.tp + self.tn, self.n)

    @property
    def kappa(self) -> Optional[float]:
        """Cohen's kappa. None when undefined (no samples, or both raters gave
        a single identical label to everything, so chance agreement is 1)."""
        n = self.n
        if not n:
            return None
        observed = (self.tp + self.tn) / n
        judge_fail, human_fail = (self.tp + self.fp) / n, (self.tp + self.fn) / n
        expected = judge_fail * human_fail + (1 - judge_fail) * (1 - human_fail)
        if expected == 1:
            return None
        return (observed - expected) / (1 - expected)

    def to_json(self) -> Dict[str, Any]:
        return {
            "n": self.n, "unjudged": self.unjudged, "human_failures": self.human_failures,
            "confusion": {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn},
            "precision": self.precision, "recall": self.recall,
            "accuracy": self.accuracy, "kappa": self.kappa,
            "disagreements": [d.__dict__ for d in self.disagreements],
        }


def calibrate(samples: List[Sample]) -> Calibration:
    result = Calibration()
    for s in samples:
        if s.judge is None:
            result.unjudged += 1
            continue
        if s.judge == "fail":
            if s.human == "fail":
                result.tp += 1
            else:
                result.fp += 1
        else:
            if s.human == "fail":
                result.fn += 1
            else:
                result.tn += 1
        if s.judge != s.human:
            result.disagreements.append(Disagreement(s.id, s.human, s.judge))
    return result


def _fmt(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_calibration(c: Calibration) -> str:
    lines = [
        f"calibration: {c.n} judged samples, {c.human_failures} human-labeled failures"
        + (f", {c.unjudged} unjudged (excluded)" if c.unjudged else ""),
        "",
        "                  human FAIL  human PASS",
        f"  judge FAIL      {c.tp:>10}  {c.fp:>10}",
        f"  judge PASS      {c.fn:>10}  {c.tn:>10}",
        "",
        f"  recall     {_fmt(c.recall)}   share of human failures the judge also failed",
        f"  precision  {_fmt(c.precision)}   share of judge failures a human agrees with",
        f"  accuracy   {_fmt(c.accuracy)}",
        f"  kappa      {_fmt(c.kappa)}   agreement beyond chance (0 = chance, 1 = perfect)",
    ]
    if c.disagreements:
        lines += ["", f"disagreements ({len(c.disagreements)}):"]
        lines += [f"  {d.id}: human {d.human.upper()}, judge {d.judge.upper()}" for d in c.disagreements]
    return "\n".join(lines)
