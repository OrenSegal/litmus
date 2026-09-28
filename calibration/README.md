# Calibrating a judge against human labels

Anchors prove a judge can tell one known pass from one known fail. They don't say how often it agrees with a careful human on real output. `litmus calibrate` measures that, given a set of outputs a human has labeled.

## The labels file

JSONL, one sample per line:

```json
{"id": "opener-017", "artifact": {"opener": "..."}, "rubric": "the opener names something specific to the prospect", "human": "fail", "model": "claude-sonnet-5"}
```

- `artifact`: the output being graded, a string or any JSON value. The judge sees exactly this.
- `rubric`: one binary criterion. If one output needs three criteria, that's three rows.
- `human`: `pass` or `fail`, from the human labeler.
- `model` (optional): the model that produced the artifact. Rows produced by the judge's own model are left unjudged and excluded, the same no-self-grading rule the suites use. Rows without it can't be checked, and calibrate warns with a count of them.
- `judge` (optional): the judge's verdict. `--judge claude` fills it in; rows that already have one are kept unless you pass `--rejudge`.
- `judge_model`: written by `--judge` on each row it grades. If a kept verdict came from a different model than the current `--judge-model`, calibrate warns, since the metrics would mix two judges.

`id` is compared as a string, so `1` and `"1"` count as duplicates, and `--out` writes ids back as strings. Any other fields are written back unchanged. If the judge fails partway through, `--out` still gets every verdict made before the failure, so a rerun only pays for the rest.

## Protocol

1. **Collect real outputs.** Use output from the skill or agent you actually want the judge to grade, not examples written for the purpose. Keep anything used as a suite anchor out of the set.
2. **Size it for failures, not rows.** Recall is measured on human-labeled failures only, so their count sets the precision of the headline number. With a true recall of 0.8, the 95% Wilson interval is 0.49 to 0.94 on 10 failures, 0.67 to 0.89 on 50 and 0.71 to 0.87 on 100. Aim for 200+ rows with 50 to 100 failures.
3. **Label before the judge runs, and blind to it.** Leave out the `judge` field until labeling is done.
4. **Measure your own consistency.** Re-label a random 30 or more rows a day later without looking at the first pass. Your agreement with yourself is the ceiling; a judge can't be expected to agree with you more than you agree with yourself.
5. **Judge once, then iterate offline.**

   ```bash
   litmus calibrate labels.jsonl --judge claude --judge-model claude-sonnet-5 --out judged.jsonl
   litmus calibrate judged.jsonl            # free: no model calls
   litmus calibrate judged.jsonl --json     # metrics for a write-up
   ```

   Each unjudged row is one `claude -p` call.
6. **Read every disagreement.** For each, decide: judge wrong, label wrong, or rubric ambiguous. Fix wrong labels and rewrite ambiguous rubrics, then say so in the write-up. Don't quietly drop rows.
7. **Report the whole table:** judge model, litmus version, date, row count, failure count, the confusion matrix, recall, precision, kappa, your self-agreement, and the disagreement breakdown from step 6.

## Reading the numbers

FAIL is the positive class, because catching failures is the judge's job.

- **Recall**: of the outputs a human failed, the share the judge also failed. A low number means bad output gets through.
- **Precision**: of the outputs the judge failed, the share a human agrees with. A low number means false alarms.
- **Cohen's kappa**: agreement corrected for chance. On a set that's 90% passes, a judge that always says PASS scores 0.90 accuracy and a kappa of 0. Report kappa, not accuracy.

`--min-kappa 0.6` exits 1 below that value, so a judge can be re-checked in CI after a model or prompt change.

A write-up template is in [`WRITEUP.md`](./WRITEUP.md).
