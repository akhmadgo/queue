"""SQLite-backed item store. Each item also has a folder that agents work in."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PENDING = "pending"
RUNNING = "running"
WAITING = "waiting"  # needs human approval before the stage runs
DONE = "done"
SHELVED = "shelved"  # gave up: too many attempts

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id        INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    stage     TEXT NOT NULL,
    status    TEXT NOT NULL,
    attempts  TEXT NOT NULL DEFAULT '{}',
    notes     TEXT NOT NULL DEFAULT '',
    parent    INTEGER,
    worker    TEXT,
    dir       TEXT NOT NULL,
    created   TEXT NOT NULL,
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY,
    item_id  INTEGER NOT NULL,
    ts       TEXT NOT NULL,
    stage    TEXT NOT NULL,
    kind     TEXT NOT NULL,
    message  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY,
    item_id   INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    stage     TEXT NOT NULL,
    attempt   INTEGER NOT NULL,
    agent     TEXT NOT NULL,
    verdict   TEXT NOT NULL,   -- pass, fail, error
    seconds   REAL NOT NULL,
    cost_usd  REAL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "item"


@dataclass
class Item:
    id: int
    title: str
    stage: str
    status: str
    attempts: dict[str, int]
    notes: str
    parent: int | None
    worker: str | None
    dir: Path
    created: str
    updated: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Item:
        d = dict(row)
        d["attempts"] = json.loads(d["attempts"])
        d["dir"] = Path(d["dir"])
        return cls(**d)


@dataclass
class Event:
    item_id: int
    ts: str
    stage: str
    kind: str
    message: str


@dataclass
class StageStats:
    stage: str
    runs: int
    passed: int
    failed: int
    errors: int
    seconds: float
    cost_usd: float | None


class Store:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.items_dir = state_dir / "items"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(state_dir / "queue.db", timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- writes ---------------------------------------------------------

    def add(self, title: str, body: str, stage: str, status: str = PENDING,
            parent: int | None = None) -> Item:
        now = _now()
        cur = self.db.execute(
            "INSERT INTO items (title, stage, status, parent, dir, created, updated)"
            " VALUES (?, ?, ?, ?, '', ?, ?)",
            (title, stage, status, parent, now, now),
        )
        item_id = cur.lastrowid
        item_dir = self.items_dir / f"{item_id:04d}-{slugify(title)}"
        (item_dir / ".queue" / "logs").mkdir(parents=True, exist_ok=True)
        (item_dir / "idea.md").write_text(f"# {title}\n\n{body}".rstrip() + "\n")
        self.db.execute("UPDATE items SET dir = ? WHERE id = ?", (str(item_dir), item_id))
        self.event(item_id, stage, "added", f"parent #{parent}" if parent else "")
        return self.get(item_id)

    def claim(self, stages: list[str], worker: str) -> Item | None:
        """Atomically take the oldest pending item in one of `stages`."""
        marks = ",".join("?" * len(stages))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                f"SELECT id FROM items WHERE status = ? AND stage IN ({marks})"
                " ORDER BY id LIMIT 1",
                (PENDING, *stages),
            ).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            self.db.execute(
                "UPDATE items SET status = ?, worker = ?, updated = ? WHERE id = ?",
                (RUNNING, worker, _now(), row["id"]),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return self.get(row["id"])

    def update(self, item_id: int, **fields) -> None:
        if "attempts" in fields:
            fields["attempts"] = json.dumps(fields["attempts"])
        fields["updated"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE items SET {cols} WHERE id = ?", (*fields.values(), item_id))

    def event(self, item_id: int, stage: str, kind: str, message: str = "") -> None:
        self.db.execute(
            "INSERT INTO events (item_id, ts, stage, kind, message) VALUES (?, ?, ?, ?, ?)",
            (item_id, _now(), stage, kind, message),
        )

    def record_run(self, item_id: int, stage: str, attempt: int, agent: str, verdict: str,
                   seconds: float, cost_usd: float | None) -> None:
        self.db.execute(
            "INSERT INTO runs (item_id, ts, stage, attempt, agent, verdict, seconds, cost_usd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, _now(), stage, attempt, agent, verdict, seconds, cost_usd),
        )

    def release_stale(self, worker: str) -> int:
        """Put back items this worker was running when it last died."""
        cur = self.db.execute(
            "UPDATE items SET status = ?, worker = NULL WHERE status = ? AND worker = ?",
            (PENDING, RUNNING, worker),
        )
        return cur.rowcount

    # -- reads ----------------------------------------------------------

    def get(self, item_id: int) -> Item:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        return Item.from_row(row)

    def list(self, status: str | None = None) -> list[Item]:
        if status:
            rows = self.db.execute("SELECT * FROM items WHERE status = ? ORDER BY id", (status,))
        else:
            rows = self.db.execute("SELECT * FROM items ORDER BY id")
        return [Item.from_row(r) for r in rows]

    def events(self, item_id: int) -> list[Event]:
        rows = self.db.execute(
            "SELECT item_id, ts, stage, kind, message FROM events WHERE item_id = ? ORDER BY id",
            (item_id,),
        )
        return [Event(**dict(r)) for r in rows]

    def stage_stats(self) -> list[StageStats]:
        rows = self.db.execute(
            "SELECT stage, COUNT(*) AS runs,"
            " SUM(verdict = 'pass') AS passed, SUM(verdict = 'fail') AS failed,"
            " SUM(verdict = 'error') AS errors, SUM(seconds) AS seconds,"
            " SUM(cost_usd) AS cost_usd"
            " FROM runs GROUP BY stage ORDER BY MIN(id)"
        )
        return [StageStats(**dict(r)) for r in rows]
