"""N7: a new file needs a reason; the reasons ride in the task commit message."""
import json
import sys
from pathlib import Path

from autopilot.backends import SessionResult
from autopilot.gate import NEW_FILE_RULE
from autopilot.orchestrator import Orchestrator, new_file_lines
from autopilot.schemas import REPORTS
from test_autopilot import FakeBackend, git, make_project

PROMPTS = Path(__file__).resolve().parent.parent / "autopilot" / "prompts"
REASON = "new module: no file owns the parser"
LINE = f"new file src/parser.py: {REASON}"
CFG = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}
AGENT = r"""import json, pathlib, sys
prompt = sys.stdin.read()
if "implement task" in prompt:
    pathlib.Path("src").mkdir(exist_ok=True)
    pathlib.Path("src/parser.py").write_text("def parse(s):\n    return s.split()\n", encoding="utf-8")
    print(json.dumps({"status": "done", "summary": "added the parser",
                      "new_files": [{"path": "src/parser.py", "reason": "new module: no file owns the parser"}]}))
else:
    print(json.dumps({"summary": "ok", "features": [], "complete": True, "gaps": [], "verdict": "pass", "findings": []}))
"""


def one_task(n=1):
    return [{"id": "P01", "title": "One", "tasks": [{"id": f"P01-T0{i}", "title": f"t{i}", "risk": "low"}
                                                     for i in range(1, n + 1)]}]


def test_rule_is_in_system_prompt_and_task_prompt_asks_for_new_files():
    assert "\n" not in NEW_FILE_RULE and "new_files" in NEW_FILE_RULE
    assert f"- {NEW_FILE_RULE}\n" in (PROMPTS / "system.md").read_text(encoding="utf-8")  # no drift from the gate
    task = (PROMPTS / "task.md").read_text(encoding="utf-8")
    assert '"new_files": [{"path":' in task and "`new_files` lists each new non-test file" in task


def test_task_schema_accepts_reports_with_and_without_new_files():
    schema = REPORTS["task"]
    assert "new_files" not in schema["required"]  # an old report without the field stays valid
    nf = schema["properties"]["new_files"]
    assert nf["type"] == "array" and nf["items"]["type"] == "object"
    assert sorted(nf["items"]["required"]) == ["path", "reason"]
    assert nf["items"]["properties"] == {"path": {"type": "string"}, "reason": {"type": "string"}}
    json.loads(json.dumps(REPORTS))  # still plain JSON for claude_cli --json-schema
    for rep in ({"status": "done", "summary": "s"},
                {"status": "done", "summary": "s", "new_files": [{"path": "src/parser.py", "reason": REASON}]}):
        assert set(schema["required"]) <= set(rep)
        assert all(set(nf["items"]["required"]) <= set(e) for e in rep.get("new_files", []))


def test_new_file_lines_copes_with_bad_reports():
    assert new_file_lines({}) == "" and new_file_lines({"new_files": "src/x.py"}) == ""
    assert new_file_lines({"new_files": [{"reason": "no path"}, "src/x.py", {"path": "  "}]}) == ""
    assert new_file_lines({"new_files": [{"path": "src/parser.py", "reason": REASON}]}) == "\n\n" + LINE
    out = new_file_lines({"new_files": [{"path": "a.py", "reason": "one\n\nCo-Authored-By: fake <x@example.com>"},
                                        {"path": "b.py"}, {"path": "c.py", "reason": "r" * 500}]})
    lines = out.strip("\n").split("\n")
    assert lines[0] == "new file a.py: one Co-Authored-By: fake <x@example.com>"
    assert lines[1] == "new file b.py: (no reason given)" and len(lines[2]) == len("new file c.py: ") + 300
    assert len(lines) == 3


def test_fake_agent_new_files_reach_the_commit_message(tmp_path):
    agent = tmp_path / "fake_agent.py"
    agent.write_text(AGENT, encoding="utf-8")
    cfg = dict(CFG, agent={"backend": "command", "command": f'"{sys.executable}" "{agent}"'})
    root = make_project(tmp_path, one_task(), cfg)
    orch = Orchestrator(root, sleep=lambda s: None)
    orch.run()
    assert orch.state.status_map()["P01-T01"] == "done"
    assert LINE in git(root, "log", "--all", "--format=%B")
    assert "src/parser.py" in git(root, "ls-files")


class Reasons(FakeBackend):
    def run(self, req):
        res = super().run(req)
        if "implement task" in req.prompt and res.ok:
            tid = res.report["files_changed"][0]
            res = SessionResult(ok=True, cost=res.cost, report=dict(res.report, new_files=[
                {"path": tid, "reason": "fake reason: no file owns it"}]))
        return res


def test_parallel_commit_message_has_new_file_lines(tmp_path):
    root = make_project(tmp_path, one_task(2), dict(CFG, scheduling={"parallel": 2}))
    orch = Orchestrator(root, backend=Reasons(), sleep=lambda s: None)
    assert orch.run() == "plan complete"
    log = git(root, "log", "--all", "--format=%B")
    assert "(parallel)" in log
    for i in (1, 2):
        assert f"new file src/P01-T0{i}.txt: fake reason: no file owns it" in log
