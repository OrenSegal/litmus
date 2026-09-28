# Litmus

**Red/green CI for prompt-ware.** Test the behavior your scripts' unit tests can't reach.

Skills, system prompts, and tool definitions are real software now: prose, schemas and scripts, shipped to other people's machines. The scripts get tests. The **prose that actually steers the model gets none.** So nobody can answer *"did editing SKILL.md make the agent better or worse?"* except by vibes, and every model upgrade silently re-rolls the dice on every installed skill.

Litmus pins golden tasks, runs them against a change, and returns a red/green diff. Underneath it's a **verification harness for agent claims**: deterministic checks wrapped around model-graded output, so a model can't rubber-stamp its own work green (when Litmus knows which model produced the run; see below).

> **The load-bearing rule:** a green only ever comes from a check that *could have failed*. A judge (LLM-graded) verdict that can't be falsified against an anchor or a deterministic guardrail is reported `INCONCLUSIVE`, never `PASS`.

Full design: [`LITMUS_SPEC.md`](./LITMUS_SPEC.md). Lineage: this generalizes `signal-scout`'s hand-built `verify_sources.py`.

## Status

Full pipeline, **78 tests, all offline**: no model, no network, no API key. Grading consumes an `AgentRun` JSON artifact, and the engine itself never calls a model, which keeps it deterministic and testable. Two things do call a model, and only when you ask: `litmus capture`, and `judge` assertions when you pass `--judge claude`. Both run through the Claude CLI, which uses your `claude` login, or `ANTHROPIC_API_KEY` if you have set it. Litmus never reads the key itself.

```bash
git clone https://github.com/OrenSegal/litmus && cd litmus
python3 -m unittest discover -s tests -t .        # 78 passing, no deps
python3 -m litmus.cli run examples/signal-scout   # end-to-end, offline

pip install git+https://github.com/OrenSegal/litmus  # installs the `litmus` command (not on PyPI yet)
```

| Milestone | Shipped |
|---|---|
| M1 engine | pure grader, 11 deterministic assertions, sample-based pass-rates, gate ratchet |
| M2 capture + report | `claude-code` stream-json adapter (`litmus capture`), self-contained `--html` report |
| M3 judge | anchored calibration (pass and fail anchors required), `panel: N` majority vote over repeated calls of one judge, `--judge claude` on the CLI; INCONCLUSIVE until falsifiable |
| M4 matrix | `litmus matrix`: case × model grid, cross-model regression detection |
| M5 case study | `examples/signal-scout/` suite. Partial: it runs offline on captured runs, and per the spec it hasn't logged a real outcome yet |
| M6 index (prototype) | `litmus index` ranks models across suites. Tested on fixtures only; no public Hallucination Index run exists yet |
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
litmus index   <suite> [<suite> ...]       # rank models across suites (prototype)
litmus capture "<prompt>" --out run.json   # capture a live AgentRun via the Claude CLI
```

`run`, `gate`, `bless`, `matrix` and `index` take `--judge claude` to grade `judge` assertions with the Claude CLI (`claude -p`), and `--judge-model <id>` to pick the judge model (default `claude-haiku-4-5-20251001`). Without `--judge`, no judge is built, nothing is sent to a model, and every `judge` assertion is `INCONCLUSIVE`. If you ask for a judge and it can't run (no `claude` on PATH, not logged in, an empty reply), the command stops with the reason on stderr and exits 2 rather than reporting `INCONCLUSIVE`. Use the same `--judge` setting for `bless` and `gate`: a baseline blessed with a judge records judge `PASS`es, and a gate run without one sees `INCONCLUSIVE` there and reports a regression.

No self-grading is enforced: a judge never grades a run its own model produced. The producing model is the run's `meta.model`, or the suite or case `target.model` if the run has none. If it is the same model as `--judge-model` (compared after normalizing ids, so `claude-haiku-4-5-20251001` and `haiku-4.5` match, and a bare alias like `haiku` matches every haiku), the judge is not called and that assertion is `INCONCLUSIVE`. Note that the default judge is Haiku 4.5, so pass a different `--judge-model` when Haiku 4.5 is the model under test. If the producing model is unknown, the run is graded and one warning goes to stderr per command. The exact rule is in [`LITMUS_SPEC.md`](./LITMUS_SPEC.md) §6.

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
| `judge` | LLM-rubric. **`INCONCLUSIVE` unless you run with `--judge claude` (or pass a judge from Python), the judge model is not the model that produced the run, and the rubric has at least one pass and one fail anchor that the judge grades correctly** |

`resolves`/`grounded` take an injectable `Fetcher`, so the whole engine, grounding included, runs offline in tests via a `DictFetcher`.

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

Cases author in JSON (always) or YAML (with the optional `[yaml]` extra). See [`examples/signal-scout/`](./examples/signal-scout), Litmus's first case study, which ports `verify_sources.py`'s guarantees into a suite. `--reference` takes whatever `meta.model` label your runs carry; `examples/model-regression/` uses `opus-4.8` and `haiku-4.5`.

## Limitations

- **Judge agreement with a human is not measured yet.** Anchors prove a judge can tell one known pass from one known fail. They don't tell you how often it agrees with a careful human on real outputs. That number needs a labelled set, which is the next piece of work.
- **`panel: N` is not independent.** It repeats the same judge model and prompt N times, so it smooths sampling noise but shares every blind spot.
- **The judge's answer is read from the first line of its reply.** A first line containing the word PASS counts as PASS. The prompt asks for a single word, but a chatty reply could be misread.
- **`grounded` is lexical.** It checks that a claim's words appear on the fetched page, not that the page supports the claim. A page that mentions the words while contradicting them passes.
- **One capture adapter.** `litmus capture` only speaks the Claude Code CLI's stream-json output.
- **The index has never been run publicly.** It ranks whatever suites you hand it; there is no published leaderboard.

## Next

M1-M4 are in, M5 is partial and M6 is a prototype. Open threads: `agent-sdk` adapter, a hosted gate that runs the
matrix on every PR, a real public **Hallucination Index** run, and a panel of
truly independent judges (today `panel: N` repeats the same judge and prompt).

## License

MIT © Oren Segal
