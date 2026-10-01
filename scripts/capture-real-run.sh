#!/bin/sh
# Capture one real AgentRun for a case, then grade the suite with it.
#
# This is the step that turns a fixture-only suite into evidence about a live
# agent. It calls the Claude CLI (your `claude` login or ANTHROPIC_API_KEY),
# so it costs money and is never run by the test suite or CI.
#
#   scripts/capture-real-run.sh <suite-dir> <case-id> <model> <skill-dir> [--yes]
#
#   suite-dir  e.g. examples/signal-scout
#   case-id    a case in <suite-dir>/cases/, whose "input" is the task prompt
#   model      passed to `claude --model` and recorded as meta.model
#   skill-dir  working directory the CLI runs in, where it finds the skill
#              under test (a checkout of that skill, not this repo)
#
# Writes <suite-dir>/runs/<case-id>/live-<model>.json (refuses to overwrite),
# then prints `litmus run` and `litmus status` for the suite. Nothing is
# blessed: if the live run is red, that is the result.
set -eu

here=$(cd -P -- "$(dirname -- "$0")" && pwd)
litmus="$here/../bin/litmus"

if [ "$#" -lt 4 ]; then
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
suite=$1 case_id=$2 model=$3 skill_dir=$4 yes=${5:-}

case_file=""
for ext in json yaml yml; do
  if [ -f "$suite/cases/$case_id.$ext" ]; then case_file="$suite/cases/$case_id.$ext"; fi
done
if [ -z "$case_file" ]; then
  # case ids need not match file names; search by id
  case_file=$(grep -l "\"id\": *\"$case_id\"" "$suite"/cases/*.json 2>/dev/null | head -n 1 || true)
fi
[ -n "$case_file" ] || { echo "no case $case_id in $suite/cases" >&2; exit 2; }
[ -d "$skill_dir" ] || { echo "skill dir not found: $skill_dir" >&2; exit 2; }

prompt=$(python3 - "$case_file" <<'EOF'
import json, sys
path = sys.argv[1]
if path.endswith((".yaml", ".yml")):
    import yaml
    doc = yaml.safe_load(open(path))
else:
    doc = json.load(open(path))
inp = doc.get("input")
if not isinstance(inp, str) or not inp.strip():
    sys.exit(f"{path}: the case has no string `input` to use as the prompt")
print(inp)
EOF
)

out="$suite/runs/$case_id/live-$model.json"
[ ! -e "$out" ] || { echo "$out exists; move it aside first" >&2; exit 2; }

echo "About to run a real agent session (this costs money):"
echo "  model:  $model"
echo "  cwd:    $skill_dir"
echo "  prompt: $prompt"
echo "  output: $out"
if [ "$yes" != "--yes" ]; then
  if [ ! -t 0 ]; then echo "not a terminal; pass --yes to confirm" >&2; exit 2; fi
  printf "Proceed? [y/N] "
  read -r answer
  case $answer in y|Y|yes) ;; *) echo "aborted"; exit 1 ;; esac
fi

mkdir -p "$suite/runs/$case_id"
"$litmus" capture "$prompt" --model "$model" --cwd "$skill_dir" --out "$out"

echo
"$litmus" run "$suite" || true
echo
"$litmus" status "$suite"
