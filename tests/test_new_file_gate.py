"""N7: a new file needs a reason; the reasons ride in the task commit message."""
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from autopilot.backends import SessionResult
from autopilot.config import Config
from autopilot.gate import NEW_FILE_RULE, task_gate
from autopilot.gitops import Git
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


# P07-T02: the gate checks the reasons
NOTES_REASON = "new module: no file owns the parser"
ON = {"gate": {"new_file_reasons": True}}


def sh(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def put(root, rel, text="x = 1\n"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def gate_repo(tmp_path, on=True):
    sh(tmp_path, "init", "-q")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("core.autocrlf", "false")):
        sh(tmp_path, "config", k, v)
    put(tmp_path, "src/old_name.py", "def old():\n    return 1\n" * 5)
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-qm", "init")
    cfg = Config.load(tmp_path)
    cfg.data["commands"]["test"] = [f'"{sys.executable}" -c "pass"']
    cfg.data["gate"]["new_file_reasons"] = on
    return cfg


def gate(cfg, report):
    task = SimpleNamespace(allow_no_changes=False, allow_test_changes=False, files_in_scope=[], verify=[])
    return task_gate(cfg, Git(cfg.root), task, report=report)


def test_new_file_without_reason_fails_with_rule_quoted(tmp_path):
    cfg = gate_repo(tmp_path)
    put(tmp_path, "NOTES2.md", "notes\n")
    g = gate(cfg, {"status": "done", "summary": "add notes"})
    assert not g.ok and g.results == []  # like every guard: the commands do not run
    assert g.problems == [f"new file without a reason: NOTES2.md. {NEW_FILE_RULE}"]
    assert g.report().endswith(NEW_FILE_RULE)


def test_new_file_with_reason_passes(tmp_path):
    cfg = gate_repo(tmp_path)
    put(tmp_path, "NOTES2.md", "notes\n")
    g = gate(cfg, {"status": "done", "summary": "add notes", "new_files": [{"path": "NOTES2.md", "reason": NOTES_REASON}]})
    assert g.ok and g.problems == [] and g.results and g.results[0].rc == 0


def test_test_file_agent_file_and_rename_need_no_reason(tmp_path):
    cfg = gate_repo(tmp_path)
    put(tmp_path, "tests/test_parser.py", "def test_p():\n    assert True\n")
    put(tmp_path, "pkg/test_util.py", "def test_u():\n    assert True\n")
    put(tmp_path, ".agent/notes.md", "n\n")
    sh(tmp_path, "mv", "src/old_name.py", "src/new_name.py")
    g = gate(cfg, {"status": "done", "summary": "tests and a rename"})
    assert g.ok, g.report()


def test_rename_counts_even_when_git_rename_detection_is_off(tmp_path):
    cfg = gate_repo(tmp_path)
    sh(tmp_path, "config", "diff.renames", "false")
    sh(tmp_path, "mv", "src/old_name.py", "src/new_name.py")
    assert gate(cfg, {"status": "done", "summary": "rename"}).ok


def test_report_none_or_switch_off_skips_the_check(tmp_path):
    cfg = gate_repo(tmp_path)
    put(tmp_path, "NOTES2.md", "notes\n")
    assert gate(cfg, None).ok  # old callers
    cfg.data["gate"]["new_file_reasons"] = False
    assert gate(cfg, {"summary": "add notes"}).ok
    assert Config.load(tmp_path).get("gate.new_file_reasons") is False  # default: existing projects keep working


def test_reason_paths_are_normalised_and_blank_reasons_do_not_count(tmp_path):
    cfg = gate_repo(tmp_path)
    put(tmp_path, "src/a.py")
    put(tmp_path, "src/b.py")
    put(tmp_path, "src/c.py")
    rep = {"new_files": [{"path": "./src/a.py", "reason": "r"}, {"path": r"src\b.py", "reason": "r"},
                         {"path": "src/c.py", "reason": "   "}, "src/c.py", {"reason": "no path"}]}
    g = gate(cfg, rep)
    assert g.problems == [f"new file without a reason: src/c.py. {NEW_FILE_RULE}"]
    assert gate(cfg, {"new_files": "src/c.py"}).problems[0].startswith("new file without a reason: src/a.py, src/b.py")
    assert not gate(cfg, ["not", "a", "dict"]).ok


def test_long_list_is_cut_and_the_rule_stays_last(tmp_path):
    cfg = gate_repo(tmp_path)
    for i in range(25):
        put(tmp_path, f"src/m{i:02}.py")
    (p,) = gate(cfg, {"summary": "many"}).problems
    assert ", and 5 more. " in p and p.endswith(NEW_FILE_RULE) and "src/m19.py" in p and "src/m20.py" not in p


class Notes(FakeBackend):
    """Attempt 1 adds NOTES2.md with no reason; attempt 2 gives the reason."""

    def run(self, req):
        m = re.search(r"implement task (\S+)", req.prompt)
        if not m:
            return super().run(req)
        tid = m.group(1)
        self.prompts.append((tid, req.prompt))
        n = sum(1 for c in self.calls if c[0] == tid)
        self.calls.append((tid, req.model))
        (Path(req.cwd) / "NOTES2.md").write_text(f"notes {tid}\n", encoding="utf-8")
        rep = {"status": "done", "summary": "add notes"}
        if n:
            rep["new_files"] = [{"path": "NOTES2.md", "reason": NOTES_REASON}]
        return SessionResult(ok=True, cost=0.1, report=rep)


def test_missing_reason_retries_with_the_rule_in_the_next_prompt(tmp_path):
    root = make_project(tmp_path, one_task(), dict(CFG, **ON))
    be = Notes()
    orch = Orchestrator(root, backend=be, sleep=lambda s: None)
    orch.run()
    assert orch.state.status_map()["P01-T01"] == "done"
    assert len(be.prompts) == 2
    assert "new file without a reason: NOTES2.md" in be.prompts[1][1] and NEW_FILE_RULE in be.prompts[1][1]
    assert "new file without a reason" not in be.prompts[0][1]
    assert f"new file NOTES2.md: {NOTES_REASON}" in git(root, "log", "--all", "--format=%B")


def test_parallel_gate_checks_reasons_too(tmp_path):
    root = make_project(tmp_path, one_task(2), dict(CFG, scheduling={"parallel": 2}, **ON))
    be = FakeBackend()  # adds src/<task>.txt with no new_files
    orch = Orchestrator(root, backend=be, sleep=lambda s: None)
    orch.run()
    retries = [p for tid, p in be.prompts if "new file without a reason: src/" in p]
    assert retries and all(NEW_FILE_RULE in p for p in retries)
