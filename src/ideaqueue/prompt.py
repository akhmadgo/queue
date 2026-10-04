"""Skills and the prompt each stage's agent receives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, Pipeline, StageSpec
from .store import Item

OUTCOME_FILE = ".queue/outcome.json"
SKIP_DIRS = {".queue", ".git", "__pycache__", ".venv", "node_modules"}


@dataclass
class Skill:
    name: str
    description: str
    body: str


def load_skill(skills_dir: Path, name: str) -> Skill:
    """Read skills/<name>/SKILL.md: a `---` header of `key: value` lines, then instructions."""
    path = skills_dir / name / "SKILL.md"
    if not path.is_file():
        raise ConfigError(f"skill '{name}' not found at {path}")
    text = path.read_text()
    meta: dict[str, str] = {}
    if text.startswith("---"):
        header, _, text = text[3:].partition("\n---")
        for line in header.strip().splitlines():
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip()] = value.strip()
    return Skill(name=meta.get("name", name), description=meta.get("description", ""),
                 body=text.strip())


def list_files(root: Path, limit: int = 200) -> list[str]:
    files = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not SKIP_DIRS.intersection(rel.parts):
            files.append(str(rel))
            if len(files) >= limit:
                files.append("…")
                break
    return files


def outcome_contract(stage: StageSpec, item_dir: Path) -> str:
    if stage.is_gate:
        verdict = (
            '- `"verdict"`: `"pass"` if the work meets the bar, `"fail"` if it must be redone.\n'
            '- `"notes"`: on fail, exactly what is wrong and what to change. '
            "The next agent sees only these notes and the files."
        )
    else:
        verdict = (
            '- `"verdict"`: `"pass"` when your part is complete, `"fail"` if you could not '
            "finish and this stage should be retried.\n"
            '- `"notes"`: a short handoff for the next stage, or why you failed.\n'
            '- `"spawn"` (optional): a list of `{"title": ..., "body": ...}` to split this '
            "item into several new items for the next stage. Use it when your job is to "
            "propose multiple candidates."
        )
    path = item_dir / OUTCOME_FILE
    return (f"When you are done, write this exact file (absolute path):\n\n    {path}\n\n"
            f"as JSON with:\n{verdict}\n\nThe stage is not finished until that file exists.")


def build_prompt(pipeline: Pipeline, stage: StageSpec, item: Item, skill: Skill) -> str:
    files = "\n".join(f"- {f}" for f in list_files(item.dir)) or "- (none yet)"
    notes = f"\n## Notes handed to you\n\n{item.notes}\n" if item.notes else ""
    attempt = item.attempts.get(stage.name, 1)
    retry = (f"\nThis is attempt {attempt} of {stage.max_attempts} at this stage. "
             "Earlier work is still in the folder; build on it.\n") if attempt > 1 else ""
    return f"""You are the **{stage.name}** stage of the "{pipeline.name}" pipeline, run by queue.
Nobody is watching this run. Do not ask questions; make reasonable decisions and record them.

Your working folder is item #{item.id}: {item.dir}
It holds everything earlier stages produced.
Read what you need from it and write all of your output into it.

## Item

{item.title}

## Files in the folder

{files}
{notes}{retry}
## Your instructions ({skill.name})

{skill.body}

## Finishing

{outcome_contract(stage, item.dir)}
"""


@dataclass
class Outcome:
    verdict: str | None = None
    notes: str = ""
    spawn: list[dict] | None = None
    problem: str = ""


def read_outcome(item_dir: Path) -> Outcome:
    path = item_dir / OUTCOME_FILE
    if not path.is_file():
        return Outcome(problem=f"agent did not write {OUTCOME_FILE}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return Outcome(problem=f"{OUTCOME_FILE} is not valid JSON: {e}")
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        return Outcome(problem=f'{OUTCOME_FILE} needs "verdict": "pass" or "fail"')
    spawn = data.get("spawn")
    if spawn is not None and not (
        isinstance(spawn, list) and all(isinstance(s, dict) and s.get("title") for s in spawn)
    ):
        return Outcome(problem=f'{OUTCOME_FILE}: "spawn" must be a list of objects with a title')
    return Outcome(verdict=verdict, notes=str(data.get("notes", "")), spawn=spawn)
