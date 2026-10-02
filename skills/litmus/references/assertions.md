# Assertions

Each `assert:` entry is a single-key dict: the key is the assertion name, the
value is its config (a string shorthand or a dict). Deterministic assertions are
trusted unconditionally; `judge` is trusted only through the guardrails in
[trust-architecture.md](trust-architecture.md).

## Deterministic

| Assertion | Config | Passes when |
|---|---|---|
| `must_run` | `"finalize.py"` or `{tool, args?, before?, after?}` | tool was called (with matching args / in order) |
| `must_not` | `{tool}` \| `{field}` \| `{phrase, in}` | forbidden tool call / output field / phrase never appeared |
| `ordering` | `{first, then}` | `first` tool called before `then` |
| `schema` | `{path?, schema}` or `{path?, ref}` | value(s) at `path` validate (JSON-Schema subset) |
| `equals` | `{path, value}` | every match at `path` equals `value` (absent → FAIL) |
| `contains` | `{path, value}` | some string at `path` contains the substring |
| `matches` | `{path, pattern, timeout?}` | some string at `path` matches the regex (search capped at `timeout` s, default 2; a timeout is FAIL) |
| `count` | `{path, op, value}` | `count(path) op value`, op ∈ `>= <= == != > <` |
| `budget` | `{cost_usd? tokens? latency_ms?}` | run within envelope (missing telemetry → INCONCLUSIVE; `{}` or an unknown key → FAIL) |
| `resolves` | `"$..source_url"` or `{path}` | every cited URL resolves (bot-walled → INCONCLUSIVE, not dead) |
| `grounded` | `{claim, source, threshold?}` | cited claim's words appear on the fetched source page (claims and sources pair by position, so unequal counts → FAIL; a source that isn't an http(s) URL → INCONCLUSIVE) |

`resolves` / `grounded` are the generalized `verify_sources.py` — they read live
pages via an injectable fetcher (offline in tests). `resolves` treats a
bot-walled platform (reddit/x/linkedin/…) as `INCONCLUSIVE`, never a dead link.

## Judge (LLM-graded)

| `judge` | `{rubric, anchors, panel?}` (anchors required: at least one `expect: pass` and one `expect: fail`) |

Returns `INCONCLUSIVE` unless a judge is wired (`--judge claude` on the CLI, or `EvalContext(judge=...)` from Python) **and** the rubric has both pass and fail anchors **and** it passes anchor
calibration **and** the judge panel. It is also `INCONCLUSIVE`, with no
judge call, when the judge model is the model that produced the run (run
`meta.model`, else `target.model`). It can never override a deterministic
FAIL. See trust-architecture.md before using it.

## Verdict statuses

`PASS` · `FAIL` · `INCONCLUSIVE` (unfalsifiable — never counts as green) · `SKIP`

A case is green when at least one assertion is `PASS` and every other one is
`PASS` or `SKIP`. A case whose assertions all `SKIP` is `SKIP`: nothing was
checked. A case with fewer runs on disk than its `samples` is at best
`INCONCLUSIVE`.
(nothing to check, e.g. no URLs). A case is green only if every assertion is
PASS or SKIP.
