# litmus design

litmus pins golden tasks for a skill, system prompt or tool definition, grades
what an agent actually did on them, and returns a red/green diff against a
baseline. This document describes how the engine decides what is green. The
README covers installation and day-to-day use.

---

## 1. The problem

A skill is prose, schemas and scripts. The scripts get unit tests; the prose,
which is what steers the model, usually gets none. That leaves three questions
without a checkable answer:

1. Did this edit to `SKILL.md` make the agent better or worse?
2. Does the skill still behave on a different model?
3. When a model grades the output, should anyone believe the grade?

litmus answers the first two with pinned cases and a baseline ratchet, and the
third with the rule in §2.

The checks in `resolves` and `grounded` generalize the source verification in
[signal-scout](https://github.com/OrenSegal/signal-scout)'s `verify_sources.py`,
and `examples/signal-scout/` is a suite for that skill.

---

## 2. The load-bearing rule

> **A green only ever comes from a check that could have failed.** A judge
> (LLM-graded) verdict that cannot be falsified against an anchor or a
> deterministic guardrail is reported `INCONCLUSIVE`, never `PASS`.

Everything below is an application of this rule: deterministic checks are
preferred, a check with nothing to check is `SKIP` or `INCONCLUSIVE` rather
than `PASS`, and a judge must prove it can tell a known pass from a known fail
before its verdict counts.

---

## 3. Data model

```
Suite       a directory of Cases, their captured runs, and an optional baseline
 └─ Case    one golden task: input, target, assertions[], samples, tags
AgentRun    the captured artifact of one execution
Assertion   a pure check over one AgentRun -> Verdict
Verdict     PASS | FAIL | INCONCLUSIVE | SKIP, with detail and evidence
AssertionResult  one assertion over a case's samples, with a pass-rate
CaseResult  every AssertionResult for a case, rolled up to one status
SuiteResult every CaseResult, diffable against a baseline
```

The engine only reads `AgentRun` JSON. It never asks a model to produce a run;
that is an adapter's job (§10). This keeps grading deterministic and testable
offline.

`AgentRun` (every field optional except what the case's assertions read):

```json
{
  "output": { "...": "the structured result the agent produced" },
  "tool_calls": [ { "name": "finalize.py", "input": {} } ],
  "final_text": "...",
  "transcript": "...",
  "cost_usd": 0.03, "tokens": 4200, "latency_ms": 5100,
  "meta": { "model": "sonnet-5" }
}
```

`meta.model` is what `matrix` groups runs by and what the no-self-grading check
(§6) compares against the judge.

---

## 4. Suites and cases

```
suite/
  suite.json               { "name", "target": {skill, model}, "defaults": {samples, target} }
  cases/*.json | *.yaml    one Case each (YAML needs the optional pyyaml extra)
  runs/<case-id>/*.json    AgentRun samples for that case
  runs/<case-id>.json      ...or a single sample
  *.schema.json            referenced by `schema: { ref: ... }`
  baseline.json            written by `litmus bless`
```

A case's runs come from its explicit `runs:` list, else `runs/<id>/*.json`,
else `runs/<id>.json`. A case's `target` is the suite target merged with its
own.

Every path a suite names (`runs:`, `schema.ref`, judge `anchors[].output`, and
the `runs/<case-id>` convention) must resolve inside the suite directory after
`..` and symlinks are followed. A path that leaves the suite fails that case,
and the file is never read or sent to a judge.

A malformed suite, case or baseline file is an input error (exit 2), not a red
result. A malformed run file fails only its case.

---

## 5. Assertion catalog

Each `assert` entry is a single-key object: the key names the assertion, the
value is its config. An unknown name, or a config that makes the assertion
raise, is a `FAIL`.

### Deterministic

| Assertion | Config | `PASS` when |
|---|---|---|
| `must_run` | `"tool"` or `{tool, args?, before?, after?}` | the tool was called (with a superset of `args`, before or after another tool) |
| `ordering` | `{first, then}` | `first` was first called before `then` |
| `must_not` | `{tool}`, `{field}` or `{phrase, in?}` | the tool was never called, the JSONPath matches nothing, or the phrase is absent (case-insensitive) from the field named by `in`: `final_text` (default), `transcript` or `output` |
| `schema` | `{path?, schema}` or `{path?, ref}` | every value at `path` validates against a JSON Schema subset (§12) |
| `equals` | `{path, value}` | every value at `path` equals `value`; no match is a `FAIL` |
| `contains` | `{path, value}` | some string at `path` contains `value` |
| `matches` | `{path, pattern, timeout?}` | some string at `path` matches the regex; the search is capped at `timeout` seconds (default 2) and a timeout is a `FAIL` |
| `count` | `{path, op, value}` | the number of matches at `path` satisfies `op` (`>=`, `<=`, `==`, `!=`, `>`, `<`) |
| `budget` | `{cost_usd?, tokens?, latency_ms?}` | every listed metric is within its cap; missing telemetry is `INCONCLUSIVE`, an empty or unknown key is a `FAIL` |
| `resolves` | `"path"` or `{path}` | every http(s) URL at `path` returns a status below 400; a bot-walled host is `INCONCLUSIVE`; no URLs is `SKIP` |
| `grounded` | `{claim, source, threshold?}` | each claim's distinguishing words appear on its fetched source page (word overlap at or above `threshold`, default 0.15) |

`grounded` pairs claims and sources by position, so unequal counts are a
`FAIL`. A source that is not an http(s) URL, or is bot-walled, is
`INCONCLUSIVE`. `resolves` and `grounded` fetch through an injectable
`Fetcher`, so tests run them offline.

### Judge

| Assertion | Config | `PASS` when |
|---|---|---|
| `judge` | `{rubric, anchors, panel?}` | every guardrail in §6 holds and the panel majority says the output meets the rubric |

Push every check that can be deterministic down to a deterministic assertion.
Most "quality" requirements are a forbidden field, a schema or a resolvable
citation in disguise.

---

## 6. Trust architecture

A judge is a model, and an unanchored model grade can rubber-stamp anything.
A `judge` assertion is `PASS` only if all four guardrails hold.

1. **Anchored calibration.** The rubric must carry at least one anchor with
   `expect: pass` and one with `expect: fail`. Without both, the assertion is
   `INCONCLUSIVE` and the real output is never graded: a judge that always
   says PASS agrees with any pass-only set, and one that always says FAIL agrees
   with any fail-only set. Before grading the real output, the judge grades
   every anchor. If it misgrades one, its verdict is void and the assertion is
   `INCONCLUSIVE`.
2. **Judge panel.** `panel: N` (default 1) calls the judge N times on the real
   output; a strict majority of PASS votes is a `PASS`, and a tie is a `FAIL`.
   The bundled `ClaudeJudge` is prompted to refute: look for a concrete
   violation and answer FAIL, or PASS only if it finds none. The N calls use the
   same model and prompt, so they are repeated samples, not independent judges.
3. **Deterministic floor.** A case's status is the worst of its assertions, so
   a judge `PASS` can never outweigh a deterministic `FAIL` on the same case.
4. **No self-grading.** The judge sees only `{artifact, rubric}`, never who
   produced it. Before any judge call, anchors included, the engine compares the
   judge's model with the model that produced the run: the run's `meta.model`,
   else the suite or case `target.model`. If they are the same model, the judge
   is not called and the assertion is `INCONCLUSIVE` with a `self-grading:`
   reason. This is a property of each run, so a `matrix` suite holding runs from
   several models leaves only the judge's own runs ungraded.

Model ids are equal after normalizing both: lowercase and trim; keep the part
after the last `/`; drop a Bedrock `<region>.anthropic.` prefix and `-vN:M`
suffix, then `-latest`; drop a `-YYYYMMDD` or `@YYYYMMDD` date; turn `.` into
`-`; drop a leading `claude-`; put name words before version numbers. So
`claude-haiku-4-5-20251001`, `anthropic/claude-haiku-4-5` and `haiku-4.5` are
one model, and `claude-3-5-sonnet` equals `sonnet-3.5`. A bare alias with no
version (`haiku`, `sonnet`, `opus`) matches every model of that family.

If the producing model is unknown (no `meta.model`, or the placeholder
`default`, and no `target.model`), or the judge reports no model, the check
cannot run. The run is graded and one warning is printed per command.

**Wiring.** The engine grades only with a judge its caller passes in. The CLI
builds one only with `--judge claude` (model from `--judge-model`, default
`claude-haiku-4-5-20251001`). Without it, every `judge` assertion is
`INCONCLUSIVE` and no model is called. A requested judge that cannot give a
verdict (CLI missing, non-zero exit, empty or unparseable reply) stops the run
with exit 2; it never becomes a verdict. The verdict is the first word of the
reply's first non-empty line, which must be PASS or FAIL.

---

## 7. Non-determinism

Model output is stochastic, so litmus asserts invariants over samples rather
than exact strings.

- A case declares `samples: N` (default 1) and is graded over the runs on disk.
- Each assertion reports a pass-rate over the samples that were not `SKIP`. It
  is `PASS` only when every such sample passed; otherwise it is `FAIL` if any
  sample failed, else `INCONCLUSIVE`. An assertion whose samples all `SKIP` is
  `SKIP`.
- An assertion with a pass-rate strictly between 0 and 1 is flagged flaky.
- A case is green when at least one assertion is `PASS` and the rest are `PASS`
  or `SKIP`. A case with fewer runs than its `samples` is `INCONCLUSIVE` unless
  it already `FAIL`s.
- Baselines store pass-rates, so `gate` can catch a drift on a case that is
  still green.

---

## 8. Judge calibration against humans

Anchors show a judge can separate one known pass from one known fail. They do
not measure how often it agrees with a careful human on real output.
`litmus calibrate` measures that from a JSONL file of human-labeled outputs:
recall and precision with FAIL as the positive class, and Cohen's kappa. Rows
produced by the judge's own model are excluded. `--min-kappa` turns the result
into a CI check. The labeling protocol is in
[`calibration/README.md`](calibration/README.md).

---

## 9. CLI

```
litmus run       <suite> [--html out.html]
litmus gate      <suite> [--baseline file] [--drift-tol 0.10] [--html out.html]
litmus bless     <suite> [--out file] [--force]
litmus matrix    <suite> [--models a,b] [--reference model]
litmus index     <suite> [<suite> ...]
litmus capture   "<prompt>" [--model id] [--cwd dir] [--out run.json]
litmus calibrate <labels.jsonl> [--out file] [--rejudge] [--min-kappa k] [--json]
litmus status    <suite>
```

`run`, `gate`, `bless`, `matrix`, `index` and `calibrate` take
`--judge claude [--judge-model id]` (§6).

Exit codes are the same for every command: **0** green or no regression,
**1** red (a case `FAIL`ed, a regression, `bless` refused, kappa below
`--min-kappa`), **2** could not evaluate (malformed input, a path outside the
suite, an unknown `--reference`, a judge or capture that could not run).

- **`gate`** is a ratchet. It fails on a regression: a case green in the
  baseline and not green now; an assertion whose pass-rate dropped by more than
  `--drift-tol` on a case green in both; an assertion that went from `PASS` to
  `FAIL`, even on a case already red; a case that went to `FAIL` from another
  non-green status; a new case that is not green; a baseline case missing from
  the current run. Fixes and new green cases never fail it. It warns when the
  baseline names another suite or was blessed with a different judge.
- **`bless`** writes the baseline, stamped with the litmus version and judge
  model. It refuses while any case is `FAIL` unless given `--force`.
- **`matrix`** groups each case's runs by `meta.model` and grades each group
  separately. With `--reference`, a case green on the reference model and not
  green on another is a cross-model regression.
- **`index`** ranks suites worst-first by share of green cases, with counts of
  failing and inconclusive cases.
- **`status`** reports what a green on a suite proves: how many runs carry the
  `litmus capture` stamp versus fixtures, cases with fewer runs than `samples`,
  `judge` assertions, and the judge the baseline was blessed with. The stamp is
  a field in the run file, so it records provenance; it does not prove it.

---

## 10. Adapters

Adapters produce `AgentRun` JSON; the engine consumes it. Two exist:

| Adapter | How a run is produced |
|---|---|
| on-disk runs | any tool, or a person, writes `AgentRun` JSON into the suite; the engine grades it as-is |
| `litmus capture` | runs `claude -p --output-format stream-json --verbose` with the prompt on stdin and folds the stream into an `AgentRun`, stamped `meta.captured_by` and `meta.captured_at` |

A failed capture (CLI missing, non-zero exit, timeout, no stream events) exits 2
and writes nothing. `meta.model` is the `--model` given, else the model the CLI
reports; the reported id is kept as `meta.model_id`.

What leaves the machine, and only when asked: `--judge claude` sends the rubric
and each artifact (anchors included) to `claude -p` over stdin, with tools
disabled, no MCP servers, no saved session and an empty temporary working
directory. `litmus capture` sends the prompt and runs the agent with whatever
tools the user's CLI settings allow. `resolves` and `grounded` fetch the
http(s) URLs found in a run's output.

---

## 11. Reports

- **Terminal:** one line per case, each non-passing assertion with the detail
  of its first non-passing sample, and a summary line
  (`N/M green · F failing · I inconclusive · S skipped`). Colour is off when
  stdout is not a terminal or `NO_COLOR` is set.
- **HTML** (`--html` on `run` and `gate`): a single self-contained file with
  the same content, light and dark themes, no external assets.
- **Gate:** regressions, new failing, removed, fixes, new green, still red.
- **Matrix:** a case × model grid of statuses.

---

## 12. Non-goals

- **Running models during grading.** The engine is pure; only `capture` and the
  opt-in judge call a model.
- **Hosting.** litmus stores nothing outside the files you point it at and
  sends nothing anywhere except as listed in §10.
- **Other capture formats.** `capture` speaks only the Claude CLI's
  stream-json; any other harness can write `AgentRun` JSON directly.
- **Full JSON Schema or JSONPath.** `schema` supports `type`, `required`,
  `properties`, `additionalProperties`, `items`, `enum`, `minItems`,
  `maxItems`, `minimum`, `maximum`, `minLength` and `maxLength`. JSONPath
  supports `$`, `.field`, `[n]`, `[*]` and `..field`.
- **Semantic grounding.** `grounded` is lexical: it checks that a claim's words
  are on the page, not that the page supports the claim.
- **Independent judges.** `panel: N` repeats one model and prompt.
- **Runtime dependencies.** The engine is stdlib-only; YAML cases need the
  optional `pyyaml` extra.
