---
description: Gate a litmus suite against its blessed baseline; fails only on regressions, never on fixes.
argument-hint: <suite-dir> [--baseline baseline.json] [--drift-tol 0.10] [--judge claude]
---

Diff the current result of a litmus suite against its baseline, using the
engine bundled with this plugin:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/litmus" gate $ARGUMENTS
```

The baseline defaults to `<suite>/baseline.json`. If none exists the command
exits 2 and says so; offer to create one with
`"${CLAUDE_PLUGIN_ROOT}/bin/litmus" bless <suite>`, but only after the user has
seen the current run, because blessing records the current result as correct.

Report the gate verdict and every entry under `REGRESSIONS`,
`new failing` and `removed`. A regression is a case that was green and is
not, an assertion that went PASS to FAIL, a pass-rate drop beyond
`--drift-tol`, or a case missing from the current run. Fixes and new green
cases never fail the gate.

Read every `litmus: warning:` line on stderr aloud to the user. A warning that
the baseline is for another suite, or was blessed with a different judge, means
the comparison may not be meaningful.

Exit codes: 0 no regressions, 1 regressions, 2 could not evaluate.
Never re-bless to make a red gate green unless the user explicitly says the new
behaviour is the intended one.
