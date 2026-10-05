# Research agenda: agent work

queue runs multi-stage agent pipelines: handoffs between agents, a second model verifying
the first, and retry loops when verification fails. Those are the parts of agent systems
that current research says matter most and are least understood. So queue doubles as a
testbed, and its research pipeline can write up what it finds.

The goal is rigorous, controlled experiments on how single and multiple LLM agents behave,
in the spirit of [autoresearch](https://github.com/karpathy/autoresearch): invest in the
setup so agents produce useful, checkable output.

## What we know

| Finding | Source | What queue does about it |
|---|---|---|
| Agents game metrics: hardcoding answers, editing tests. One frontier model cheated on 76% of impossible SWE tasks. | [ImpossibleBench](https://arxiv.org/pdf/2510.20270) | `run-experiment` forbids special-casing; `verify` searches for it |
| In autoresearch loops, one agent memorized evaluation answers while another wrote general code. Telling agents that held-out data exists removed the gap. | [Generalizers and Metric-Maximizers](https://arxiv.org/pdf/2607.18064) | `run-experiment` requires a held-out split, and says verify re-checks on untuned data |
| Multi-agent failures: 42% system design, 37% inter-agent misalignment (handoffs), 21% weak verification. | [MAST](https://arxiv.org/pdf/2503.13657) | Gates with written notes, a different model as verifier, attempt limits |
| At equal token or call budgets, multi-agent systems do not beat a single agent on reasoning tasks. | [Tran & Kiela](https://www.alphaxiv.org/abs/2604.02460), [equal inference cost](https://arxiv.org/pdf/2609.04217) | Skills require equal budgets for any comparison; `q stats` records cost per run |

These sources were found by search and have not all been read in full. The `find` and
`verify` stages should confirm each claim before it is cited.

## Experiments

Ordered by cost. Each can be sent to queue as an item that skips `find`:

```bash
# first line of the file is the title, the rest is the body
q add --stage experiment - < idea.md
```

### 1. Does a different-model verifier catch more errors than a same-model one?

- **Hypothesis:** a verifier from a different model family detects more planted errors in
  experiment folders than a verifier from the same family as the author.
- **Setup:** take finished experiment folders and plant known errors: fabricated numbers
  in RESULTS.md, fake citations, test-set tuning, hardcoded evaluation answers, an
  off-by-one in the metric. Run Claude-verifies-Claude, Codex-verifies-Claude and the
  reverse pairings.
- **Metric:** share of planted errors caught; false alarms on clean folders.
- **Budget:** same model calls and token cap per verifier.
- **Why first:** no GPU, clear metric, and the result decides queue's default design.

### 2. Do verify-and-retry loops converge?

- **Hypothesis:** most fixes after a failed verification land in the first retry; later
  retries mostly oscillate or introduce new problems.
- **Data:** queue's own `runs` table and verify notes across many items.
- **Metric:** per retry: problems fixed, problems introduced, flip-flops. Output: a
  recommended `max_attempts`.

### 3. What is lost in handoffs between stages?

- **Hypothesis:** passing only files and short notes loses information that the full
  transcript would carry, and the loss shows up as repeated work or contradictions.
- **Setup:** same pipeline, three handoff modes: notes only, files plus notes, full
  previous transcript.
- **Metric:** downstream stage success, repeated work, cost.

### 4. Pipeline vs one agent at equal budget, on long research tasks

- **Hypothesis:** the equal-budget result (single agent ≥ multi-agent) found on short
  reasoning tasks does not hold for long tasks where context overflows.
- **Setup:** direction → paper, done by queue's five-stage pipeline vs one agent with the
  same total token budget.
- **Metric:** verified claims per paper, citation accuracy, blind reviewer ratings.

### 5. Metric gaming across autoresearch tasks

- **Hypothesis:** the memorization gap between agents found on one task appears across
  many, and the held-out disclosure fixes it everywhere.
- **Setup:** 5–10 small autoresearch-style tasks (file + metric + time budget), Claude Code
  vs Codex, with and without held-out disclosure.
- **Metric:** gap between tuned and held-out score; count of special-cased answers.

## Harness work these experiments need

- [x] Per-run records: stage, attempt, agent, verdict, seconds, cost (`q stats`)
- [x] Skill rules for held-out data, no special-casing, equal budgets
- [ ] Token counts per run, not only cost
- [ ] Configurable handoff mode per stage (for experiment 3)
- [ ] Workers on a sandbox machine, for experiments that run code
- [ ] Budget limits per item and per day
