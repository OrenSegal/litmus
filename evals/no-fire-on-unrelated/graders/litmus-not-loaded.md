---
type: tool_used
tool: Skill
input_match: '"skill"\s*:\s*"(?:[\w-]+:)?litmus"'
min: 0
max: 0
arm: both
weight: 1
---

The litmus skill was not loaded for a request that has nothing to do with testing
prompt-ware. Scored in both arms, so a false trigger lowers the plugin arm.
