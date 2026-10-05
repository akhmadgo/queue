# queue

Run multi-stage pipelines with your own agents, on the machines you choose, without
babysitting them.

You describe a pipeline as stages. Each stage has a skill (instructions) and an agent (a
model you bring: Claude Code on your subscription, Codex, an API key, or any command). You
drop items in; workers move each item through the stages. Gate stages can send work back
with notes, and items that keep failing are shelved instead of looping forever.

The first pipeline turns a research direction into verified paper drafts:

```
find → experiment → verify ─pass→ write → review ─pass→ done
           ↑           │fail         ↑       │fail
           └───────────┘             └───────┘
```

## Quick start

```bash
uv tool install git+https://github.com/akhmadgo/queue
mkdir my-research && cd my-research
q init                           # research pipeline + skills
q "efficient long-context attention for small models"
q run                            # start a worker; Ctrl-C to stop
q ls                             # what's where
q show 3                         # one item's history
q stats                          # runs, pass/fail, time and cost per stage
```

Each item gets a folder under `.queue/items/` holding everything its agents produced, plus
the exact prompt and log for every run in `.queue/prompts/` and `.queue/logs/`.

## Concepts

| | |
|---|---|
| **item** | One thing moving through the pipeline. Has a folder that agents read from and write to. |
| **stage** | A skill plus where the item goes next: `next`, or `pass` and `fail` for a gate. |
| **skill** | `skills/<name>/SKILL.md`: a short header and instructions, the same format agents already use. |
| **agent** | `claude-code`, `codex`, or `command` (anything that reads a prompt on stdin). |
| **worker** | `q run`, optionally limited to some stages with `-s`. Run several, on different machines. |

## pipeline.toml

```toml
[agents.claude]
use = "claude-code"           # uses claude's own login
model = "opus"

[agents.checker]
use = "codex"

[stages.experiment]
skill = "run-experiment"
agent = "claude"
next = "verify"
max_attempts = 3              # shelve after 3 runs of this stage

[stages.verify]
skill = "verify"
agent = "checker"
pass = "write"
fail = "experiment"           # back with the verifier's notes

[stages.submit]
skill = "submit"
agent = "claude"
next = "done"
approval = "human"            # waits for `q approve <id>`
```

## How a stage finishes

The agent writes `.queue/outcome.json` in the item folder:

```json
{"verdict": "pass", "notes": "handoff for the next stage"}
```

`"fail"` on a gate sends the item to its `fail` stage with the notes; on a plain stage it
retries. A plain stage may add `"spawn": [{"title": ..., "body": ...}]` to split one item
into several (that's how `find` turns a direction into ideas).

## Safety

Agents run unattended, so they cannot stop to ask permission. Decide per agent what it may
do (`permission_mode`, `allowed_tools`, `sandbox`), and run workers that execute code
(like `experiment`) inside a sandbox or VM, not on a machine with your credentials.
Anything that leaves your machines, such as submitting a paper, should use
`approval = "human"`.

## Research agenda

queue is also a testbed for controlled experiments on how agents behave in multi-stage
systems. See [docs/RESEARCH.md](docs/RESEARCH.md).

## Status

v0.1: local workers sharing one SQLite file. Next: limits (budget per item, daily cap),
digests and notifications, and workers on other machines.

## License

MIT
