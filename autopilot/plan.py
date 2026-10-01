"""plan.yaml model: phases, tasks, dependency validation and ordering."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import RISKS, load_yaml


class PlanError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Task:
    id: str
    title: str
    phase_id: str
    order: int
    description: str = ""
    risk: str = "medium"
    depends_on: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    files_in_scope: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    allow_no_changes: bool = False
    allow_test_changes: bool = False
    needs_decision: bool = False   # L2: weigh options in an ADR before building
    reopen: bool = False


@dataclass
class Phase:
    id: str
    title: str
    goal: str
    order: int
    depends_on: list[str]
    tasks: list[Task]
    deploy: bool = True
    priority: bool = False   # corrective phases jump the queue

    @property
    def max_risk(self) -> str:
        if not self.tasks:
            return "low"
        return max((t.risk for t in self.tasks), key=RISKS.index)


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


class Plan:
    def __init__(self, goal: str, phases: list[Phase]):
        self.goal = goal
        self.phases = phases
        self.phase_by_id = {p.id: p for p in phases}
        self.task_by_id = {t.id: t for p in phases for t in p.tasks}

    # ---------- loading ----------
    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        errors: list[str] = []
        phases: list[Phase] = []
        prev_id = None
        seen_tasks: set[str] = set()
        order = 0
        for pi, p in enumerate(data.get("phases") or []):
            pid = str(p.get("id") or f"P{pi + 1:02d}")
            deps = _as_list(p["depends_on"]) if "depends_on" in p else ([prev_id] if prev_id else [])
            tasks = []
            for ti, t in enumerate(p.get("tasks") or []):
                tid = str(t.get("id") or f"{pid}-T{ti + 1:02d}")
                if tid in seen_tasks:
                    errors.append(f"duplicate task id {tid}")
                seen_tasks.add(tid)
                risk = str(t.get("risk", "medium")).lower()
                if risk not in RISKS:
                    errors.append(f"{tid}: risk {risk!r} not in {RISKS}")
                if not t.get("title"):
                    errors.append(f"{tid}: missing title")
                order += 1
                tasks.append(Task(
                    id=tid, title=str(t.get("title", tid)), phase_id=pid, order=order,
                    description=str(t.get("description", "") or ""), risk=risk,
                    depends_on=[str(x) for x in _as_list(t.get("depends_on"))],
                    acceptance_criteria=[str(x) for x in _as_list(t.get("acceptance_criteria"))],
                    files_in_scope=[str(x) for x in _as_list(t.get("files_in_scope"))],
                    verify=[str(x) for x in _as_list(t.get("verify"))],
                    docs=[str(x) for x in _as_list(t.get("docs"))],
                    allow_no_changes=bool(t.get("allow_no_changes", False)),
                    allow_test_changes=bool(t.get("allow_test_changes", False)),
                    needs_decision=bool(t.get("needs_decision", False)),
                    reopen=bool(t.get("reopen", False)),
                ))
            phases.append(Phase(id=pid, title=str(p.get("title", pid)), goal=str(p.get("goal", "") or ""),
                                order=pi, depends_on=[str(d) for d in deps], tasks=tasks,
                                deploy=bool(p.get("deploy", True)), priority=bool(p.get("priority", False))))
            prev_id = pid
        plan = cls(str(data.get("goal", "") or ""), phases)
        errors += plan._validate_refs()
        if errors:
            raise PlanError(errors)
        return plan

    @classmethod
    def load(cls, path: Path | str) -> "Plan":
        return cls.from_dict(load_yaml(Path(path)))

    def _validate_refs(self) -> list[str]:
        errs = []
        if len(self.phase_by_id) != len(self.phases):
            errs.append("duplicate phase ids")
        if not self.phases:
            errs.append("plan has no phases")
        for p in self.phases:
            for d in p.depends_on:
                if d not in self.phase_by_id:
                    errs.append(f"phase {p.id} depends on unknown phase {d}")
            for t in p.tasks:
                for d in t.depends_on:
                    if d not in self.task_by_id:
                        errs.append(f"task {t.id} depends on unknown task {d}")
        if not errs:
            errs += self._cycles()
        return errs

    def _cycles(self) -> list[str]:
        # Combined graph: task -> explicit deps + all tasks of dependency phases.
        graph = {}
        for t in self.all_tasks():
            deps = set(t.depends_on)
            for pd in self.phase_by_id[t.phase_id].depends_on:
                deps.update(x.id for x in self.phase_by_id[pd].tasks)
            graph[t.id] = deps
        WHITE, GREY, BLACK = 0, 1, 2
        color = {k: WHITE for k in graph}
        for start in graph:
            if color[start] != WHITE:
                continue
            stack = [(start, iter(graph[start]))]
            color[start] = GREY
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    color[node] = BLACK
                    stack.pop()
                elif color[nxt] == GREY:
                    return [f"dependency cycle involving {nxt} and {node}"]
                elif color[nxt] == WHITE:
                    color[nxt] = GREY
                    stack.append((nxt, iter(graph[nxt])))
        return []

    # ---------- queries ----------
    def all_tasks(self) -> list[Task]:
        return [t for p in self.phases for t in p.tasks]

    def phase_of(self, task: Task | str) -> Phase:
        tid = task if isinstance(task, str) else task.id
        return self.phase_by_id[self.task_by_id[tid].phase_id]

    def next_ready(self, status: dict[str, str], policy: str = "soft") -> Task | None:
        """First task (plan order) whose dependencies are satisfied.

        status values: pending | running | done | blocked | skipped.
        Explicit task deps must be `done`. Phase deps: all tasks finished; in `soft` mode a
        blocked/skipped task counts as finished so one failure doesn't freeze the whole plan.
        """
        finished = {"done", "blocked", "skipped"} if policy == "soft" else {"done", "skipped"}
        if policy == "soft":
            # pending tasks that transitively depend on blocked work can't run either: treat as finished
            status = dict(status)
            dead = {k for k, v in status.items() if v in ("blocked", "skipped")}
            changed = True
            while changed:
                changed = False
                for t in self.all_tasks():
                    if status.get(t.id, "pending") == "pending" and t.id not in dead and \
                            any(d in dead for d in t.depends_on):
                        dead.add(t.id)
                        changed = True
            status = {**status, **{d: status.get(d) if status.get(d) in ("blocked", "skipped") else "waiting"
                                   for d in dead}}
            finished = finished | {"waiting"}
        ordered = sorted(self.all_tasks(), key=lambda t: (not self.phase_by_id[t.phase_id].priority, t.order))
        for t in ordered:
            if status.get(t.id, "pending") != "pending":
                continue
            if any(status.get(d) != "done" for d in t.depends_on):
                continue
            phase = self.phase_by_id[t.phase_id]
            ok = all(status.get(x.id, "pending") in finished
                     for pd in phase.depends_on for x in self.phase_by_id[pd].tasks)
            if ok:
                return t
        return None

    def waiting_on_blocked(self, status: dict[str, str]) -> list[str]:
        return [t.id for t in self.all_tasks() if status.get(t.id, "pending") == "pending"]


def append_phase(path: Path | str, phase: dict) -> None:
    """Append a phase (e.g. corrective tasks from an audit) to plan.yaml and re-validate."""
    import yaml

    path = Path(path)
    data = load_yaml(path)
    data.setdefault("phases", []).append(phase)
    Plan.from_dict(data)  # raises PlanError before we write anything invalid
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)


def clear_reopen_flags(path: Path | str, task_ids: list[str]) -> None:
    import yaml

    path = Path(path)
    data = load_yaml(path)
    for p in data.get("phases") or []:
        for t in p.get("tasks") or []:
            if str(t.get("id")) in task_ids:
                t.pop("reopen", None)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)
