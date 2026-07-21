# Litmus — Product & Design Spec

> Red/green CI for prompt-ware. Test the behavior your scripts' unit tests can't reach.

**Status:** design spec (M0). No code yet — review gate before build.
**Author:** Oren Segal · **License:** MIT · **Repo:** `github.com/OrenSegal/litmus`
**Lineage:** generalizes `signal-scout/scripts/verify_sources.py` — deterministic checks wrapped around self-graded model output.

---

## 0. One line

Litmus pins golden tasks for a skill (or system prompt, or tool definition), runs them against a change — an edit, a model upgrade, a new dependency — and returns a **red/green diff**. Underneath the wedge it is a general **verification harness for agent claims**: deterministic checks wrapped around self-graded model output, so a model can never rubber-stamp its own work green.

Tagline options: *"Did editing SKILL.md make the agent better or worse? Stop guessing."* · *"pytest for the prose that steers your agent."*

---

## 1. The missing layer

Skills are real software now: **prose + schemas + scripts**, shipped to other people's machines through marketplaces. The scripts get unit tests. The **prose — the part that actually steers the model — gets zero.**

Three unanswered questions today, all answered only by vibes:

1. *"Did my edit to SKILL.md make the agent better or worse?"* — no red/green, no diff, no gate.
2. *"Does this skill still work on the new model?"* — **every model upgrade silently re-rolls the dice on every installed skill.** Opus 4.8 → Sonnet 5 → Fable 5, each a fresh, untested roll.
3. *"Is the eval itself trustworthy?"* — the thing grading the output is a model, and **a model scoring its own work rubber-stamps it.** Self-graded `evidence_quality: 9/10` is worth nothing.

Every skill author ships untested behavior. Anthropic's marketplace, the OpenCode/Cowork/Codex ecosystems — all missing this layer. Whoever builds "pytest for skills" owns it.

---

## 2. Why the shape is a *verification* harness, not just a test runner

The naive build is "a script that runs golden tasks and diffs." That is 1x. The 10x is the **trust architecture**, because the hard part isn't running tasks — it's *believing the grade*.

`verify_sources.py` already solved the GTM-specific instance: it never lets a self-graded `evidence_quality` score be the last word. It anchors every claim to something checkable — does the URL resolve, do the cited words actually appear on the page — and it is *page-length-invariant, bot-wall-aware, and self-healing* (`--apply`) so the guarantee doesn't depend on the agent behaving afterward.

Litmus generalizes exactly that discipline:

> **A green only ever comes from a check that could have failed.** Every judge (LLM-graded) verdict must be falsifiable against an anchor or a deterministic guardrail — or it is reported `INCONCLUSIVE`, never `PASS`.

That single rule is the product. It's why Litmus is a *verification* harness and why it generalizes past skills to **any agent claim** (layer 2, §12). `signal-scout` becomes Litmus's first case study, not the other way around.

---

## 3. The two layers

| | Layer 1 — the wedge | Layer 2 — the general thing |
|---|---|---|
| **What** | Regression CI for skills | Verification harness for agent claims |
| **User** | Every skill/plugin/prompt author | Every team shipping agent output as product |
| **Sells on** | "stop shipping untested prose" | "prove your agent's claims, don't self-grade them" |
| **Instance** | Litmus test suites | `verify_sources.py` was the first one, hand-built |

Ship Layer 1. Let Layer 2 pull through on the same engine.

---

## 4. Data model

```
Suite      ── a folder of Cases + a Baseline (last-green result)
 └─ Case   ── one golden task: input · target · assertions[] · samples · tags
Target     ── what runs the task: {skill|prompt|tool-def} × model × version
AgentRun   ── captured artifact of ONE execution (adapter-produced):
              { tool_calls[], final_output, transcript, cost, tokens, latency }
Assertion  ── a pure check over an AgentRun → Verdict
Verdict    ── PASS | FAIL | INCONCLUSIVE | SKIP  (+ detail, + evidence)
CaseResult ── verdicts for one Case across its samples (+ pass-rate)
SuiteResult── all CaseResults + target metadata → diffable against Baseline
```

The engine only ever sees `AgentRun` JSON. It never talks to a model to *produce* the run — that's the adapter's job (§9). This keeps the engine **pure and fully testable offline**, exactly like `verify_sources.py` is pure.

