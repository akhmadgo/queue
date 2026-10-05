"""The worker loop: claim an item, run its stage's agent, move it on."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable

from .agents import Agent, build_agent
from .config import DONE, Pipeline, StageSpec
from .prompt import OUTCOME_FILE, build_prompt, load_skill, read_outcome
from .store import DONE as ITEM_DONE
from .store import PENDING, SHELVED, WAITING, Item, Store


def default_worker_name() -> str:
    return socket.gethostname()


class Engine:
    def __init__(self, pipeline: Pipeline, store: Store,
                 agent_factory: Callable = build_agent,
                 say: Callable[[str], None] = print):
        self.pipeline = pipeline
        self.store = store
        self.say = say
        self._agent_factory = agent_factory
        self._agents: dict[str, Agent] = {}

    def agent(self, name: str) -> Agent:
        if name not in self._agents:
            self._agents[name] = self._agent_factory(self.pipeline.agents[name])
        return self._agents[name]

    # -- entering stages ------------------------------------------------

    def submit(self, title: str, body: str = "", stage: str | None = None,
               parent: int | None = None) -> Item:
        stage = stage or self.pipeline.start
        return self.store.add(title, body, stage, status=self._entry_status(stage), parent=parent)

    def _entry_status(self, stage: str) -> str:
        return WAITING if self.pipeline.stages[stage].approval == "human" else PENDING

    def _move(self, item: Item, target: str, notes: str, kind: str) -> None:
        if target == DONE:
            self.store.update(item.id, stage=DONE, status=ITEM_DONE, notes=notes, worker=None)
            self.store.event(item.id, item.stage, kind, f"→ done. {notes}".strip())
            return
        self.store.update(item.id, stage=target, status=self._entry_status(target),
                          notes=notes, worker=None)
        self.store.event(item.id, item.stage, kind, f"→ {target}. {notes}".strip())

    def _retry(self, item: Item, reason: str) -> None:
        self.store.update(item.id, status=PENDING, worker=None)
        self.store.event(item.id, item.stage, "error", reason)

    # -- running --------------------------------------------------------

    def run_once(self, stages: list[str] | None = None, worker: str | None = None) -> Item | None:
        """Run one item through one stage. Returns the item, or None if nothing was pending."""
        worker = worker or default_worker_name()
        item = self.store.claim(stages or list(self.pipeline.stages), worker)
        if item is None:
            return None
        stage = self.pipeline.stages[item.stage]
        try:
            self._run_stage(item, stage)
        except BaseException as e:
            self._retry(item, f"interrupted: {type(e).__name__}")
            raise
        return self.store.get(item.id)

    def _run_stage(self, item: Item, stage: StageSpec) -> None:
        attempt = item.attempts.get(stage.name, 0) + 1
        if attempt > stage.max_attempts:
            self.store.update(item.id, status=SHELVED, worker=None)
            self.store.event(item.id, stage.name, "shelved",
                             f"{stage.name} failed {stage.max_attempts} times. Last notes: "
                             f"{item.notes}".strip())
            self.say(f"#{item.id} shelved at {stage.name}")
            return
        item.attempts[stage.name] = attempt
        self.store.update(item.id, attempts=item.attempts)

        skill = load_skill(self.pipeline.skills_dir, stage.skill)
        prompt = build_prompt(self.pipeline, stage, item, skill)
        (item.dir / OUTCOME_FILE).unlink(missing_ok=True)
        log_path = item.dir / ".queue" / "logs" / f"{stage.name}-{attempt}.log"
        (item.dir / ".queue" / "prompts").mkdir(parents=True, exist_ok=True)
        (item.dir / ".queue" / "prompts" / f"{stage.name}-{attempt}.md").write_text(prompt)

        self.say(f"#{item.id} {stage.name} (attempt {attempt}/{stage.max_attempts}) "
                 f"via {stage.agent}: {item.title}")
        self.store.event(item.id, stage.name, "started", f"attempt {attempt} via {stage.agent}")
        env = {"QUEUE_ITEM_ID": str(item.id), "QUEUE_STAGE": stage.name,
               "QUEUE_OUTCOME": str(item.dir / OUTCOME_FILE)}
        started = time.monotonic()
        with open(log_path, "a") as log:
            result = self.agent(stage.agent).run(prompt, item.dir, env, log, stage.timeout)
        seconds = time.monotonic() - started
        took = f"{seconds:.0f}s"
        if result.cost_usd is not None:
            took += f", ${result.cost_usd:.2f}"

        def record(verdict: str) -> None:
            self.store.record_run(item.id, stage.name, attempt, stage.agent, verdict,
                                  seconds, result.cost_usd)

        if not result.ok:
            record("error")
            self._retry(item, f"agent failed ({result.error}, {took}); see {log_path.name}")
            self.say(f"#{item.id} {stage.name} agent failed: {result.error}")
            return

        outcome = read_outcome(item.dir)
        if outcome.problem:
            if stage.is_gate:
                record("error")
                self._retry(item, f"{outcome.problem} ({took})")
                self.say(f"#{item.id} {stage.name}: {outcome.problem}")
                return
            # A plain stage that finished cleanly but wrote no outcome counts as a pass.
            outcome.verdict = "pass"

        record(outcome.verdict)
        if outcome.verdict == "fail":
            target = stage.fail if stage.is_gate else stage.name
            self._move(item, target, outcome.notes, f"fail ({took})")
            self.say(f"#{item.id} {stage.name} failed → {target}")
            return

        target = stage.pass_ if stage.is_gate else stage.next
        if outcome.spawn and target != DONE:
            children = [self.submit(s["title"], s.get("body", ""), target, parent=item.id)
                        for s in outcome.spawn]
            ids = ", ".join(f"#{c.id}" for c in children)
            self.store.update(item.id, stage=DONE, status=ITEM_DONE, notes=outcome.notes,
                              worker=None)
            self.store.event(item.id, stage.name, f"pass ({took})", f"split into {ids}")
            self.say(f"#{item.id} {stage.name} split into {ids}")
            return
        self._move(item, target, outcome.notes, f"pass ({took})")
        self.say(f"#{item.id} {stage.name} passed → {target}")

    def run(self, stages: list[str] | None = None, worker: str | None = None,
            once: bool = False, poll: float = 3.0) -> None:
        """Drain loop. With once=True, stop when nothing is pending."""
        worker = worker or default_worker_name()
        released = self.store.release_stale(worker)
        if released:
            self.say(f"put back {released} item(s) left running by an earlier {worker} worker")
        waiting = False
        while True:
            item = self.run_once(stages, worker)
            if item is not None:
                waiting = False
                continue
            if once:
                return
            if not waiting:
                self.say("queue empty, waiting for items (Ctrl-C to stop)")
                waiting = True
            time.sleep(poll)
