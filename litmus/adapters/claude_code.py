"""claude-code adapter — capture a live AgentRun by driving the Claude CLI.

`capture()` shells out to `claude -p --output-format stream-json`, which uses
the CLI's own authentication — no API key is handled here. The parsing half
(`parse_stream`) is a pure function over the emitted event dicts, so it is
fully unit-tested offline against fixture events; only `capture()` itself
touches the network, and it is never exercised by the test suite.

stream-json emits one JSON object per line. We consume the shapes we need and
ignore the rest, so the adapter degrades gracefully across CLI versions:

    {"type":"assistant","message":{"content":[
        {"type":"tool_use","name":"finalize.py","input":{...}},
        {"type":"text","text":"..."}]}}
    {"type":"result","subtype":"success","result":"...",
        "total_cost_usd":0.03,"duration_ms":5100,
        "usage":{"input_tokens":1000,"output_tokens":200}}
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Dict, List, Optional

from ..models import AgentRun, ToolCall

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

    for ev in events:
        etype = ev.get("type")
        if etype in ("assistant", "user"):
            content = ev.get("message", {}).get("content", [])
            if isinstance(content, str):
                texts.append(content)
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(name=str(block.get("name", "")), input=dict(block.get("input", {}))))
                elif block.get("type") == "text":
                    texts.append(str(block.get("text", "")))
        elif etype == "result":
            result_text = str(ev.get("result", ""))
            cost = ev.get("total_cost_usd", cost)
            latency = ev.get("duration_ms", latency)
            usage = ev.get("usage", {}) or {}
            tok = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            tokens = tok or tokens

    final_text = result_text or (texts[-1] if texts else "")
    return AgentRun(
        output=_extract_output(final_text),
        tool_calls=tool_calls,
        final_text=final_text,
        transcript="\n".join(texts),
        cost_usd=cost,
        tokens=tokens,
        latency_ms=latency,
    )


def capture(
    prompt: str,
    *,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 300,
) -> AgentRun:
    """Run the Claude CLI headless and return the captured AgentRun.

    Not covered by the offline test suite — it invokes the CLI. The skill to
    load is expected to be discoverable from `cwd` (the CLI's own resolution).
    """
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    if extra_args:
        cmd += extra_args
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    events: List[Dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    run = parse_stream(events)
    run.meta.setdefault("model", model or "default")
    run.meta.setdefault("exit_code", proc.returncode)
    return run
