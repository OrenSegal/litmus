---
description: Author a new litmus case (a golden task plus assertions) in a suite, then run it to prove it can go red.
argument-hint: <suite-dir> <case-id> [what the case should check]
---

Add one new case to a litmus suite. Arguments: `$ARGUMENTS` (the suite
directory, the case id, then optionally what the case should check).

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/litmus/references/case-format.md` and
   `${CLAUDE_PLUGIN_ROOT}/skills/litmus/references/assertions.md` first.
2. Look at the suite's existing `cases/*.json` and follow their style.
3. Write `cases/<case-id>.json` with an `id`, the `input` task, and
   assertions. Prefer deterministic assertions (`must_run`, `ordering`, `must_not`,
   `schema`, `equals`, `count`, `contains`, `matches`, `resolves`,
   `grounded`, `budget`). Use `judge` only for genuinely subjective quality,
   and only with both a pass and a fail anchor.
4. Every path in the case (`runs:`, `schema.ref`, judge `anchors[].output`) is
   relative to the suite directory and must stay inside it.
5. If there is no captured run yet, do not invent one and present it as real.
   Either tell the user to capture it:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/litmus" capture "<task prompt>" --model <model> --out <suite>/runs/<case-id>/<model>.json
   ```

   (this runs the agent and costs money), or, if they want an offline fixture,
   write one under `runs/<case-id>/` and say plainly that it is hand-written.
6. Prove the case can fail: run it, then make one assertion deliberately wrong
   (or point it at a fixture that violates it) and confirm the case goes red,
   then restore it.

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/litmus" run <suite-dir>
   ```

A case that cannot go red proves nothing. Do not bless the baseline as part of
this command; leave that to the user.