---

## 5. Assertion taxonomy — the heart

Two tiers. Deterministic assertions are trusted unconditionally. Judge assertions are trusted **only** through the guardrails in §6.

### Deterministic (no model, cheap, always trusted)

| Assertion | Checks | Generalizes |
|---|---|---|
| `must_run(tool, args?, order?)` | a tool/script was invoked (optionally with matching args, optionally before/after another) | — |
| `must_not(tool \| field \| phrase)` | a forbidden tool call, output field, or phrase never appeared (e.g. *"must not invent an `opener` for a Segment"*) | — |
| `schema(path, json-schema)` | output at JSONPath validates against a schema | signal-scout's required-fields |
| `equals / contains / matches(path, expr)` | deterministic value / substring / regex at a JSONPath | — |
| `resolves(path)` | every cited URL resolves — bot-wall-aware, Wayback fallback | **`verify_sources.py` link check** |
| `grounded(claim_path, source_path)` | cited claim's distinguishing words actually appear on the fetched source (page-length-invariant word overlap) | **`verify_sources.py` evidence match** |
| `budget(cost \| tokens \| latency ≤ X)` | run stayed within envelope | — |
| `count(path, op, n)` | e.g. "≥ 3 individuals, ≤ 10 total" | — |

### Judge (LLM-graded — untrusted until anchored)

| Assertion | Checks |
|---|---|
| `judge(rubric, anchors[], panel?)` | a rubric criterion an LLM must grade (*"the opener is genuinely personalized to the person's post, not a mail-merge"*) — subject to every guardrail in §6 |

Design rule: **push everything you can down to deterministic.** A judge assertion is the last resort, only for genuinely subjective quality. Most "AI quality" is actually a deterministic invariant in disguise (a forbidden field, a schema, a resolvable citation).

---

## 6. The trust architecture (the moat)

Every eval tool on the market has the same silent failure mode: *the judge is a model, and models rubber-stamp.* Litmus makes a judge verdict **falsifiable or void**. Four guardrails, all required for a judge `PASS`:

1. **Anchored calibration.** Every rubric ships with pinned pass/fail exemplars. Before grading the real output, the judge re-grades the anchors. **If it misgrades a known anchor, its verdict on the real case is void → `INCONCLUSIVE`, never `PASS`.** A judge that can't tell the fixed-good from the fixed-bad doesn't get to bless anything.
2. **Adversarial panel.** N independent judges (prompted to *refute*, not confirm); majority rules; **ties and disagreement default to `FAIL`.** (Directly reuses the workflow adversarial-verify pattern.)
3. **Deterministic floor.** A judge `PASS` can never override a deterministic `FAIL` on the same case. Checkable truth outranks opinion.
4. **No self-grading.** The judge model is decoupled from the target model, and the judge sees only `{artifact, rubric}` — never "you produced this." A model may not grade its own homework.

> **Invariant:** green comes only from checks that could have failed. Anything a self-grading model could have waved through is reported, not counted.

This is the generalization of "never let the self-graded score be the last word." It is the reason Litmus is defensible where a thin test-runner is not.

---

## 7. Non-determinism is a first-class citizen

Prose-ware is stochastic — a runner that asserts exact strings is useless. Litmus asserts **invariants over samples**:

- Each case declares `samples: N` (default 3). The case runs N times.
- Assertions report a **pass-rate**; the case passes if pass-rate ≥ its `threshold` (default 1.0 for deterministic, tunable for judge).
- A case whose pass-rate is neither ~0 nor ~1 is **flaky** — surfaced explicitly (this is the "find flaky tests" problem, built in, not bolted on).
- Baselines store pass-rates, so the gate can catch a *drift* (0.95 → 0.70) that a single run would miss.

---

## 8. Run modes (CLI)

```
litmus run     suite/            # run, evaluate, print red/green table
litmus gate    suite/ --baseline # CI mode: diff vs baseline, exit 1 on any regression
litmus matrix  suite/ --models opus-4.8,sonnet-5,haiku-4.5   # the "model upgrade" answer
litmus bless   suite/            # accept current run as new baseline (guardrailed*)
litmus index   suites/*          # aggregate → Hallucination Index (§12)
```

