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
CREATE TABLE IF NOT EXISTS session_models (
  session_id INTEGER, model TEXT, input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, cost REAL
);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, kind TEXT, task_id TEXT, phase_id TEXT, title TEXT, question TEXT, checked TEXT, why TEXT,
  suggestion TEXT, blocks TEXT, status TEXT, answer TEXT, created_at TEXT, answered_at TEXT
);
"""
SESSION_COLS = ("tokens_in", "tokens_out", "tokens_cache_read", "tokens_cache_write", "num_turns", "duration_ms")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.healed = ""  # self-healing: what was restored when the database would not open
        try:
            self._open()
        except sqlite3.DatabaseError as exc:  # corrupt (crash mid-write, disk trouble): restore the last backup
            self.healed = self._restore(exc)
            self._open()

    def _open(self):
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(sessions)")}
            for col in SESSION_COLS:  # older databases predate the token ledger
                if col not in have:
                    self.db.execute(f"ALTER TABLE sessions ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.DatabaseError:
            self.db.close()
            raise

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + "-backup")  # matches the `.agent/state.db-*` ignore rule

    def backup(self):
        """A consistent copy (SQLite's backup API, safe while open), taken at every run start."""
        dst = sqlite3.connect(str(self.backup_path))
        try:
            self.db.backup(dst)
        finally:
            dst.close()

    def _restore(self, exc) -> str:
        """Move the broken file aside and start from the backup, or empty. The plan and git still hold the work: the
        run re-syncs tasks from plan.yaml and marks a task done when its commit is on main (Orchestrator)."""
        aside = self.path.with_name(f"{self.path.name}-corrupt-{dt.datetime.now():%Y%m%d%H%M%S}")
        self.path.replace(aside)
        for extra in ("-wal", "-shm"):
            Path(str(self.path) + extra).unlink(missing_ok=True)
        if self.backup_path.exists():
            import shutil
            shutil.copyfile(self.backup_path, self.path)
            return f"state database was unreadable ({exc}); restored the backup from the last run start ({aside.name})"
        return f"state database was unreadable ({exc}) and had no backup; started a fresh one ({aside.name})"

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
                    self.set_meta(f"unstick:{t.id}", False)
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
                    summary: str = "", error: str = "", log_path: str = "", usage: dict | None = None,
                    num_turns: int = 0, duration_ms: int = 0):
        usage = usage or {}
        tot = {k: sum(int(u.get(k) or 0) for u in usage.values()) for k in ("input", "output", "cache_read", "cache_write")}
        self.db.execute(
            "UPDATE sessions SET ended_at=?, cost=?, ok=?, claude_session_id=?, summary=?, error=?, log_path=?, "
            "tokens_in=?, tokens_out=?, tokens_cache_read=?, tokens_cache_write=?, num_turns=?, duration_ms=? WHERE id=?",
            (now(), cost, int(ok), claude_session_id, summary[:4000], error[:4000], log_path, tot["input"], tot["output"],
             tot["cache_read"], tot["cache_write"], num_turns, duration_ms, sid))
        for m, u in usage.items():
            self.db.execute("INSERT INTO session_models VALUES(?,?,?,?,?,?,?)",
                            (sid, m, *(int(u.get(k) or 0) for k in ("input", "output", "cache_read", "cache_write")),
                             float(u.get("cost") or 0)))

    def next_session_id(self) -> int:
        return int(self.db.execute("SELECT COALESCE(MAX(id),0)+1 FROM sessions").fetchone()[0])

    def token_totals(self, by: str, since_session: int = 0) -> list[tuple[str, dict]]:
        """[(key, {input, output, cache_read, cache_write, total, cost})] for by in model|kind|task|phase|day, biggest first."""
        if by == "model":
            q = ("SELECT model k, SUM(input) i, SUM(output) o, SUM(cache_read) r, SUM(cache_write) w, SUM(cost) c "
                 "FROM session_models WHERE session_id >= ? GROUP BY model")
        else:
            key = {"kind": "kind", "task": "task_id", "phase": "phase", "day": "substr(started_at, 1, 10)"}[by]
            q = (f"SELECT COALESCE({key}, '(none)') k, SUM(tokens_in) i, SUM(tokens_out) o, SUM(tokens_cache_read) r, "
                 "SUM(tokens_cache_write) w, SUM(cost) c FROM sessions WHERE id >= ? GROUP BY k")
        out = []
        for r in self.db.execute(q, (since_session,)):
            i, o, rd, w = (int(r[x] or 0) for x in "iorw")
            out.append((r["k"] or "(unknown)", {"input": i, "output": o, "cache_read": rd, "cache_write": w,
                                                "total": i + o + rd + w, "cost": float(r["c"] or 0)}))
        return sorted(out, key=lambda kv: -kv[1]["total"])

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

    # ---------- owner decisions (docs/NEEDS-YOU.md) ----------
    def add_decision(self, **f) -> str:
        n = max((int(r[0][2:]) for r in self.db.execute("SELECT id FROM decisions")), default=0) + 1
        did = f"D-{n:03d}"
        f.setdefault("blocks", [])
        f["blocks"] = json.dumps(f["blocks"]) if isinstance(f["blocks"], list) else f["blocks"]
        f.update(id=did, status="OPEN", created_at=now())
        self.db.execute(f"INSERT INTO decisions({', '.join(f)}) VALUES({', '.join('?' * len(f))})", tuple(f.values()))
        return did

    def decisions(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return list(self.db.execute("SELECT * FROM decisions WHERE status=? ORDER BY rowid DESC", (status,)))
        return list(self.db.execute("SELECT * FROM decisions ORDER BY rowid DESC"))

    def decision(self, did: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone()

    def set_decision(self, did: str, **f):
        if isinstance(f.get("blocks"), list):
            f["blocks"] = json.dumps(f["blocks"])
        cols = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE decisions SET {cols} WHERE id=?", (*f.values(), did))

    def answer_decision(self, did: str, text: str) -> bool:
        cur = self.db.execute("UPDATE decisions SET status='ANSWERED', answer=?, answered_at=? WHERE id=? AND status='OPEN'",
                              (text, now(), did))
        return cur.rowcount > 0

    def open_decision(self, task_id: str | None = None, kind: str | None = None, phase_id: str | None = None):
        q, args = "SELECT * FROM decisions WHERE status='OPEN'", []
        for col, val in (("task_id", task_id), ("kind", kind), ("phase_id", phase_id)):
            if val is not None:
                q += f" AND {col}=?"; args.append(val)
        return self.db.execute(q + " ORDER BY rowid DESC", args).fetchone()

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
