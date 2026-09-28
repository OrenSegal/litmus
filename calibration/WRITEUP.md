# How often does the judge agree with me? (template, not yet run)

Every blank below is filled from a real `litmus calibrate` run. Until then this file has no results in it.

## Setup

- Skill and rubric criteria graded: ___
- Where the outputs came from: ___
- Rows: ___, of which human-labeled failures: ___
- Judge: `--judge claude --judge-model ___`, litmus ___, run on ___
- Labeled by: ___, before the judge ran and without seeing its verdicts

## My own consistency

Re-labeled ___ rows a day later without looking. Agreed with myself on ___ of ___. The flips were mostly on ___, so I rewrote that rubric as: ___

## Results

|                | human FAIL | human PASS |
|----------------|-----------:|-----------:|
| **judge FAIL** | ___        | ___        |
| **judge PASS** | ___        | ___        |

- Recall (human failures the judge caught): ___
- Precision (judge failures I agree with): ___
- Cohen's kappa: ___
- Accuracy, for comparison only: ___

## The disagreements

___ rows disagreed. Judge wrong: ___. My label wrong: ___. Rubric ambiguous: ___.

Examples worth showing (one per category):

- ___

## What I changed because of this

- ___

## What this doesn't show

- One judge model and one prompt; another model or a reworded prompt needs its own run.
- One labeler. Agreement with a second person would be a stronger ceiling than self-agreement.
- ___
