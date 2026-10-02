"""P3: independent first attempts run at the same time in git worktrees, then gate and merge one by one."""
import threading
from pathlib import Path

from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project, phases_basic

PAR = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "scheduling": {"parallel": 3}}


def independent(n=3, risk="low"):
    return [{"id": "P01", "title": "One",
             "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": risk} for i in range(1, n + 1)]}]


class Together(FakeBackend):
    """The first `n` task sessions must overlap in time, or the barrier breaks the test."""

    def __init__(self, n, **kw):
        super().__init__(**kw)
        self.barrier, self.cwds, self.lock = threading.Barrier(n, timeout=20), [], threading.Lock()

    def run(self, req):
        if "implement task" in req.prompt and len(self.cwds) < self.barrier.parties:
            with self.lock:
                self.cwds.append(req.cwd)
            self.barrier.wait()
        return super().run(req)


def run(tmp_path, phases, fake, cfg=PAR):
    root = make_project(tmp_path, phases, cfg)
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    return root, orch, orch.run()


def test_independent_tasks_run_together_in_worktrees(tmp_path):
    fake = Together(3)
    root, orch, outcome = run(tmp_path, independent(3), fake)
    assert outcome == "plan complete"
    assert all(Path(c) != root and not Path(c).is_relative_to(root) for c in fake.cwds)  # outside the repo
    assert {orch.state.status_map()[f"P01-T0{i}"] for i in (1, 2, 3)} == {"done"}
    files = git(root, "ls-files")
    assert all(f"src/P01-T0{i}.txt" in files for i in (1, 2, 3))
    log = git(root, "log", "--format=%s")
    assert log.count("[autopilot] merge P01-T0") == 3 and log.count("[autopilot] docs for P01-T0") == 3
    assert not any("autopilot/P01" in b for b in git(root, "branch", "--list").splitlines())  # branches cleaned
    assert len(git(root, "worktree", "list").strip().splitlines()) == 1  # only the main checkout is left
    assert git(root, "status", "--porcelain").strip() == ""


def test_dependent_or_risky_tasks_stay_serial(tmp_path):
    root, orch, outcome = run(tmp_path, phases_basic(), FakeBackend())  # T02 needs T01; P02-T01 is high risk
    assert outcome == "plan complete" and set(orch.state.status_map().values()) == {"done"}
    assert "[autopilot] docs for" not in git(root, "log", "--format=%s")  # the parallel path never ran


class Clash(Together):
    """Every task writes the same file with different content: the second merge conflicts."""

    def run(self, req):
        res = super().run(req)
        if "implement task" in req.prompt:
            (Path(req.cwd) / "shared.txt").write_text(req.prompt.split("implement task ", 1)[1].split()[0])
        return res


def test_merge_conflict_goes_back_to_the_queue_and_is_redone(tmp_path):
    fake = Clash(2)
    root, orch, outcome = run(tmp_path, independent(2), fake)
    assert outcome == "plan complete"
    assert set(orch.state.status_map().values()) == {"done"}
    t2 = [c for c in fake.calls if c[0] == "P01-T02"]
    assert len(t2) == 2 and orch.state.task("P01-T02")["attempts"] == 2  # parallel try + serial redo
    assert "merge conflict with work merged in parallel" in fake.prompts[-1][1]


def test_gate_failure_in_a_worktree_retries_serially(tmp_path):
    fake = Together(2, behaviours={"P01-T02": ["break", "ok"]})
    _, orch, outcome = run(tmp_path, independent(2), fake)
    assert outcome == "plan complete" and orch.state.task("P01-T02")["attempts"] == 2
    assert "failed verification" in fake.prompts[-1][1]


def test_parallel_off_by_default(tmp_path):
    fake = FakeBackend()
    root = make_project(tmp_path, independent(3), {"audit": {"completion_audit": False}})
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    assert "[autopilot] docs for" not in git(root, "log", "--format=%s")


# ---------------------------------------------------------------- LEARNINGS.md
class Learner(FakeBackend):
    def run(self, req):
        res = super().run(req)
        if "implement task P01-T01" in req.prompt and "failed verification" in req.prompt:
            res.report["learning"] = "BROKEN marker files fail the test command; never create them"
        return res


def test_a_task_that_passes_after_failing_leaves_a_learning(tmp_path):
    cfg = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}
    root = make_project(tmp_path, independent(2), cfg)
    fake = Learner(behaviours={"P01-T01": ["break", "ok"]})
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    text = (root / ".agent" / "LEARNINGS.md").read_text(encoding="utf-8")
    assert "[P01-T01] BROKEN marker files fail the test command" in text and "P01-T02" not in text
    assert "LEARNINGS.md" in git(root, "ls-files", ".agent")  # committed with the task
    retry = [p for t, p in fake.prompts if t == "P01-T01"][1]
    assert 'add `"learning"`' in retry


def test_learnings_reach_every_later_session_and_are_protected(tmp_path):
    from autopilot.config import Config
    from autopilot.gate import protected_files
    cfg = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}
    root = make_project(tmp_path, independent(2), cfg)
    (root / ".agent" / "LEARNINGS.md").write_text("# Learnings\n\n- [x] [P00] LEARN-MARK use utf-8\n", encoding="utf-8")

    class Rec(FakeBackend):
        systems = []

        def run(self, req):
            Rec.systems.append(req.system_append)
            return super().run(req)

    Orchestrator(root, backend=Rec(), sleep=lambda s: None).run()
    assert Rec.systems and all("LEARN-MARK use utf-8" in s for s in Rec.systems)
    assert ".agent/LEARNINGS.md" in protected_files(Config.load(root))


def test_fallback_learning_without_agent_text(tmp_path):
    cfg = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}
    root = make_project(tmp_path, independent(1), cfg)
    Orchestrator(root, backend=FakeBackend(behaviours={"P01-T01": ["break", "ok"]}), sleep=lambda s: None).run()
    text = (root / ".agent" / "LEARNINGS.md").read_text(encoding="utf-8")
    assert "[P01-T01] failed first with:" in text and "passed on attempt 2 with" in text


def test_parallel_sessions_also_bring_the_cli_usage_figure(tmp_path):
    import time

    class Metered(Together):  # G1: every session reports the CLI's own usage figure
        def run(self, req):
            res = super().run(req)
            res.window = {"five_hour": {"pct": 0.4, "reset": time.time() + 3600}, "status": "allowed"}
            return res
    _, orch, outcome = run(tmp_path, independent(3), Metered(3))
    assert outcome == "plan complete" and orch.state.get_meta("window_seen")["five_hour"]["pct"] == 0.4
