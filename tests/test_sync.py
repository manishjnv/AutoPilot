"""P4: GitHub is the source of truth (pull before work, stop on divergence), a failed push stops the run, PR mode."""
import subprocess

import yaml

from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


def commit(path, msg):
    git(path, "add", "-A")
    git(path, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-qm", msg)


def with_remote(tmp_path, cfg=None, phases=None):
    """A project whose main is already on a bare remote, plus an owner clone of that remote."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    root = make_project(tmp_path, phases or phases_basic()[:1], {**BASE, **(cfg or {})})
    commit(root, "init")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "origin", "main")
    owner = tmp_path / "owner"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(remote), str(owner)], check=True)
    return root, remote, owner


def add_task_upstream(owner):
    plan_path = owner / ".agent" / "plan.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    plan["phases"][0]["tasks"].append({"id": "P01-T09", "title": "added by the owner on GitHub", "risk": "low"})
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    commit(owner, "owner adds a task")
    git(owner, "push", "-q", "origin", "main")


def test_run_start_pulls_new_commits_and_their_plan(tmp_path):
    root, _, owner = with_remote(tmp_path)
    add_task_upstream(owner)
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert "owner adds a task" in git(root, "log", "--format=%s")
    assert orch.state.status_map().get("P01-T09") == "done"


def test_diverged_history_stops_the_run(tmp_path):
    root, _, owner = with_remote(tmp_path)
    add_task_upstream(owner)
    (root / "local.txt").write_text("x")
    commit(root, "local-only commit")
    before = git(root, "rev-parse", "main")
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    outcome = orch.run()
    assert "diverged" in outcome and "Reconcile" in outcome
    assert git(root, "rev-parse", "main") == before and not orch.state.tasks("done")
    assert any("diverged" in e["message"] for e in orch.state.events(50) if e["kind"] == "fatal")


def test_offline_remote_only_skips_the_sync(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    assert Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run() == "plan complete"


def test_failed_push_stops_the_run_after_one_retry(tmp_path):
    root = make_project(tmp_path, phases_basic(), {**BASE, "git": {"push": True, "pull": False}})
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", str(tmp_path / "gone.git"))
    sleeps = []
    orch = Orchestrator(root, backend=FakeBackend(), sleep=sleeps.append)
    outcome = orch.run()
    assert outcome.startswith("push to origin failed") and 30 in sleeps
    assert orch.state.status_map()["P01-T01"] == "done"  # merged before the push: never redone
    assert orch.state.status_map()["P01-T02"] == "pending"


def test_push_reaches_the_remote(tmp_path):
    root, remote, _ = with_remote(tmp_path, {"git": {"push": True}})
    assert Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run() == "plan complete"
    assert git(remote, "rev-parse", "main") == git(root, "rev-parse", "main")
