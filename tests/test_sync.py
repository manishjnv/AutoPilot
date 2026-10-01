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


# ---------------------------------------------------------------- PR mode
class FakeGH:
    """Stands in for the gh CLI: `pr merge` moves the remote's main to the branch, like GitHub's merge would."""

    def __init__(self, root, checks=()):
        self.root, self.checks, self.calls = root, list(checks), []

    def __call__(self, *args, check=True, timeout=120):
        from autopilot.gitops import GitError
        from autopilot.proc import Proc
        self.calls.append(" ".join(args[:2]))
        rc, out = 0, ""
        if args[:2] == ("pr", "checks"):
            rc, out = self.checks.pop(0) if self.checks else (0, "all checks were successful")
        elif args[:2] == ("pr", "merge"):
            git(self.root, "push", "-q", "origin", f"refs/heads/{args[2]}:refs/heads/main")
        if check and rc:
            raise GitError(f"gh failed: {out}")
        return Proc(rc, out, "")


PR = {"git": {"push": True, "mode": "pr"}}


def pr_run(tmp_path, checks=(), fake=None):
    root, remote, _ = with_remote(tmp_path, PR)
    orch = Orchestrator(root, backend=fake or FakeBackend(), sleep=lambda s: None)
    orch._gh = FakeGH(root, checks)
    return root, remote, orch, orch.run()


def test_pr_mode_merges_on_github_when_ci_is_green(tmp_path):
    root, remote, orch, outcome = pr_run(tmp_path)
    assert outcome == "plan complete"
    assert orch._gh.calls == ["pr create", "pr checks", "pr merge"] * 2  # P01-T01 and P01-T02
    assert git(remote, "rev-parse", "main") == git(root, "rev-parse", "main")
    assert "[autopilot] P01-T01" in git(root, "log", "--format=%s")
    assert git(root, "ls-remote", "--heads", "origin", "autopilot/P01-T01") == ""  # branch cleaned up


def test_red_ci_closes_the_pr_and_retries_with_the_ci_output(tmp_path):
    fake = FakeBackend()
    _, _, orch, outcome = pr_run(tmp_path, checks=[(1, "unit-tests\tfail\t1m2s")], fake=fake)
    assert outcome == "plan complete" and orch.state.task("P01-T01")["attempts"] == 2
    assert orch._gh.calls[:6] == ["pr create", "pr checks", "pr close", "pr create", "pr checks", "pr merge"]
    retry = [p for t, p in fake.prompts if t == "P01-T01"][1]
    assert "CI failed on the pull request" in retry and "unit-tests" in retry


def test_no_checks_configured_counts_as_green(tmp_path):
    _, _, orch, outcome = pr_run(tmp_path, checks=[(1, "no checks reported on the 'autopilot/P01-T01' branch")])
    assert outcome == "plan complete" and orch._gh.calls[-1] == "pr merge"


def test_pr_mode_without_push_is_refused(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], {**BASE, "git": {"mode": "pr"}})
    outcome = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run()
    assert outcome.startswith("fatal: config:") and "git.mode: pr needs git.push: true" in outcome
