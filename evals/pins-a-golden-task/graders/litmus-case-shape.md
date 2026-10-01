---
type: regex
target: last_message
pattern: '"assert"\s*:\s*\['
weight: 2
---

The answer contains a litmus case: a JSON object with an `assert` array. An agent
without the skill has no reason to use this exact shape.
