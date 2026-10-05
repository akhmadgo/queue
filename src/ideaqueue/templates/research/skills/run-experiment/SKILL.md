---
name: run-experiment
description: Implement and run the experiment for one research idea, logging everything
---
The item is one research idea (see `idea.md`). Test it.

1. Write a plan to `experiments/PLAN.md`: setup, datasets, baseline, metric, number of
   seeds, and the result that would refute the hypothesis. Keep it within the compute
   budget in `idea.md` (default: one machine, under 4 hours).
2. Implement the code in `experiments/`. Pin dependencies in `experiments/requirements.txt`.
3. Run the baseline and the proposed method with at least 3 seeds each. Every run writes
   its config, seed, and metrics to `experiments/runs/<run-name>/metrics.json` and its
   full output to `experiments/runs/<run-name>/log.txt`.
4. Summarize in `experiments/RESULTS.md`: a table of mean ± std per method, which runs
   each number comes from, and whether the hypothesis held. A negative result is a valid
   result; report it plainly.

Rules that keep results honest:
- Split data into train, validation and a held-out test set before writing any method code.
  Tune only on validation. Evaluate on the test set once, at the end. The verify stage
  re-checks results on data you did not tune on; results that only hold on tuned data fail.
- Write general methods. Never special-case or hardcode answers for specific examples in
  the evaluation data, even if it raises the score.
- When comparing systems (for example one agent against several), give every system the
  same budget (tokens, model calls, wall-clock or GPU time) and report the budget used
  next to each result. A comparison at unequal budgets is not a result.
- Record the cost of each run (tokens, dollars, seconds) in its metrics.json.

Never type a number into RESULTS.md that is not in a metrics.json. Never delete a run
because it looked bad.

If notes from verify are handed to you, fix exactly those problems first and say how in
`experiments/RESULTS.md` under "Changes after review".
