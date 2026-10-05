---
name: find-ideas
description: Turn a research direction into a few ranked, novel, testable ideas
---
The item is a research direction. Turn it into concrete research ideas that a single
agent can test with modest compute in a few hours.

1. Search for recent work on the direction (arXiv, Semantic Scholar, conference pages).
   Save what you read to `literature.md`: title, authors, year, link, one line on the finding.
2. Propose 5–8 candidate ideas. Each must be a falsifiable claim with a clear experiment,
   not a topic.
3. For each candidate, search specifically for prior work that already did it. Drop any
   idea that is already published. Record what you checked.
4. Score the survivors on novelty, feasibility on one GPU (or CPU) in under 4 hours, and
   how interesting the result would be either way. Write the ranking to `ideas.md`.
5. Spawn the top 3 as new items. For each, the title is the claim in one line and the body
   contains: hypothesis, proposed experiment, baseline, metric, what result would refute it,
   and the closest prior work with links. If the idea compares systems, name the budget
   they will be matched on (tokens, calls or time).

If nothing survives the novelty check, verdict "fail" with notes on what you tried.
