# Security

- Report a vulnerability through GitHub's private advisory form on this repo, not a public issue.
- What litmus runs: `litmus mutate` without `--dry-run` copies the plugin to a temp directory and runs `claude plugin eval <copy> --trust-plugin` once for the baseline and once per mutant, as you, on your credential. `--trust-plugin` is passed because each copy is a new directory; only point litmus at plugins you would run yourself. `--scaffold` and `--allow-tools` are passed through only when you give them.
- `litmus vacuity`, `litmus audit` and `--dry-run` never run a model, and start no subprocess other than a time-boxed Python regex worker.
- In scope: a crafted suite, grader or mutants manifest that makes litmus write outside its output directory or the temp copy, read files outside the suite, or execute code. Manifests naming a path outside the suite root, or with patched content that does not match its hash, are rejected.
- Out of scope: what the plugin under test does inside `claude plugin eval`; see the runner's own isolation notes.
