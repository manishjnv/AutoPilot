"""W25: a scope or test failure keeps the diff; any other failure still discards."""
import subprocess
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator
from test_autopilot import make_project
from test_heal import _tool_cmd
from test_reliability import NO_AUDIT, Resumable

SCOPED = [{"id": "P01", "title": "One", "tasks": [
    {"id": "P01-T01", "title": "a", "risk": "medium", "files_in_scope": ["docs/other.md"]}]}]


class Probe(Resumable):
    """Records what is on disk when each session starts. `extra`: files a session also writes (by call number)."""

    def __init__(self, behaviours, extra=None, reasons_from=2):
        super().__init__(behaviours)
        self.seen, self.extra, self.reasons_from = [], extra or {}, reasons_from

    def run(self, req):
        cwd = Path(req.cwd)
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True).stdout.strip()
        n = len(self.seen) + 1
        self.seen.append({"built": (cwd / "src" / "P01-T01.txt").exists(), "extra": (cwd / "docs" / "NEEDS-YOU.md").exists(),
                          "broken": (cwd / "BROKEN").exists(), "branch": branch})
        for rel in self.extra.get(n, []):
            (cwd / rel).parent.mkdir(exist_ok=True)
            (cwd / rel).write_text("x\n")
        res = super().run(req)
        if n >= self.reasons_from and isinstance(res.report, dict) and res.report.get("status") == "done":
            res.report["scope_additions"] = {"src/P01-T01.txt": "the task needs this file"}
        return res


def run(tmp_path, phases, fake, cfg=None):
    root = make_project(tmp_path, phases, {**NO_AUDIT, **(cfg or {})})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    return orch, orch.run()


def test_scope_failure_keeps_the_diff_and_the_retry_only_adds_the_reason(tmp_path):
    fake = Probe({"P01-T01": ["ok", "ok"]})
    orch, outcome = run(tmp_path, SCOPED, fake)
    assert outcome == "plan complete" and orch.state.task("P01-T01")["attempts"] == 2
    assert [s["built"] for s in fake.seen] == [False, True]  # attempt 2 started on attempt 1's files
    second = fake.reqs[1]
    assert second.resume and "The diff is kept" in second.prompt and "back at the state" not in second.prompt


def test_test_failure_keeps_the_files_and_shows_the_test_output(tmp_path):
    fake = Probe({"P01-T01": ["break", "ok"]})
    orch, outcome = run(tmp_path, [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a"}]}], fake)
    assert outcome == "plan complete"
    assert [(s["built"], s["broken"]) for s in fake.seen] == [(False, False), (True, True)]
    assert "The diff is kept" in fake.reqs[1].prompt and "(exit 1)" in fake.reqs[1].prompt


def test_protected_file_failure_still_discards(tmp_path):
    fake = Probe({"P01-T01": ["ok", "ok"]}, extra={1: ["docs/NEEDS-YOU.md"]})
    orch, outcome = run(tmp_path, [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a"}]}], fake)
    assert outcome == "plan complete"
    assert [(s["built"], s["extra"]) for s in fake.seen] == [(False, False), (False, False)]
    assert "The diff is kept" not in fake.reqs[1].prompt and "back at the state" in fake.reqs[1].prompt


def test_after_an_env_repair_the_next_attempt_starts_a_branch(tmp_path):
    marker = tmp_path / "tool-ok"
    marker.write_text("x")
    cfg = {"commands": {"setup": [f"python -c \"import os,sys; sys.exit(0 if os.path.exists(r'{marker}') else 1)\""],
                        "lint": [_tool_cmd(marker)]}}

    class Breaks(Probe):
        def run(self, req):
            if req.prompt.startswith("# Assignment: repair the project's environment"):
                marker.write_text("x")
                (Path(req.cwd) / "requirements.txt").write_text("mytool\n")
                return SessionResult(ok=True, report={"status": "done", "summary": "declared", "rca": {
                    "symptom": "s", "root_cause": "r", "fix": "requirements.txt:1", "prevention": "p"}})
            if len(self.seen) == 1:  # attempt 2 (kept): the tool vanishes
                marker.unlink(missing_ok=True)
            return super().run(req)
    fake = Breaks({"P01-T01": ["ok", "ok", "ok"]})
    orch, outcome = run(tmp_path, SCOPED, fake, cfg)
    assert outcome == "plan complete" and orch.env_repair_tried
    assert [s["built"] for s in fake.seen] == [False, True, False]  # attempt 3 is a fresh branch, not a kept diff
    assert fake.seen[2]["branch"] == "autopilot/P01-T01"
    assert "The diff is kept" not in fake.reqs[-1].prompt


def test_a_park_after_a_kept_attempt_leaves_main_clean(tmp_path):
    """A park after kept attempts leaves main clean (checkout -f drops staged files; _park also discards first)."""
    fake = Probe({"P01-T01": ["break", "break", "break"]})
    orch, outcome = run(tmp_path, [{"id": "P01", "title": "One", "tasks": [{"id": "P01-T01", "title": "a"}]}], fake,
                        {"unstick": {"enabled": False}})
    assert orch.state.task("P01-T01")["status"] == "blocked"
    assert orch.git.branch() == "main" and orch.git.is_clean()
    assert not (Path(orch.root) / "BROKEN").exists() and not (Path(orch.root) / "src" / "P01-T01.txt").exists()
