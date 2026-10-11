"""N1: `status: done` in plan.yaml records work that exists before Autopilot."""
import pytest

from autopilot.plan import Plan, PlanError
from autopilot.state import State


def plan_of(statuses):
    tasks = [{"id": f"T{i}", "title": f"task {i}", **({"status": s} if s else {})} for i, s in enumerate(statuses, 1)]
    return Plan.from_dict({"goal": "g", "phases": [{"id": "P01", "title": "p", "tasks": tasks}]})


def test_done_tasks_are_done_and_next_ready_is_first_open(tmp_path):
    st = State(tmp_path / "state.db")
    plan = plan_of(["done"] * 6 + [None, None])
    st.sync_plan(plan)
    sm = st.status_map()
    assert [sm[f"T{i}"] for i in range(1, 7)] == ["done"] * 6
    assert sm["T7"] == sm["T8"] == "pending"
    assert plan.next_ready(sm).id == "T7"
    assert st.task("T1")["note"] == "done before Autopilot"


def test_other_status_value_fails_naming_the_task():
    with pytest.raises(PlanError) as e:
        plan_of([None, "blocked"])
    assert "T2" in str(e.value.errors) and "blocked" in str(e.value.errors)


@pytest.mark.parametrize("current", ["running", "blocked", "skipped"])
def test_existing_task_state_is_not_changed(tmp_path, current):
    st = State(tmp_path / "state.db")
    st.sync_plan(plan_of([None]))
    st.set_task("T1", status=current)
    st.sync_plan(plan_of(["done"]))
    assert st.status_map()["T1"] == current


def test_pending_row_becomes_done_and_removing_key_keeps_it(tmp_path):
    st = State(tmp_path / "state.db")
    st.sync_plan(plan_of([None]))
    st.sync_plan(plan_of(["done"]))
    assert st.status_map()["T1"] == "done"
    st.sync_plan(plan_of([None]))
    assert st.status_map()["T1"] == "done"


def test_plan_without_status_loads_as_before():
    assert plan_of([None]).task_by_id["T1"].status == ""


# N1: discovery pack
import subprocess
import sys

from autopilot.config import Config
from autopilot.context import PACK_CAP, discovery_pack


