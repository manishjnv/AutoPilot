"""Crash-safe SQLite state: task status, sessions, costs, phases, approvals, events."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from .plan import Plan

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, phase TEXT, status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  cost REAL DEFAULT 0, last_error TEXT, commit_sha TEXT, model TEXT, note TEXT,
  started_at TEXT, finished_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, task_id TEXT, phase TEXT, attempt INTEGER,
  model TEXT, started_at TEXT, ended_at TEXT, cost REAL DEFAULT 0, ok INTEGER,
  claude_session_id TEXT, summary TEXT, error TEXT, log_path TEXT
);
CREATE TABLE IF NOT EXISTS phases (
  id TEXT PRIMARY KEY, status TEXT DEFAULT 'open', completed_at TEXT,
  staging_ref TEXT, prod_status TEXT, prod_ref TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---------- plan sync ----------
    def sync_plan(self, plan: Plan) -> dict:
        """Add new tasks, mark tasks removed from the plan as skipped, apply `reopen` flags."""
        existing = {r["id"]: r for r in self.db.execute("SELECT * FROM tasks")}
        added, removed, reopened = [], [], []
        for t in plan.all_tasks():
            row = existing.get(t.id)
            if row is None:
                self.db.execute("INSERT INTO tasks(id, phase, updated_at) VALUES(?,?,?)", (t.id, t.phase_id, now()))
                added.append(t.id)
            else:
                if row["phase"] != t.phase_id:
                    self.db.execute("UPDATE tasks SET phase=? WHERE id=?", (t.phase_id, t.id))
                if t.reopen and row["status"] in ("blocked", "skipped"):
                    self.set_task(t.id, status="pending", attempts=0, last_error=None,
                                  note="reopened by replanner")
                    reopened.append(t.id)
        for tid, row in existing.items():
            if tid not in plan.task_by_id and row["status"] == "pending":
                self.set_task(tid, status="skipped", note="removed from plan")
                removed.append(tid)
        for p in plan.phases:
            self.db.execute("INSERT OR IGNORE INTO phases(id) VALUES(?)", (p.id,))
        return {"added": added, "removed": removed, "reopened": reopened}

    def recover_crashed(self) -> list[str]:
        rows = [r["id"] for r in self.db.execute("SELECT id FROM tasks WHERE status='running'")]
        for tid in rows:
            self.set_task(tid, status="pending", note="recovered after crash")
        return rows

    # ---------- tasks ----------
    def set_task(self, tid: str, **fields):
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), tid))

    def task(self, tid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

    def status_map(self) -> dict[str, str]:
        return {r["id"]: r["status"] for r in self.db.execute("SELECT id, status FROM tasks")}

    def tasks(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return list(self.db.execute("SELECT * FROM tasks WHERE status=? ORDER BY id", (status,)))
        return list(self.db.execute("SELECT * FROM tasks ORDER BY id"))

    # ---------- sessions & cost ----------
    def start_session(self, kind: str, task_id: str | None, phase: str | None, attempt: int, model: str) -> int:
        cur = self.db.execute(
            "INSERT INTO sessions(kind, task_id, phase, attempt, model, started_at) VALUES(?,?,?,?,?,?)",
            (kind, task_id, phase, attempt, model, now()))
        return int(cur.lastrowid)

    def end_session(self, sid: int, *, cost: float, ok: bool, claude_session_id: str = "",
                    summary: str = "", error: str = "", log_path: str = ""):
        self.db.execute(
            "UPDATE sessions SET ended_at=?, cost=?, ok=?, claude_session_id=?, summary=?, error=?, log_path=? WHERE id=?",
            (now(), cost, int(ok), claude_session_id, summary[:4000], error[:4000], log_path, sid))

    def cost(self, *, task_id: str | None = None, phase: str | None = None, today: bool = False) -> float:
        q, args = "SELECT COALESCE(SUM(cost),0) FROM sessions WHERE 1=1", []
        if task_id:
            q += " AND task_id=?"; args.append(task_id)
        if phase:
            q += " AND phase=?"; args.append(phase)
        if today:
            q += " AND started_at >= ?"; args.append(dt.date.today().isoformat())
        return float(self.db.execute(q, args).fetchone()[0])

    def session_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def recent_sessions(self, n: int = 20) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (n,)))

    # ---------- phases ----------
    def phase(self, pid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM phases WHERE id=?", (pid,)).fetchone()

    def set_phase(self, pid: str, **fields):
        self.db.execute("INSERT OR IGNORE INTO phases(id) VALUES(?)", (pid,))
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE phases SET {cols} WHERE id=?", (*fields.values(), pid))

    def phases_closed(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM phases WHERE status IN ('done','partial')").fetchone()[0])

    def last_staging_ref(self, exclude: str | None = None) -> str | None:
        row = self.db.execute(
            "SELECT staging_ref FROM phases WHERE staging_ref IS NOT NULL AND id != ? ORDER BY completed_at DESC LIMIT 1",
            (exclude or "",)).fetchone()
        return row[0] if row else None

    def last_prod_ref(self) -> str | None:
        row = self.db.execute(
            "SELECT prod_ref FROM phases WHERE prod_status='deployed' ORDER BY completed_at DESC LIMIT 1").fetchone()
        return row[0] if row else None

    # ---------- meta & events ----------
    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, json.dumps(value)))

    def event(self, kind: str, message: str):
        self.db.execute("INSERT INTO events(ts, kind, message) VALUES(?,?,?)", (now(), kind, message[:4000]))

    def events(self, n: int = 50) -> list[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)))
