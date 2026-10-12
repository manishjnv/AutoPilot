"""N1 conflicts: two plan documents disagree on a task; the git log, then the newer file, decides."""
import os
import subprocess

from autopilot.context import document_conflicts


def git(root, *args, when="2026-01-01T00:00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    cfg = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", *cfg, *args], cwd=root, env=env, check=True, capture_output=True)


def commit(root, name, text, msg, when):
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", name)
    git(root, "commit", "-m", msg, when=when)


def repo(tmp_path, plan_when, todo_when, log_msg):
    git(tmp_path, "init")
    commit(tmp_path, "PLAN.md", "- [x] Add login\n", "docs: plan", plan_when)
    commit(tmp_path, "TODO.md", "- [ ] Add login\n", log_msg, todo_when)
    out = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=True)
    return out.stdout


def test_git_commit_wins(tmp_path):
    log = repo(tmp_path, "2026-01-01T00:00:00", "2026-02-01T00:00:00", "feat: add login")
    assert document_conflicts(tmp_path, log) == ["TODO.md says open, git shows the commit: marked done"]


def test_newer_document_wins_without_commit(tmp_path):
    log = repo(tmp_path, "2026-01-01T00:00:00", "2026-02-01T00:00:00", "docs: todo")
    assert document_conflicts(tmp_path, log) == ["PLAN.md says done, TODO.md is newer: marked open"]


def test_no_conflict(tmp_path):
    git(tmp_path, "init")
    commit(tmp_path, "PLAN.md", "- [x] Add login\n", "docs: plan", "2026-01-01T00:00:00")
    commit(tmp_path, "TODO.md", "- [x] Add login\n", "docs: todo", "2026-02-01T00:00:00")
    assert document_conflicts(tmp_path, "") == []
