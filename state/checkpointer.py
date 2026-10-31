"""Assignment 4, Part A: the checkpointer. This file is yours.

A checkpointer saves one run's state, so its checkpoints are keyed by the run's
run_id (frameworks call one run's line of checkpoints a thread). Save them on a
durable backend: a SQLite file such as state/checkpoints.db is fine; an in-memory
store is not, because it dies with the process. A sync save is on disk before
save() returns.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.4), so keep them:

    Checkpointer(path=None)                    # None: your default file
    .save(run_id, checkpoint, *, step, mode)   # one checkpoint; mode is sync, async or exit
    .last(run_id) -> dict | None               # the run's latest checkpoint, or None
    .all(run_id) -> list[dict]                 # every checkpoint the run saved, oldest first
    .runs() -> list[str]                       # every run_id that has a checkpoint

A checkpoint is a dict of exactly the five fields in harness.formats.CHECKPOINT_FIELDS:
plan, step_status, completed_calls (each with its idempotency key), findings and
current_step. Everything in it must serialize, and the conversation is not in it.
Every save is also a trace line, trace.event("checkpoint", step=..., mode=...),
which your way writes.
"""

from __future__ import annotations

import atexit
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from harness import ROOT
from harness.formats import CHECKPOINT_FIELDS, DURABILITY_MODES

DEFAULT = ROOT / "state" / "checkpoints.db"


class Checkpointer:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._modes = {}
        self._pending = []
        self._futures = []
        # One worker preserves the order of asynchronous saves.
        self._worker = ThreadPoolExecutor(max_workers=1)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    step INTEGER,
                    mode TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS checkpoints_by_run
                ON checkpoints (run_id, id)
            """)
        atexit.register(self.close)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _write(self, row):
        # The transaction commits before this method returns.
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO checkpoints (run_id, checkpoint, step, mode) "
                "VALUES (?, ?, ?, ?)", row,
            )

    def save(self, run_id: str, checkpoint: dict, *, step, mode: str = "sync") -> None:
        if mode not in DURABILITY_MODES:
            raise ValueError(f"Unknown durability mode: {mode}")
        if set(checkpoint) != set(CHECKPOINT_FIELDS):
            raise ValueError("A checkpoint must contain exactly the five required fields")
        # Serialize now so later mutations cannot change a queued snapshot.
        payload = json.dumps(checkpoint, allow_nan=False)
        with closing(self._connect()) as conn:
            previous = conn.execute(
                "SELECT mode FROM checkpoints WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        previous_mode = self._modes.get(run_id, previous[0] if previous else mode)
        if previous_mode != mode:
            raise ValueError("Durability mode must stay fixed for a run")
        self._modes[run_id] = mode
        row = (run_id, payload, step, mode)
        if mode == "sync":
            self._write(row)
        elif mode == "async":
            self._futures.append(self._worker.submit(self._write, row))
        else:
            self._pending.append(row)

    def flush(self) -> None:
        """Wait for background saves and persist saves deferred until run end."""
        for future in self._futures:
            future.result()
        self._futures.clear()
        while self._pending:
            self._write(self._pending[0])
            self._pending.pop(0)

    def close(self) -> None:
        """Call at normal run end; normal process exit is a fallback."""
        try:
            self.flush()
        finally:
            self._worker.shutdown(wait=True)
            atexit.unregister(self.close)

    def last(self, run_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT checkpoint FROM checkpoints WHERE run_id = ? "
                "ORDER BY id DESC LIMIT 1", (run_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, run_id: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT checkpoint FROM checkpoints WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def runs(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM checkpoints ORDER BY run_id"
            ).fetchall()
        return [row[0] for row in rows]
