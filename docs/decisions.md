# Decisions

Each entry is taken from the commit history, merged PRs, the CHANGELOG, SPEC.md
or the README. Where the record shows the decision but not the options weighed
against it, the entry says "alternative not recorded".

## 1. Mutation testing on top of `claude plugin eval`, not a separate eval harness

**Context.** litmus 0.1 and 0.2 were a red/green regression harness with their
own deterministic assertions, an LLM judge, a `calibrate` command and a matrix
runner. It was retired from the sous marketplace on 2026-10-02 because its
deterministic assertions could pass when they could never fail (four that
could not fail gave 1/1 green), and `claude plugin eval` covered the rest.

**Decision.** Pivot in 0.3.0 to mutation testing of eval suites: break the
plugin's prose on purpose and ask whether the suite notices. litmus drives
`claude plugin eval` through an adapter and does not run or grade evals
itself.

**Alternatives considered and why rejected.** Keep the 0.2 harness and fix its
assertions. Rejected in PR #13: the runner already runs and grades, so litmus
moved to the question the runner does not answer ("can this suite fail?").
The 0.2 engine, judge and examples were removed and stay in history at tag
`v0.2.0`.

**Consequences.** litmus depends on the runner's CLI flags and result format,
and re-implements its four deterministic grader types for the offline checks.
A grader it cannot translate is UNKNOWN, never PASS. A promptfoo adapter is
specified (SPEC section 4.3) and not built.

**Evidence.** [PR #13](https://github.com/OrenSegal/litmus/pull/13) (48b6b9b);
sous [PR #8](https://github.com/OrenSegal/sous/pull/8) (retirement); CHANGELOG
0.3.0; `docs/SCOPE.md`.

## 2. Deterministic operators; LLM-written mutants only as recorded manifests

**Context.** A mutation score is only comparable across runs if the same
mutants run each time.

**Decision.** All seven operators are deterministic: the same file gives the
same sites in the same order, and each mutant id ends in a hash of the patched
file. LLM-written mutants are accepted only as a recorded manifest
(`operator: "llm:<name>"`, the full patched file, the original file's SHA-256,
and how it was generated), replayed byte for byte. A mutant whose source file
changed since it was recorded is stale and reported INCONCLUSIVE without
running.

**Alternatives considered and why rejected.** Generating LLM mutants at run
time. SPEC section 2 allows LLM-written mutants but requires them to be
recorded before they run; it ships the recording format and replay path, not
a generator. The reason for not generating them is not written down beyond
that rule.

**Consequences.** `mutants.json` from any run can be replayed later (for
example after a model release). Operators only cover prose: hooks, scripts and
MCP servers are not mutated, so a plugin whose behaviour lives in a hook gets
little from litmus.

**Evidence.** SPEC.md section 2 and "LLM-written mutants"; README "Mutation
operators" and "Limits"; `tests/test_operators_mutants.py`; AGENTS.md (a new
operator needs a determinism test).

## 3. INCONCLUSIVE never counts as killed, and every run uses `--ablation none`

**Context.** A crashed, partial or rate-limited run, a baseline that was never
green, or a stale mutant cannot show that the suite caught anything.

**Decision.**
`mutation_score = killed / (killed + survived + inconclusive)`, so an
inconclusive mutant lowers the score instead of being dropped. `decided_score`
(killed over killed plus survived) is shown next to it and never gated on.
Every run, baseline included, passes `--ablation none`.

**Alternatives considered and why rejected.**
- Gating on `decided_score`: shown, never gated on. The reason is the
  invariant in AGENTS.md: INCONCLUSIVE never counts as killed.
- The runner's default two-arm mode: SPEC section 4.1 says the docs say
  ablation mode changes absolute scores, so mixing modes would compare unlike
  numbers.

**Consequences.** A flaky environment drags the score down rather than up.
The two-arm results a user already has are still used, by `litmus audit`,
which treats the no-plugin arm as a free "delete the whole plugin" mutant.

**Evidence.** SPEC.md sections 1, 4.1 and 6; AGENTS.md; README blockquote
under the intro; `tests/test_adapter_scoring.py`.

## 4. Judges are not calibrated

**Context.** A kill is counted when the suite's own grader, often an LLM
judge, scores the mutant red.

**Decision.** litmus does not check that judge against human labels. It
flags judge-only cases and rubrics that never say what fails
(`litmus vacuity`), and stops there.

**Alternatives considered and why rejected.** A `calibrate` command that
measured judge agreement with human labels existed in 0.2 (PR #5). It was
removed with the 0.2 engine in PR #13. Rebuilding it needs a labelled set and
paid judge runs, so it was not done.

**Consequences.** A kill can be judge noise and a survivor can be a lenient
judge. The README states this under "Limits".

**Evidence.** [PR #5](https://github.com/OrenSegal/litmus/pull/5) (7d8ef98);
[PR #13](https://github.com/OrenSegal/litmus/pull/13) (48b6b9b);
[PR #18](https://github.com/OrenSegal/litmus/pull/18) (5563338); README
"Limits".

## 5. Published runs used `--runs 1`

**Context.** SPEC section 6 and the README ask for `--runs 3` on any number
that gets published, because with one run a single flaky case can fake a kill
or a survival. (That advice was later withdrawn: under the mean-of-runs rule
more runs raise false kills. See SPEC section 6.)

**Decision.** All three paid runs on cited, and both rootcause runs
(2026-10-15 and 2026-11-06), used `--runs 1`, and the README says so next to
every result.

**Alternatives considered and why rejected.** `--runs 2` for cited run 2:
rejected because the dry run estimated $5.40 against a $5 cap. `--runs 3`:
the reason for not using it on the other runs is not recorded beyond cost
caps of $5 per run.

**Consequences.** The 36% on cited run 3 is a first reading, not a settled
score. The two kills that rest on one regex grader are the most exposed.

**Evidence.** README "Results", "Second paid run" and "Limits"; commit
3682244; reports under `docs/scores/`.
