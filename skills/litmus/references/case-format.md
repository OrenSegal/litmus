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

`samples` runs the case N times over its N captured runs; each assertion reports
a pass-rate and a case passes only if every assertion meets its threshold
(default 1.0). An assertion neither reliably green nor red is flagged `~flaky`.

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

## JSONPath selectors

`$` root · `.field` · `[n]` (negative ok) · `[*]` wildcard · `..field` recursive
descent. That's the whole grammar — enough to pin any output contract.