- **`gate`** is the ratchet: a regression = a case that was green and is now red, OR a pass-rate drop past tolerance. The baseline failure count may only shrink (same discipline as Shelfie's arch-lint ratchet). Non-zero exit fails the PR.
- **`bless`** *cannot* bless a case with a live deterministic `FAIL` — you can't paper over a broken citation by updating the snapshot. (Guardrail borrowed from `jest -u`'s worst footgun, closed.)
- **`matrix`** is the headline feature for the "every upgrade re-rolls the dice" pain: one command, a model × skill-version heatmap of what regressed.

---

## 9. Adapters — the integration boundary

The engine consumes `AgentRun` JSON. Adapters *produce* it. This boundary is deliberate: it keeps the graded core pure (like `verify_sources.py`) and lets Litmus test any harness that can emit the schema.

| Adapter | How it captures a run | Status |
|---|---|---|
| `transcript` | loads a pre-captured `AgentRun` JSON (offline; what the engine's own tests use; what CI uses after a run already happened) | **v0.1 — required** |
| `claude-code` | `claude -p --output-format stream-json` with the skill loaded; parse `tool_use` events + final message → `AgentRun` | v0.2 |
| `agent-sdk` | drive the Claude Agent SDK, capture tool calls programmatically | v0.3 |
| `generic` | any external harness writes the `AgentRun` schema; Litmus grades it | v0.3 |

`AgentRun` schema is the stable contract; adapters are swappable. Live capture is never on the critical path of the graded core.

---

## 10. Reports

- **Terminal**: red/green table, regressions first, flaky flagged, exit code.
- **HTML artifact**: self-contained, theme-aware (reuse the signal-scout report aesthetic + trust-mark footer). Shows per-case verdicts, judge anchor-calibration status, and the *evidence* behind each fail (the dead URL, the failing tool-call, the judge transcript).
- **Diff view**: `regressions[] · fixes[] · still-red[] · new[]` vs baseline.
- **Matrix**: model × version heatmap.

Every fail is **explainable** — you see the artifact and the exact check that tripped, never just a score.

---

## 11. Dogfood (the tail eats itself)

Two levels, both shipped:

1. The engine has a deterministic **pytest suite** (pytest for the pytest-for-skills). Runs green offline, no API — proves the core the way `verify_sources.py` is provable.
2. Litmus ships a **Litmus suite for its own `SKILL.md`** — the skill that teaches an agent to author suites is itself pinned by golden cases. Living proof of the concept, and the canonical example.

---

## 12. Growth loop, GTM & moat

Follows signal-scout's decided discipline: **skill = distribution, not revenue; service-first; freeze new mechanisms until real outcome data exists.**

**Growth loop — the Hallucination Index.** Run Litmus across popular *public* skills × current models and publish a recurring leaderboard: *which shipped skills regress, on which model, this week.* This is (a) the marketing engine, (b) the layer-2 credibility proof, and (c) a corpus flywheel no competitor can clone late. It's lifted straight from signal-scout's own moat ranking (*recurring index > trust mark > engine-as-lead*).

**Moat ranking (highest → lowest):**
1. **Regression-corpus flywheel** — every run of every user's suite is labeled behavioral data. Compounds. Uncopyable late.
2. **Recurring Hallucination Index** — public, habitual, cited.
3. **Trust architecture** (anchored judge, §6) — the hard-to-copy engineering.
4. **The CLI itself** — a lead, not a moat. Free and open.

**Monetization ladder (do NOT build yet — freeze until one real run has logged outcomes):**
- Free OSS: CLI + skill (`litmus run/gate/matrix`).
- Hosted CI: runs the matrix on every PR, dashboards drift, gates merges. $ / seat or / repo.
- Private index: a company's own skills benchmarked continuously against model releases.
- **Claim-verification API** (layer 2): `verify_sources.py` as a service — the general endpoint the essay points at. Biggest market, last to build.

**First case study:** `signal-scout` — port its hand-built `verify_sources.py` guarantees into a Litmus suite (`grounded`, `resolves`, `must_run finalize.py`, `must_not invent opener`, `schema`). Proof the general tool subsumes the specific one.

---

## 13. Packaging & naming

**Name:** Litmus. CLI: `litmus`. Instantly-legible red/green metaphor; a "litmus test" *is* pass/fail.

**Collision plan** (verify before publish): `litmus` on npm/PyPI is likely taken. Keep the CLI command `litmus`; publish under a distinct dist name — preferred `litmus-ci`, fallback scoped `@orensegal/litmus`. Repo stays `OrenSegal/litmus`.

**Layout** (host-agnostic, mirrors signal-scout 1.5+ Cowork/Codex/OpenCode compatibility):

```
litmus/
  pyproject.toml            # pip install litmus-ci → `litmus` entry point
  package.json              # npx installer (mirrors signal-scout bin/install.js)
  .claude-plugin/
    plugin.json · marketplace.json
  skills/litmus/
    SKILL.md                # teaches an agent to author + run suites
    references/             # assertion taxonomy, trust-architecture, case-format
    scripts/                # engine entry points
  litmus/                   # the Python engine (pure)
    case.py · assertions.py · runner.py · gate.py · report.py
    adapters/{transcript,claude_code,agent_sdk}.py
  examples/signal-scout/    # first case-study suite
  tests/                    # engine pytest suite (green offline)
  README.md · BUSINESS.md · COMPLIANCE.md · AGENTS.md · LICENSE
```

**Case file format** (`.litmus.yaml`):

```yaml
case: classifies-solo-maintainer-as-individual
target: { skill: signal-scout, model: sonnet-5 }
samples: 3
input: "https://example-dev-tool.com — solo maintainer active on GitHub & HN"
assert:
  - must_run:   finalize.py
  - schema:     { path: "$", ref: signal-scout.schema.json }
  - must_not:   { field: "$.segments[*].opener" }        # segments never get openers
  - equals:     { path: "$.individuals[0].type", value: "Individual" }
  - resolves:   { path: "$.individuals[*].source_url" }
  - grounded:   { claim: "$..evidence", source: "$..source_url" }
  - judge:
      rubric:  "The opener references a specific thing the person actually posted."
      anchors: [ { output: fixtures/good_opener.json, expect: pass },
                 { output: fixtures/mailmerge.json,   expect: fail } ]
      panel:   3
```

---

## 14. Build milestones

| M | Deliverable | Runs green without an API key? |
|---|---|---|
| M0 | **this spec** | — |
| M1 | engine core + `transcript` adapter + all deterministic assertions + pytest | **yes** |
| M2 | `run` / `gate` / `bless` + terminal report + baseline diff | yes (transcript fixtures) |
| M3 | anchored judge + panel + calibration | needs judge model |
| M4 | `matrix` + HTML report + `claude-code` live adapter | needs model |
| M5 | `examples/signal-scout/` case-study suite | partial |
| M6 | Hallucination Index prototype (one public run) | needs models |

**v0.1 non-goals:** hosted service, dashboards, the claim-verification API, non-Claude adapters, a GUI. Freeze per signal-scout discipline until M5 logs a real outcome.

---

## 15. Design principles

1. **Green only from falsifiable checks.** If a self-grading model could wave it through, it's `INCONCLUSIVE`, not `PASS`.
2. **Engine stays pure.** It grades `AgentRun` JSON; it never calls a model. Fully testable offline.
3. **Assert invariants, not strings.** Stochastic output demands sample-based pass-rates.
4. **Self-heal like `--apply`.** Where safe, fix/annotate rather than just flag.
5. **Deterministic outranks judged.** Checkable truth beats opinion, always.
6. **Host-agnostic.** Claude Code, Cowork, Codex, OpenCode — one `AgentRun` contract.
7. **Freeze until data.** No new mechanism until a real run logs a real outcome.

---

## 16. Open questions (for review)

- **`AgentRun` schema stability** — how reliably does `claude -p --output-format stream-json` expose tool-call args across versions? (De-risked by making `transcript` the primary adapter.)
- **Judge cost** — the panel multiplies calls; cap via "deterministic-first, judge only what's left."
- **Skill loading in headless mode** — confirm a skill can be force-loaded for a `-p` run.
- **Name collision** — lock the dist name before any publish.
- **Where does the corpus live** — flywheel data governance / privacy (COMPLIANCE.md), opt-in like signal-scout.

---

*Review gate: approve §5–6 (assertion taxonomy + trust architecture) and §13 (naming/packaging) and I build M1 — the pure engine + deterministic assertions + pytest, green offline, no API key.*
