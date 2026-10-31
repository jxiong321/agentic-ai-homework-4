"""Assignment 4, Part D: the memory store. This file is yours.

A store is shared by every run, keyed by repository and issue. It is durable: a
SQLite file such as state/store.db is fine. How you give a run an empty store, for
Part D's second set of five runs, is yours: an environment variable this module
reads, for example. The checker always reads your real store.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.5), so keep them:

    Store(path=None)                                  # None: your default file
    .write(record) -> id                              # a new record; returns its id
    .supersede(old_id, record) -> id                  # a new record that replaces old_id
    .active(repository, issue=None) -> list[dict]     # the active records, for retrieval
    .records() -> list[dict]                          # every record, active or not

Every record carries the fields of section 12.5: its kind (episodic, semantic or
procedural), its text, and its provenance: source, written_at, origin (derived or
ingested) and confirmed. A superseded record stays in the store, inactive, and the
record that replaced it names it in `supersedes`.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
import os
import re
import sqlite3
import uuid

from harness import ROOT

DEFAULT = ROOT / "state" / "store.db"
REPOSITORY = "ledgerline"
KINDS = ("episodic", "semantic", "procedural")
ORIGINS = ("derived", "ingested")


class Store:
    MAX_RECORDS = 1000
    TTL_DAYS = 90

    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.environ.get("REPOMIND_STORE_PATH") or DEFAULT)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, record TEXT NOT NULL)")

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _prepare(self, record):
        row = dict(record)
        row.setdefault("id", uuid.uuid4().hex)
        row.setdefault("active", True)
        row.setdefault("supersedes", None)
        required = {"repository", "issue", "kind", "text", "source", "written_at", "origin", "confirmed"}
        if not required <= row.keys():
            raise ValueError(f"Missing memory fields: {required - row.keys()}")
        if row["kind"] not in KINDS or row["origin"] not in ORIGINS:
            raise ValueError("Invalid memory kind or origin")
        source = row["source"]
        if source not in ("user", "repo", "memory") and not re.fullmatch(r"issue:\d+", source):
            raise ValueError("Invalid provenance source")
        if source.startswith("issue:") and (row["kind"] != "episodic" or row["confirmed"]):
            raise ValueError("Issue claims must remain unconfirmed episodic records")
        if source == "user" and not row.get("stated_by"):
            raise ValueError("User-stated memories require attribution")
        if not isinstance(row["confirmed"], bool) or not isinstance(row["active"], bool):
            raise ValueError("Confirmation and activity must be booleans")
        if datetime.fromisoformat(row["written_at"].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Memory timestamps must include a timezone")
        return row

    def _put(self, conn, row):
        conn.execute("INSERT INTO memories VALUES (?, ?)", (str(row["id"]), json.dumps(row)))

    def _bound(self, conn):
        rows = [json.loads(r[0]) for r in conn.execute("SELECT record FROM memories")]
        while len(rows) > self.MAX_RECORDS:
            referenced = {str(r["supersedes"]) for r in rows if r["supersedes"] is not None}
            candidates = [r for r in rows if r["source"] != "user" and not r.get("candidate")
                          and str(r["id"]) not in referenced]
            if not candidates:
                raise ValueError("Store capacity exhausted by protected history; consolidate it")
            oldest = min(candidates, key=lambda r: datetime.fromisoformat(r["written_at"].replace("Z", "+00:00")))
            conn.execute("DELETE FROM memories WHERE id=?", (str(oldest["id"]),))
            rows.remove(oldest)

    def write(self, record: dict):
        row = self._prepare(record)
        if row["supersedes"] is not None:
            raise ValueError("Use supersede() to replace a memory atomically")
        with closing(self._connect()) as conn, conn:
            self._put(conn, row)
            self._bound(conn)
        return row["id"]

    def supersede(self, old_id, record: dict):
        row = self._prepare(dict(record, supersedes=old_id, active=True))
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            found = conn.execute("SELECT record FROM memories WHERE id=?", (str(old_id),)).fetchone()
            if found is None:
                raise KeyError(old_id)
            old = json.loads(found[0])
            if not old["active"] or old["repository"] != row["repository"] or old["issue"] != row["issue"]:
                raise ValueError("Supersession requires an active record in the same scope")
            old["active"] = False
            conn.execute("UPDATE memories SET record=? WHERE id=?", (json.dumps(old), str(old_id)))
            self._put(conn, row)
            self._bound(conn)
        return row["id"]

    def active(self, repository: str, issue: int | None = None) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.TTL_DAYS)
        with closing(self._connect()) as conn, conn:
            rows = [json.loads(r[0]) for r in conn.execute("SELECT record FROM memories ORDER BY rowid")]
            active = []
            for row in rows:
                if row["active"] and row["source"] != "user" and datetime.fromisoformat(row["written_at"].replace("Z", "+00:00")) < cutoff:
                    row["active"] = False
                    conn.execute("UPDATE memories SET record=? WHERE id=?", (json.dumps(row), str(row["id"])))
                if row["active"] and row["repository"] == repository and (issue is None or row["issue"] in (None, issue)):
                    active.append(row)
            return active

    def records(self) -> list[dict]:
        with closing(self._connect()) as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT record FROM memories ORDER BY rowid")]