def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _repo(tmp_path):
    for d in ("notes", ".cursor/rules", "node_modules/x", ".venv/lib"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "PLAN.md").write_text("# Plan\n- [x] login page\n- [ ] export csv\n", encoding="utf-8")
    (tmp_path / "notes/session-3.md").write_text("did things\n", encoding="utf-8")
    (tmp_path / ".cursor/rules/x.mdc").write_text("rule\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
    (tmp_path / "node_modules/x/README.md").write_text("junk\n", encoding="utf-8")
    (tmp_path / ".venv/lib/NOTES.md").write_text("junk\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@example.com")
    _git(tmp_path, "config", "user.name", "dummy")
    for i, m in enumerate(["first change", "second change", "third change"]):
        (tmp_path / f"f{i}.txt").write_text(m, encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", m)


def _cfg(tmp_path, **test):
    return Config(tmp_path, {"commands": {"test": test.get("cmd", [])}, "onboard": {"test_timeout_sec": test.get("t", 300)}})


def test_pack_has_commits_paths_and_checkboxes(tmp_path):
    _repo(tmp_path)
    cmd = f'"{sys.executable}" -c "print(\'tests ok\')"'
    pack = discovery_pack(tmp_path, _cfg(tmp_path, cmd=[cmd]))
    for s in ("first change", "second change", "third change", "PLAN.md", "notes/session-3.md",
              ".cursor/rules/x.mdc", "pyproject.toml", "- [x] login page", "- [ ] export csv"):
        assert s in pack
    assert "node_modules" not in pack and ".venv" not in pack and ".git/" not in pack
    assert "exit code: 0" in pack and "tests ok" in pack


def test_hanging_test_command_is_stopped_and_reported(tmp_path):
    cmd = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    pack = discovery_pack(tmp_path, _cfg(tmp_path, cmd=[cmd], t=1))
    assert "timed out after 1 s" in pack


def test_not_a_git_repo_and_no_test_command(tmp_path):
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    pack = discovery_pack(tmp_path, _cfg(tmp_path))
    assert "## Git log" in pack and "(no git history)" in pack
    assert "no test command" in pack and "README.md" in pack


def test_pack_is_capped_and_marks_truncation(tmp_path):
    (tmp_path / "docs").mkdir()
    for i in range(1500):
        (tmp_path / "docs" / f"document-number-{i:05d}-with-a-long-name.md").write_text("x", encoding="utf-8")
    pack = discovery_pack(tmp_path, _cfg(tmp_path))
    assert len(pack) <= PACK_CAP + 200 and "truncated" in pack


# N1: onboarding prompt with the pack and the four rules
import yaml

from autopilot.cli import main as cli_main

PLAN6 = "# Plan\n" + "".join(f"- [x] step {i}\n" for i in range(1, 7)) + "- [ ] export csv\n"
AGENT = r"""import pathlib, sys
pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(), encoding="utf-8")
if len(sys.argv) > 2 and sys.argv[2] == "plan":
    tasks = [{"id": f"P01-T0{i}", "title": f"step {i}", "status": "done", "acceptance_criteria": ["works"]} for i in range(1, 7)]
    tasks.append({"id": "P01-T07", "title": "export csv", "acceptance_criteria": ["csv is written"]})
    plan = {"version": 1, "goal": "demo", "phases": [{"id": "P01", "title": "All", "goal": "g", "tasks": tasks}]}
    pathlib.Path(".agent/plan.yaml").write_text(__import__("yaml").safe_dump(plan), encoding="utf-8")
if len(sys.argv) > 2 and sys.argv[2] == "doc":
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/PLAN2.md").write_text("second plan\n", encoding="utf-8")
print('{"summary": "fake onboarding done"}')
"""


def _onboard_fixture(tmp_path, mode):
    _repo(tmp_path)
    (tmp_path / "PLAN.md").write_text(PLAN6, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "plan with six checked tasks")
    agent = tmp_path.parent / f"agent_{tmp_path.name}.py"
    agent.write_text(AGENT, encoding="utf-8")
    seen = tmp_path.parent / f"prompt_{tmp_path.name}.txt"
    from argparse import Namespace

    from autopilot.cli import cmd_init
    cmd_init(Namespace(path=str(tmp_path), stack=None, name=None, force=False, quiet=True))
    pj = tmp_path / ".agent" / "project.yaml"
    pj.write_text(pj.read_text(encoding="utf-8") + f"\nagent:\n  backend: command\n  command: '\"{sys.executable}\" \"{agent}\" \"{seen}\" {mode}'\n", encoding="utf-8")
    return seen


def test_onboard_prompt_has_log_plan_path_and_four_rules(tmp_path, capsys):
    seen = _onboard_fixture(tmp_path, "plan")
    cli_main(["onboard", "-C", str(tmp_path)])
    prompt = seen.read_text(encoding="utf-8")
    for s in ("plan with six checked tasks", "PLAN.md", "notes/session-3.md", "Rule 1", "Rule 2", "status: done",
              "Rule 3", "Rule 4"):
        assert s in prompt
    assert "{{discovery}}" not in prompt


def test_six_done_tasks_validate_and_next_lists_first_open(tmp_path, capsys):
    _onboard_fixture(tmp_path, "plan")
    assert cli_main(["onboard", "-C", str(tmp_path)]) in (0, None)
    out = capsys.readouterr().out
    assert "plan    OK" in out and "WARN  onboarding created" not in out
    assert cli_main(["validate", "-C", str(tmp_path)]) in (0, None)
    capsys.readouterr()
    cli_main(["next", "-C", str(tmp_path)])
    nxt = capsys.readouterr().out
    assert nxt.splitlines()[0].split()[1] == "P01-T07" and "P01-T01" not in nxt
    assert yaml.safe_load((tmp_path / ".agent/plan.yaml").read_text())["phases"][0]["tasks"][0]["status"] == "done"


def test_new_file_outside_agent_dir_is_warned(tmp_path, capsys):
    _onboard_fixture(tmp_path, "doc")
    cli_main(["onboard", "-C", str(tmp_path)])
    out = capsys.readouterr().out
    assert "WARN" in out and "docs/PLAN2.md" in out
    assert (tmp_path / "docs/PLAN2.md").exists()


# N4: one-screen summary after an adopt
def _adopt_plan(tmp_path, done=6, open_=4, owner=()):
    tasks = [{"id": f"P01-T{i:02d}", "title": f"step {i}", "status": "done"} for i in range(1, done + 1)]
    tasks += [{"id": f"P01-T{i:02d}", "title": f"open {i}", **({"owner_only": True} if f"P01-T{i:02d}" in owner else {})}
              for i in range(done + 1, done + open_ + 1)]
    plan = {"version": 1, "goal": "demo", "phases": [{"id": "P01", "title": "All", "goal": "g", "tasks": tasks}]}
    (tmp_path / ".agent").mkdir(exist_ok=True)
    (tmp_path / ".agent" / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    return tmp_path


def test_adopt_summary_counts_done_open_and_first_open_next(tmp_path):
    from autopilot.report import adopt_summary
    out = adopt_summary(_adopt_plan(tmp_path))
    assert "Done: 6 of 10 tasks. Open: 4." in out
    assert "P01 All: 6 of 10 done" in out
    assert "Next: P01-T07 open 7" in out


def test_adopt_summary_is_at_most_20_plain_lines(tmp_path):
    from autopilot.report import adopt_summary
    out = adopt_summary(_adopt_plan(tmp_path))
    assert len(out.splitlines()) <= 20
    assert "\x1b" not in out


def test_adopt_summary_works_without_state_db_and_creates_none(tmp_path):
    from autopilot.report import adopt_summary
    adopt_summary(_adopt_plan(tmp_path))
    assert not (tmp_path / ".agent" / "state.db").exists()


def test_adopt_summary_lists_owner_tasks_still_open(tmp_path):
    from autopilot.report import adopt_summary
    out = adopt_summary(_adopt_plan(tmp_path, owner=("P01-T08",)))
    assert "Waits for you (owner tasks): P01-T08." in out
