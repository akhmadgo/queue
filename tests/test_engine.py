import json
import sys
import textwrap
from pathlib import Path

import pytest

from ideaqueue import config
from ideaqueue.cli import main
from ideaqueue.engine import Engine
from ideaqueue.store import DONE, PENDING, SHELVED, WAITING, Store

# A stand-in agent. It reads the stage from the environment and acts on a script of
# verdicts: FAKE_<STAGE> = "fail,pass" means fail the first run, pass the second.
FAKE_AGENT = textwrap.dedent("""
    import json, os, pathlib, sys
    stage = os.environ["QUEUE_STAGE"]
    prompt = sys.stdin.read()
    counter = pathlib.Path(f".runs-{stage}")
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    plan = os.environ.get(f"FAKE_{stage.upper()}", "pass").split(",")
    action = plan[min(n, len(plan) - 1)]
    pathlib.Path(f"{stage}-{n + 1}.txt").write_text(prompt)
    if action == "crash":
        sys.exit(3)
    out = {"verdict": "fail" if action == "fail" else "pass", "notes": f"{stage} run {n + 1}"}
    if action == "spawn":
        out["spawn"] = [{"title": "idea A", "body": "a"}, {"title": "idea B", "body": "b"}]
    if action != "silent":
        pathlib.Path(os.environ["QUEUE_OUTCOME"]).write_text(json.dumps(out))
""")


def make_pipeline(tmp_path: Path, stages: str) -> config.Pipeline:
    (tmp_path / "fake_agent.py").write_text(FAKE_AGENT)
    for skill in ("make", "check", "propose", "ship"):
        (tmp_path / "skills" / skill).mkdir(parents=True, exist_ok=True)
        (tmp_path / "skills" / skill / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: test\n---\nDo the {skill} step.\n")
    (tmp_path / "pipeline.toml").write_text(textwrap.dedent(f"""
        [pipeline]
        name = "toy"

        [agents.fake]
        use = "command"
        run = ["{sys.executable}", "{tmp_path / 'fake_agent.py'}"]
    """) + textwrap.dedent(stages))
    return config.load(tmp_path / "pipeline.toml")


MAKE_CHECK = """
    [stages.make]
    skill = "make"
    agent = "fake"
    next = "check"
    max_attempts = 3

    [stages.check]
    skill = "check"
    agent = "fake"
    pass = "done"
    fail = "make"
"""


@pytest.fixture
def toy(tmp_path):
    pipeline = make_pipeline(tmp_path, MAKE_CHECK)
    store = Store(pipeline.state_dir)
    yield Engine(pipeline, store, say=lambda _: None), store
    store.close()


def drain(engine):
    engine.run(once=True)


def test_item_moves_through_to_done(toy):
    engine, store = toy
    item = engine.submit("hello")
    drain(engine)
    item = store.get(item.id)
    assert item.status == DONE
    assert item.attempts == {"make": 1, "check": 1}
    assert (item.dir / "idea.md").read_text().startswith("# hello")


def test_gate_failure_sends_item_back_with_notes(toy, monkeypatch):
    engine, store = toy
    monkeypatch.setenv("FAKE_CHECK", "fail,pass")
    item = engine.submit("needs a second try")
    drain(engine)
    item = store.get(item.id)
    assert item.status == DONE
    assert item.attempts == {"make": 2, "check": 2}
    # The second make run was told what the check said.
    assert "check run 1" in (item.dir / "make-2.txt").read_text()
    kinds = [e.kind.split(" ")[0] for e in store.events(item.id)]
    assert kinds.count("fail") == 1


def test_item_is_shelved_after_max_attempts(toy, monkeypatch):
    engine, store = toy
    monkeypatch.setenv("FAKE_CHECK", "fail")
    item = engine.submit("never good enough")
    drain(engine)
    item = store.get(item.id)
    assert item.status == SHELVED
    assert item.stage == "make"
    assert item.attempts["make"] == 3


def test_agent_crash_retries_same_stage(toy, monkeypatch):
    engine, store = toy
    monkeypatch.setenv("FAKE_MAKE", "crash,pass")
    item = engine.submit("flaky")
    drain(engine)
    item = store.get(item.id)
    assert item.status == DONE
    assert item.attempts["make"] == 2


def test_gate_without_outcome_is_retried(toy, monkeypatch):
    engine, store = toy
    monkeypatch.setenv("FAKE_CHECK", "silent,pass")
    item = engine.submit("forgetful checker")
    drain(engine)
    assert store.get(item.id).status == DONE
    assert store.get(item.id).attempts["check"] == 2


def test_spawn_splits_item(tmp_path, monkeypatch):
    pipeline = make_pipeline(tmp_path, """
        [stages.propose]
        skill = "propose"
        agent = "fake"
        next = "make"

        [stages.make]
        skill = "make"
        agent = "fake"
        next = "done"
    """)
    store = Store(pipeline.state_dir)
    engine = Engine(pipeline, store, say=lambda _: None)
    monkeypatch.setenv("FAKE_PROPOSE", "spawn")
    parent = engine.submit("a direction")
    drain(engine)
    items = store.list()
    assert [i.title for i in items] == ["a direction", "idea A", "idea B"]
    assert all(i.status == DONE for i in items)
    assert [i.parent for i in items[1:]] == [parent.id, parent.id]


def test_human_approval_holds_item(tmp_path):
    pipeline = make_pipeline(tmp_path, """
        [stages.make]
        skill = "make"
        agent = "fake"
        next = "ship"

        [stages.ship]
        skill = "ship"
        agent = "fake"
        next = "done"
        approval = "human"
    """)
    store = Store(pipeline.state_dir)
    engine = Engine(pipeline, store, say=lambda _: None)
    item = engine.submit("release it")
    drain(engine)
    assert store.get(item.id).status == WAITING
    store.update(item.id, status=PENDING)
    drain(engine)
    assert store.get(item.id).status == DONE


def test_config_rejects_unknown_target(tmp_path):
    with pytest.raises(config.ConfigError, match="unknown stage 'nowhere'"):
        make_pipeline(tmp_path, """
            [stages.make]
            skill = "make"
            agent = "fake"
            next = "nowhere"
        """)


def test_cli_shorthand_add_and_run(tmp_path, monkeypatch, capsys):
    make_pipeline(tmp_path, MAKE_CHECK)
    monkeypatch.chdir(tmp_path)
    main(["try the cli"])
    main(["run", "--once"])
    main(["ls"])
    out = capsys.readouterr().out
    assert "#1 added at make" in out
    assert "done" in out.splitlines()[-1]


def test_init_creates_valid_research_pipeline(tmp_path):
    main(["init", str(tmp_path)])
    pipeline = config.load(tmp_path / "pipeline.toml")
    assert list(pipeline.stages) == ["find", "experiment", "verify", "write", "review"]
    assert ".queue/" in (tmp_path / ".gitignore").read_text()
    from ideaqueue.prompt import load_skill
    for stage in pipeline.stages.values():
        assert load_skill(pipeline.skills_dir, stage.skill).body


def test_prompt_mentions_outcome_contract(toy):
    engine, store = toy
    item = engine.submit("look at the prompt")
    engine.run_once()
    prompt = (store.get(item.id).dir / "make-1.txt").read_text()
    assert "You are the **make** stage" in prompt
    assert ".queue/outcome.json" in prompt
    assert "Do the make step." in prompt
    assert json  # keep import used
