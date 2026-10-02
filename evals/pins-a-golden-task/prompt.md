---
name: pins-a-golden-task
description: A request to regression-test a skill should fire litmus and produce a litmus case with assertions.
tags: [trigger, authoring]
max_turns: 10
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

I keep editing my `release-notes` skill and I can't tell whether each edit makes
it better or worse. Pin a golden task for it so I get a red/green answer: when it
is given a diff that only touches tests and CI config, it must not write a
"Features" heading, and it must say there are no user-facing changes.

Show me the test case file in full. Don't run anything.
