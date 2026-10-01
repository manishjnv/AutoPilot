"""L7: docs/STATUS.md is regenerated from plan.yaml; docs/BACKLOG.md ideas reach the plan through one replan."""
from pathlib import Path

import yaml

from autopilot.backends import SessionResult
from autopilot.config import Config
from autopilot.gate import protected_files
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project, phases_basic
from test_intake import FakeGH, Triager

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


class Planner(FakeBackend):
    """A replan that turns the backlog idea into a new phase; `ok=False` = the replan session fails."""

    def __init__(self, ok=True, **kw):
        super().__init__(**kw)
        self.ok, self.replans = ok, []

    def run(self, req):
        if "replan remaining work" not in req.prompt:
            return super().run(req)
        self.replans.append(req.prompt)
        if not self.ok:
            return SessionResult(ok=False, error="boom")
        p = Path(req.cwd) / ".agent" / "plan.yaml"
        plan = yaml.safe_load(p.read_text(encoding="utf-8"))
        plan["phases"].append({"id": "P09", "title": "Dark mode", "tasks": [{"id": "P09-T01", "title": "dark mode"}]})
        p.write_text(yaml.safe_dump(plan), encoding="utf-8")
        return SessionResult(ok=True, report={"summary": "planned dark mode", "added": ["P09-T01"]})


def project(tmp_path, backlog=None, cfg=None):
    root = make_project(tmp_path, phases_basic()[:1], {**BASE, **(cfg or {})})
    if backlog is not None:
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "BACKLOG.md").write_text(backlog, encoding="utf-8")
    return root


def test_status_md_is_the_plan_as_a_checklist(tmp_path):
    root = project(tmp_path)
    assert Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).run() == "plan complete"
    text = git(root, "show", "HEAD:docs/STATUS.md")
    assert "- [x] P01-T01" in text and "- [x] P01-T02" in text and "2/2 tasks done" in text
    assert "(the source of truth)" in text


def test_backlog_idea_is_planned_built_and_moved_to_imported(tmp_path):
    root = project(tmp_path, "# Backlog\n\n- add dark mode\n")
    fake = Planner()
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert len(fake.replans) == 1 and "- add dark mode" in fake.replans[0]
    assert orch.state.status_map()["P09-T01"] == "done"
    text = (root / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    new, imported = text.split("## Imported")
    assert "add dark mode" not in new and "] add dark mode" in imported
    assert "backlog: 1 idea(s) planned by a replan; new tasks: P09-T01" in (root / ".agent" / "DECISIONS.md").read_text()
    assert orch.docs.backlog() == []


def test_failed_import_is_not_retried_until_the_backlog_changes(tmp_path):
    root = project(tmp_path, "- idea one\n")
    fake = Planner(ok=False)
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch.run() == "plan complete"
    orch.import_backlog()
    assert len(fake.replans) == 1 and orch.docs.backlog() == ["idea one"]
    orch.docs.backlog_add("idea two")
    orch.import_backlog()
    assert len(fake.replans) == 2


def test_backlog_add_and_import_keep_the_file_shape(tmp_path):
    root = project(tmp_path)
    d = Orchestrator(root, backend=FakeBackend()).docs
    d.backlog_add("first")
    d.backlog_add("second")
    assert d.backlog() == ["first", "second"]
    d.backlog_imported(["first"])
    d.backlog_add("third")
    assert d.backlog() == ["second", "third"]
    text = (root / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    assert text.startswith("# Backlog") and text.count("## Imported") == 1 and "] first" in text


def test_backlog_is_protected_from_sessions(tmp_path):
    assert "docs/BACKLOG.md" in protected_files(Config.load(project(tmp_path)))


def test_feature_issue_goes_to_the_backlog(tmp_path):
    root = project(tmp_path, cfg={"intake": {"enabled": True}, "replan": {"enabled": False}})
    idea = {"kind": "feature", "actionable": False, "title": "Export to CSV",
            "description": "Users want to download their list as a spreadsheet.", "reason": "feature"}
    gh = FakeGH(issues=[{"number": 9, "title": "csv pls", "body": "b"}])
    orch = Orchestrator(root, backend=Triager({9: idea}), sleep=lambda s: None)
    orch._gh = gh
    assert orch.run() == "plan complete"
    assert orch.docs.backlog() == ["Export to CSV: Users want to download their list as a spreadsheet. (GitHub issue #9)"]
    assert "added to the project's backlog" in gh.said("comment")[0][-1] and not gh.said("close")
