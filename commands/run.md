---
description: Run a Litmus suite and report red/green per case, with the evidence for every failure.
argument-hint: <suite-dir> [--judge claude] [--html out.html] [--quiet]
---

Run the Litmus suite the user named, using the engine bundled with this plugin:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/litmus" run $ARGUMENTS
```

If no suite directory was given, look for one (a directory with a `cases/`
subdirectory, often under `tests/litmus/` or `examples/`) and ask before
running if there is more than one.

Then report, without softening it:

- the summary line (`N/M green · F failing · I inconclusive · S skipped`);
- every FAIL with its assertion name and the evidence the engine printed;
- every INCONCLUSIVE and why (a `judge` assertion run without `--judge` is
  always INCONCLUSIVE; that is expected, not a failure).

Exit codes: 0 means no case failed, 1 means at least one case FAILed, 2 means
the suite could not be evaluated (bad file, path outside the suite, judge or
CLI error). On exit 2, show the `litmus: error:` line and fix the cause; do not
report it as a red result.

Do not pass `--judge claude` unless the user asked for judging: it calls a
model and costs money.
