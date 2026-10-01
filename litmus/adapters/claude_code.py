"""claude-code adapter — capture a live AgentRun by driving the Claude CLI.

`capture()` shells out to `claude -p --output-format stream-json`, which uses
the CLI's own authentication — no API key is handled here. The prompt goes over
stdin, not argv (argv is size-limited and visible in `ps`). The parsing half
(`parse_stream`) is a pure function over the emitted event dicts, so it is
fully unit-tested offline against fixture events; `capture()` is tested only
against a mocked subprocess, never against the real CLI.

A capture that fails (CLI missing, non-zero exit, timeout, no stream events)
raises CaptureError instead of returning a run, so a broken capture can never
be written to disk and graded as if it were the agent's behaviour. Each run is
stamped `meta.captured_by = "litmus capture"` and `meta.captured_at` (UTC), which
is how `litmus status` tells captured runs from hand-written fixtures.

stream-json emits one JSON object per line. We consume the shapes we need and
ignore the rest, so the adapter degrades gracefully across CLI versions:

    {"type":"assistant","message":{"content":[
        {"type":"tool_use","name":"finalize.py","input":{...}},
        {"type":"text","text":"..."}]}}
    {"type":"system","subtype":"init","model":"claude-sonnet-4-5-20250929",...}
    {"type":"result","subtype":"success","result":"...",
        "total_cost_usd":0.03,"duration_ms":5100,
        "usage":{"input_tokens":1000,"output_tokens":200}}
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..model_ids import UNKNOWN_MODEL
from ..models import AgentRun, ToolCall

CAPTURED_BY = "litmus capture"


class CaptureError(RuntimeError):
    """The CLI did not produce a usable run. The CLI command exits 2."""


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL)


def _extract_output(text: str) -> Any:
    """Best-effort: pull the structured result out of the final message —
    a fenced ```json block if present, else the whole text as JSON, else None."""
    if not text:
        return None
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text.strip()
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def parse_stream(events: List[Dict[str, Any]]) -> AgentRun:
    """Pure: fold a list of stream-json event dicts into one AgentRun."""
    tool_calls: List[ToolCall] = []
    texts: List[str] = []
    cost: Optional[float] = None
    tokens: Optional[int] = None
    latency: Optional[float] = None
    result_text = ""
    model: Optional[str] = None  # the model that actually ran, for no-self-grading

    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "system" and ev.get("model") and model is None:
            model = str(ev["model"])
        if etype == "assistant" and model is None:
            msg_model = (ev.get("message") or {}).get("model")
            if msg_model:
                model = str(msg_model)
        if etype in ("assistant", "user"):
            message = ev.get("message")
            content = message.get("content", []) if isinstance(message, dict) else []
            if isinstance(content, str):
                texts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    raw_input = block.get("input")
                    tool_calls.append(ToolCall(name=str(block.get("name", "")),
                                               input=dict(raw_input) if isinstance(raw_input, dict) else {}))
                elif block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
        elif etype == "result":
            result_text = str(ev.get("result", ""))
            cost = ev.get("total_cost_usd", cost)
            latency = ev.get("duration_ms", latency)
            usage = ev.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            tok = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            tokens = tok or tokens

    final_text = result_text or (texts[-1] if texts else "")
    run = AgentRun(
        output=_extract_output(final_text),
        tool_calls=tool_calls,
        final_text=final_text,
        transcript="\n".join(texts),
        cost_usd=cost,
        tokens=tokens,
        latency_ms=latency,
    )
    if model:
        run.meta["model"] = model
    return run


def capture(
    prompt: str,
    *,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 300,
) -> AgentRun:
    """Run the Claude CLI headless and return the captured AgentRun.

    The skill to load is expected to be discoverable from `cwd` (the CLI's own
    resolution). Raises CaptureError when the CLI is missing, times out, exits
    non-zero, or emits no stream events.
    """
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    if extra_args:
        cmd += extra_args
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        proc = subprocess.run(cmd, input=prompt, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CaptureError("the Claude CLI (`claude`) is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"the Claude CLI timed out after {timeout}s; nothing was written") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()[-500:] or "no output"
        raise CaptureError(f"the Claude CLI exited with code {proc.returncode}: {detail}")
    events: List[Dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            events.append(ev)
    if not events:
        raise CaptureError("the Claude CLI produced no stream-json events; nothing was written")
    run = parse_stream(events)
    # An explicit --model is the tag `matrix` groups and filters on, so it wins.
    # The id the CLI reported is kept as meta.model_id. With no --model, the
    # reported id becomes meta.model (UNKNOWN_MODEL only if the CLI reported none).
    reported = run.meta.get("model")
    if reported:
        run.meta["model_id"] = reported
    if model:
        run.meta["model"] = model
    run.meta.setdefault("model", UNKNOWN_MODEL)
    run.meta.setdefault("exit_code", proc.returncode)
    run.meta["captured_by"] = CAPTURED_BY
    run.meta["captured_at"] = started
    return run
