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

Never type a number into RESULTS.md that is not in a metrics.json. Never delete a run
because it looked bad.

If notes from verify are handed to you, fix exactly those problems first and say how in
`experiments/RESULTS.md` under "Changes after review".
