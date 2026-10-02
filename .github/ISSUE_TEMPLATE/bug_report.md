---
name: Bug report
about: litmus graded something wrong, crashed, or exited with the wrong code
labels: bug
---

**What happened**

<!-- The command you ran and its full output, including the exit code (`echo $?`). -->

**What you expected**

**Smallest suite that reproduces it**

<!-- A case JSON and the AgentRun JSON it grades, trimmed down. Remove anything private. -->

**Environment**

- `litmus --version`:
- `python3 --version`:
- OS:
- Installed via: pip / plugin `bin/litmus` / checkout

<!-- For a security problem (reading files outside a suite, sending data to a model you did not pick), do not file an issue. Use a private advisory: see SECURITY.md. -->
