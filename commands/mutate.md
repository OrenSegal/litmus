---
description: Check whether a plugin's eval suite can fail. Free vacuity and audit checks, then a mutation dry run.
argument-hint: <plugin-dir> [--max-mutants N] [--files GLOB]
---

Run the free litmus checks on the plugin the user named (default: the current
directory), using the copy bundled with this plugin. Split `$ARGUMENTS` into
the plugin directory and the mutation options (`--max-mutants`, `--files`):
`vacuity` takes only the directory and rejects the mutation options.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/litmus" vacuity <plugin-dir>
"${CLAUDE_PLUGIN_ROOT}/bin/litmus" mutate <plugin-dir> <mutation options> --dry-run
```

If the plugin has saved results under its eval directory, also run
`"${CLAUDE_PLUGIN_ROOT}/bin/litmus" audit <eval-dir>/results/*/aggregate-result.json`.

Report VACUOUS graders and NULL_GREEN cases first, then audit findings, then
the mutants a real run would try and its cost estimate.

Do not run `litmus mutate` without `--dry-run` unless the user explicitly asks
for a paid run after seeing the estimate; then add `--yes`, a
`--max-cost-usd` ceiling, and the `--allow-tools` the suite needs.
