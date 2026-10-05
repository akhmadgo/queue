"""The `q` command."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import config
from .engine import Engine
from .store import PENDING, SHELVED, WAITING, Store

COMMANDS = {"init", "add", "ls", "show", "stats", "run", "approve", "retry", "-h", "--help"}


def _open(args) -> tuple[config.Pipeline, Store, Engine]:
    path = Path(args.pipeline) if args.pipeline else config.find_pipeline(Path.cwd())
    pipeline = config.load(path)
    store = Store(pipeline.state_dir)
    return pipeline, store, Engine(pipeline, store)


def cmd_init(args) -> None:
    dest = Path(args.dir).resolve()
    if (dest / config.PIPELINE_FILE).exists():
        sys.exit(f"{dest / config.PIPELINE_FILE} already exists")
    template = resources.files("ideaqueue") / "templates" / args.template
    if not template.is_dir():
        sys.exit(f"no template named '{args.template}'")
    with resources.as_file(template) as src:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    gitignore = dest / ".gitignore"
    if ".queue/" not in (gitignore.read_text() if gitignore.exists() else ""):
        with open(gitignore, "a") as f:
            f.write(".queue/\n")
    print(f"created {args.template} pipeline in {dest}")
    print("next: q add \"<a research direction>\"  then  q run")


def cmd_add(args) -> None:
    _, _store, engine = _open(args)
    text = " ".join(args.text)
    if text == "-" or (not text and not sys.stdin.isatty()):
        text = sys.stdin.read().strip()
    if not text:
        sys.exit("nothing to add")
    title, _, body = text.partition("\n")
    item = engine.submit(title.strip(), body.strip(), stage=args.stage)
    print(f"#{item.id} added at {item.stage} ({item.status})")


def cmd_ls(args) -> None:
    _, store, _ = _open(args)
    items = store.list(args.status)
    if not items:
        print("no items")
        return
    width = max(len(i.stage) for i in items)
    for i in items:
        tries = sum(i.attempts.values())
        print(f"#{i.id:<4} {i.stage:<{width}}  {i.status:<8} {tries:>2} runs  {i.title}")


def cmd_show(args) -> None:
    _, store, _ = _open(args)
    try:
        item = store.get(args.id)
    except KeyError:
        sys.exit(f"no item #{args.id}")
    print(f"#{item.id} {item.title}")
    print(f"  stage   {item.stage} ({item.status})")
    print(f"  folder  {item.dir}")
    if item.parent:
        print(f"  parent  #{item.parent}")
    if item.notes:
        print(f"  notes   {item.notes}")
    print("\nhistory")
    for e in store.events(item.id):
        print(f"  {e.ts[11:19]}  {e.stage:<12} {e.kind:<14} {e.message}")


def cmd_stats(args) -> None:
    _, store, _ = _open(args)
    stats = store.stage_stats()
    if not stats:
        print("no runs yet")
        return
    print(f"{'stage':<14}{'runs':>5}{'pass':>6}{'fail':>6}{'error':>7}{'avg s':>8}{'cost':>9}")
    for s in stats:
        cost = f"${s.cost_usd:.2f}" if s.cost_usd is not None else "-"
        print(f"{s.stage:<14}{s.runs:>5}{s.passed:>6}{s.failed:>6}{s.errors:>7}"
              f"{s.seconds / s.runs:>8.0f}{cost:>9}")
    costs = [s.cost_usd for s in stats if s.cost_usd is not None]
    if costs:
        print(f"total cost ${sum(costs):.2f}")


def cmd_run(args) -> None:
    pipeline, _, engine = _open(args)
    stages = args.stage or None
    for s in stages or []:
        if s not in pipeline.stages:
            sys.exit(f"unknown stage '{s}'")
    try:
        engine.run(stages=stages, worker=args.worker, once=args.once)
    except KeyboardInterrupt:
        print("\nstopped")


def cmd_approve(args) -> None:
    _, store, _ = _open(args)
    item = store.get(args.id)
    if item.status != WAITING:
        sys.exit(f"#{item.id} is {item.status}, not waiting for approval")
    store.update(item.id, status=PENDING)
    store.event(item.id, item.stage, "approved")
    print(f"#{item.id} approved for {item.stage}")


def cmd_retry(args) -> None:
    _, store, _ = _open(args)
    item = store.get(args.id)
    if item.status != SHELVED:
        sys.exit(f"#{item.id} is {item.status}; only shelved items can be retried")
    item.attempts.pop(item.stage, None)
    store.update(item.id, status=PENDING, attempts=item.attempts)
    store.event(item.id, item.stage, "retried")
    print(f"#{item.id} back to pending at {item.stage}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="q", description="Run pipelines with your own agents.")
    p.add_argument("-p", "--pipeline", help="path to pipeline.toml (default: search upward)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a pipeline from a template")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("-t", "--template", default="research")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("add", help="add an item (also: q \"text\")")
    s.add_argument("text", nargs="*")
    s.add_argument("-s", "--stage", help="start at this stage instead of the first")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("ls", help="list items")
    s.add_argument("status", nargs="?")
    s.set_defaults(fn=cmd_ls)

    s = sub.add_parser("show", help="show one item and its history")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("stats", help="runs, verdicts, time and cost per stage")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("run", help="start a worker that drains the queue")
    s.add_argument("-s", "--stage", action="append", help="only these stages (repeatable)")
    s.add_argument("-w", "--worker", help="worker name (default: hostname)")
    s.add_argument("--once", action="store_true", help="stop when nothing is pending")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("approve", help="let a waiting item run its stage")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("retry", help="give a shelved item fresh attempts")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_retry)
    return p


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    # `q "some idea"` is shorthand for `q add "some idea"`.
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["add", *argv]
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except config.ConfigError as e:
        sys.exit(f"config error: {e}")
