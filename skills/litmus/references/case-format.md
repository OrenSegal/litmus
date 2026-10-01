# Case & suite format

## Suite layout

```
suite/
  suite.json               # { "name", "target": {skill, model}, "defaults": {samples} }
  cases/*.json | *.yaml     # one Case each (YAML needs the litmus-ci[yaml] extra)
  runs/<case-id>/*.json     # captured AgentRun samples for that case
  runs/<case-id>.json       # ...or a single sample
  *.schema.json             # referenced by `schema: { ref: ... }`
  baseline.json             # written by `litmus bless`
```

Runs precedence for a case: explicit `runs:` paths → `runs/<id>/*.json` → `runs/<id>.json`.

## Case

```json
{
  "id": "classify-solo-maintainer-as-individual",
  "input": "https://example.com — solo maintainer, active on GitHub",
  "samples": 3,
  "assert": [
    { "must_run": "finalize.py" },
    { "schema": { "path": "$", "ref": "signal-scout.schema.json" } },
    { "equals": { "path": "$.individuals[0].type", "value": "Individual" } },
    { "must_not": { "field": "$.segments[*].opener" } }
  ]
}
```

`samples` declares how many captured runs the case is graded over; each
assertion reports a pass-rate and a case passes only if every assertion meets
its threshold (default 1.0). An assertion neither reliably green nor red is
flagged `~flaky`. With fewer runs on disk than `samples`, the case is
`INCONCLUSIVE` (or `FAIL`, if a run it has already fails).

Every path a case names (`runs:`, `schema.ref`, judge `anchors[].output`) is
relative to the suite directory and must stay inside it once `..` and symlinks
are resolved. A path that leaves the suite fails that case; Litmus never reads
it, or sends it to a judge.

## AgentRun (what the engine grades)

Produced by an adapter (`litmus capture`) or hand-authored. All fields optional
except whatever your assertions read.

```json
{
  "output": { "individuals": [ ... ] },
  "tool_calls": [ { "name": "finalize.py", "input": {} } ],
  "final_text": "…",
  "transcript": "…",
  "cost_usd": 0.03, "tokens": 4200, "latency_ms": 5100,
  "meta": { "model": "sonnet-5", "skill_version": "1.6.0" }
}
```

`meta.model` is what `litmus matrix` groups by — tag every run with it.
It is also how the judge's no-self-grading check knows who produced the run: a
`judge` assertion is INCONCLUSIVE, with no judge call, when `meta.model` names
the judge model. Without `meta.model` the suite or case `target.model` is used;
with neither (or the placeholder `default`), the run is graded and Litmus prints
one warning. `litmus capture` sets `meta.model` to your `--model`, or, without
one, to the model the Claude CLI reports (kept as `meta.model_id` either way).

## JSONPath selectors

`$` root · `.field` · `[n]` (negative ok) · `[*]` wildcard · `..field` recursive
descent. That's the whole grammar — enough to pin any output contract.
