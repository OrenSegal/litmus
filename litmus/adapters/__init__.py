"""Adapters produce the AgentRun the engine grades.

`transcript` (this release) loads a pre-captured AgentRun from disk — the
offline path used by tests and by CI after a run has happened. Live adapters
(`claude_code`, `agent_sdk`) land in later milestones and emit the same
AgentRun contract, so the graded core never changes.
"""
