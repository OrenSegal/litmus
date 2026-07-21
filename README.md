# Litmus

**Red/green CI for prompt-ware.** Test the behavior your scripts' unit tests can't reach.

Skills, system prompts, and tool definitions are real software now — prose + schemas + scripts, shipped to other people's machines. The scripts get tests. The **prose that actually steers the model gets none.** So nobody can answer *"did editing SKILL.md make the agent better or worse?"* except by vibes — and every model upgrade silently re-rolls the dice on every installed skill.

Litmus pins golden tasks, runs them against a change, and returns a red/green diff. Underneath it's a **verification harness for agent claims**: deterministic checks wrapped around self-graded model output, so a model can never rubber-stamp its own work green.

> **The load-bearing rule:** a green only ever comes from a check that *could have failed*. A judge (LLM-graded) verdict that can't be falsified against an anchor or a deterministic guardrail is reported `INCONCLUSIVE`, never `PASS`.

Full design: [`LITMUS_SPEC.md`](./LITMUS_SPEC.md). Lineage: this generalizes `signal-scout`'s hand-built `verify_sources.py`.

## Status

Full pipeline, **47 tests, all offline** — no model, no network, no API key. Grading consumes an `AgentRun` JSON artifact; the engine never calls a model, which is what keeps it deterministic and testable. Live capture and judging go through the Claude CLI's own auth (still no API key).

```bash
git clone https://github.com/OrenSegal/litmus && cd litmus
python3 -m unittest discover -s tests -t .        # 47 passing, no deps
python3 -m litmus.cli run examples/signal-scout   # end-to-end, offline

pip install litmus-ci                              # or install the `litmus` command
```

| Milestone | Shipped |
|---|---|
| M1 engine | pure grader, 11 deterministic assertions, sample-based pass-rates, gate ratchet |
| M2 capture + report | `claude-code` stream-json adapter (`litmus capture`), self-contained `--html` report |
| M3 judge | anchored calibration + adversarial panel; INCONCLUSIVE-until-falsifiable |
| M4 matrix | `litmus matrix` — case × model grid, cross-model regression detection |
| M6 index | `litmus index` — the Hallucination Index leaderboard |
| packaging | Claude Code plugin (`.claude-plugin/` + `skills/litmus/`), npm installer, CI dogfood |

## How it works

```
Suite ─ cases/*.json  +  runs/<case>/*.json (captured AgentRun samples)  +  baseline.json
 └─ Case ─ input + assertions[] + samples(N)
      └─ Assertion ─ pure check over an AgentRun → Verdict(PASS|FAIL|INCONCLUSIVE|SKIP)
```

```bash
litmus run     <suite> [--html out.html]  # evaluate, print red/green, exit 1 on any FAIL
litmus gate    <suite> --baseline b.json   # diff vs baseline, exit 1 ONLY on regressions
litmus bless   <suite>                     # snapshot current result as baseline (won't bless a live failure)
litmus matrix  <suite> --reference opus-4.8 # case × model grid; exit 1 on cross-model regressions
litmus index   <suite> [<suite> ...]       # Hallucination Index leaderboard
litmus capture "<prompt>" --out run.json   # capture a live AgentRun via the Claude CLI
```

Non-determinism is first-class: a case runs over N samples, each assertion reports a **pass-rate**, and anything neither reliably green nor reliably red is flagged **flaky**.

## Assertions (M1, all deterministic)

| | |
|---|---|
| `must_run` | a tool/script was invoked (optional args-subset, `before`/`after` order) |
| `must_not` | a forbidden tool call, output `field`, or `phrase` never appeared |
| `ordering` | tool A called before tool B |
| `schema` | output at a JSONPath validates (dependency-free JSON-Schema subset) |
| `equals` / `contains` / `matches` | deterministic value / substring / regex at a JSONPath |
| `count` | cardinality at a JSONPath (`>=`, `<`, `==`, …) |
| `budget` | cost / tokens / latency within envelope (missing telemetry → `INCONCLUSIVE`) |
| `resolves` | every cited URL resolves — bot-wall-aware (`verify_sources.py` link check) |
| `grounded` | cited claim's words actually appear on the fetched source, page-length-invariant |
| `judge` | LLM-rubric — **`INCONCLUSIVE` until a judge + anchors are wired (M3)** |

`resolves`/`grounded` take an injectable `Fetcher`, so the whole engine — including grounding — runs offline in tests via a `DictFetcher`.

## Case file

```json
{
  "id": "classify-solo-maintainer-as-individual",
  "assert": [
    { "must_run": "finalize.py" },
    { "schema": { "path": "$", "ref": "signal-scout.schema.json" } },
    { "equals": { "path": "$.individuals[0].type", "value": "Individual" } },
    { "must_not": { "field": "$.segments[*].opener" } }
  ]
}
```

Cases author in JSON (always) or YAML (with the optional `[yaml]` extra). See [`examples/signal-scout/`](./examples/signal-scout) — Litmus's first case study, porting `verify_sources.py`'s guarantees into a suite.

## Next

M1–M6 are in. Open threads: `agent-sdk` adapter, a hosted gate that runs the
matrix on every PR, and a real public **Hallucination Index** run. Direction and
moat: [`BUSINESS.md`](./BUSINESS.md).

## License

MIT © Oren Segal
