"""Load and validate a pipeline.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PIPELINE_FILE = "pipeline.toml"
DONE = "done"


class ConfigError(Exception):
    pass


@dataclass
class AgentSpec:
    name: str
    use: str
    options: dict = field(default_factory=dict)


@dataclass
class StageSpec:
    name: str
    skill: str
    agent: str
    next: str | None = None
    pass_: str | None = None
    fail: str | None = None
    approval: str | None = None
    max_attempts: int = 3
    timeout: float | None = None

    @property
    def is_gate(self) -> bool:
        return self.pass_ is not None


@dataclass
class Pipeline:
    root: Path
    name: str
    start: str
    agents: dict[str, AgentSpec]
    stages: dict[str, StageSpec]

    @property
    def state_dir(self) -> Path:
        return self.root / ".queue"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"


def find_pipeline(start: Path) -> Path:
    """Walk up from `start` to the nearest pipeline.toml."""
    for d in [start, *start.parents]:
        if (d / PIPELINE_FILE).is_file():
            return d / PIPELINE_FILE
    raise ConfigError(f"no {PIPELINE_FILE} found in {start} or its parents (run `q init`)")


def load(path: Path) -> Pipeline:
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e

    agents = {}
    for name, raw in data.get("agents", {}).items():
        raw = dict(raw)
        if "use" not in raw:
            raise ConfigError(f"agent '{name}' needs a `use` (claude-code, codex or command)")
        agents[name] = AgentSpec(name=name, use=raw.pop("use"), options=raw)

    stages = {}
    for name, raw in data.get("stages", {}).items():
        raw = dict(raw)
        for key in ("skill", "agent"):
            if key not in raw:
                raise ConfigError(f"stage '{name}' needs a `{key}`")
        stages[name] = StageSpec(
            name=name,
            skill=raw.pop("skill"),
            agent=raw.pop("agent"),
            next=raw.pop("next", None),
            pass_=raw.pop("pass", None),
            fail=raw.pop("fail", None),
            approval=raw.pop("approval", None),
            max_attempts=int(raw.pop("max_attempts", 3)),
            timeout=raw.pop("timeout", None),
        )
        if raw:
            raise ConfigError(f"stage '{name}': unknown keys {sorted(raw)}")

    if not stages:
        raise ConfigError(f"{path}: no [stages.*] defined")

    meta = data.get("pipeline", {})
    pipeline = Pipeline(
        root=path.parent.resolve(),
        name=meta.get("name", path.parent.name),
        start=meta.get("start", next(iter(stages))),
        agents=agents,
        stages=stages,
    )
    _validate(pipeline)
    return pipeline


def _validate(p: Pipeline) -> None:
    targets = set(p.stages) | {DONE}
    if p.start not in p.stages:
        raise ConfigError(f"start stage '{p.start}' is not defined")
    for s in p.stages.values():
        if s.agent not in p.agents:
            raise ConfigError(f"stage '{s.name}' uses unknown agent '{s.agent}'")
        if s.is_gate:
            if s.fail is None:
                raise ConfigError(f"stage '{s.name}' has `pass` but no `fail`")
            if s.next is not None:
                raise ConfigError(f"stage '{s.name}': use either `next` or `pass`/`fail`")
        elif s.next is None:
            raise ConfigError(f"stage '{s.name}' needs `next` (or `pass` and `fail`)")
        for t in (s.next, s.pass_, s.fail):
            if t is not None and t not in targets:
                raise ConfigError(f"stage '{s.name}' points to unknown stage '{t}'")
        if s.approval not in (None, "human"):
            raise ConfigError(f"stage '{s.name}': approval must be \"human\" if set")
