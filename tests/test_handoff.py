"""N11: hand a task to the next runner at a long usage limit (fake runners only, no subprocess, no network)."""
import re
import time
from pathlib import Path

from autopilot.backends import SessionResult
from test_autopilot import FakeBackend, git, make_project
from test_orchestrator import events, orch_for

PHASES = [{"id": "P01", "title": "One", "tasks": [
    {"id": "P01-T01", "title": "a", "description": "build a", "risk": "low", "acceptance_criteria": ["a works"]},
    {"id": "P01-T02", "title": "b", "risk": "low", "depends_on": ["P01-T01"]},
    {"id": "P01-T03", "title": "c", "risk": "low", "depends_on": ["P01-T02"]}]}]


class Claude(FakeBackend):
    """The first runner: its first task session ends on a usage limit that resets in `wait` seconds."""

    def __init__(self, wait):
        super().__init__()
        self.wait, self.limited = wait, False

    def run(self, req):
        if "implement task P01-T01" in req.prompt and not self.limited:
            self.limited = True
            (Path(req.cwd) / "wip.txt").write_text("half done\n")
            return SessionResult(ok=False, error="limit", rate_limited=True, reset_at=time.time() + self.wait)
        return super().run(req)


class Codex(FakeBackend):
    def __init__(self, orch=None):
        super().__init__()
        self.orch, self.handoffs = orch, []

    def run(self, req):
        f = Path(req.cwd) / "HANDOFF.md"
        if f.exists():
            self.handoffs.append(f.read_text(encoding="utf-8"))
        if "implement task P01-T02" in req.prompt:  # the first runner's window reopens while this one works
            self.orch.state.set_meta("handoff_until", time.time() - 1)
        return super().run(req)


def build(tmp_path, wait, fallback):
    root = make_project(tmp_path, PHASES, {"agent": {"fallback": fallback}})
    claude, codex = Claude(wait), Codex()
    orch = orch_for(root, claude)
    codex.orch, orch._fallback_backend = orch, lambda name: codex
    return root, orch, claude, codex


def tasks_of(fake):
    return [c[0] for c in fake.calls if c[0].startswith("P01-")]


def test_handoff_continues_under_the_next_runner(tmp_path):
    root, orch, claude, codex = build(tmp_path, 7200, ["codex", "copilot"])
    assert orch.run() == "app complete"
    assert tasks_of(codex) == ["P01-T01", "P01-T02"]  # T01 handed over, T02 still in the closed window
    assert tasks_of(claude) == ["P01-T03"]            # after the reset the first runner is used again
    text = codex.handoffs[0]
    assert all(h in text for h in ("## Goal", "## Done", "## Next", "## Failing tests"))
    assert "build a" in text and "a works" in text and "wip: handoff at usage limit" in text
    assert len(events(orch, "handoff")) == 1
    assert not (root / "HANDOFF.md").exists() and not re.search(r"^HANDOFF\.md$", git(root, "ls-files"), re.M)
    assert "wip.txt" in git(root, "ls-files")  # the first runner's work is kept


def test_short_reset_keeps_the_pause(tmp_path):
    _root, orch, claude, codex = build(tmp_path, 600, ["codex"])
    assert orch.run() == "app complete"
    assert not codex.calls and not events(orch, "handoff")
    assert claude.limited and tasks_of(claude) == ["P01-T01", "P01-T02", "P01-T03"]  # paused, then the same runner


def test_empty_fallback_keeps_the_pause(tmp_path):
    _root, orch, claude, codex = build(tmp_path, 7200, [])
    assert orch.run() == "app complete"
    assert not codex.calls and not events(orch, "handoff")
    assert re.search(r"usage limit reached", " ".join(events(orch, "rate_limit")))
