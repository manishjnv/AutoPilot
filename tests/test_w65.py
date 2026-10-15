"""W65: a half-built project is adopted, never rebuilt (template plan refused, undo tag, deleted-file reason,
the owner's files survive a clean, another version control gets one line)."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

from autopilot.cli import ADOPT_LINE, NO_PROJECT_LINE, TEMPLATE_LINE, cmd_run, template_plan
from autopilot.cli import main as cli_main
from autopilot.gate import DELETE_RULE, missing_delete_reasons
from autopilot.gitops import Git, other_vcs, vcs_line
from autopilot.report import adopt_summary

PROMPTS = Path(__file__).resolve().parent.parent / "autopilot" / "prompts"


class Cfg:
    def __init__(self, **kw):
        self.kw = kw

    def get(self, key, default=None):
        return self.kw.get(key, default)


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    g = Git(root)
    g.ensure_repo("main")
    return root, g


def _no_login_check(monkeypatch):  # the login check (H2) runs first and is not under test here
    monkeypatch.setattr("autopilot.cli.preflight", lambda cfg: True)
    monkeypatch.setattr("autopilot.cli.cmd_preflight", lambda args: 0)


def test_template_plan_refuses_run_and_next(tmp_path, monkeypatch, capsys):
    _no_login_check(monkeypatch)
    root = tmp_path / "empty"
    root.mkdir()
    assert cli_main(["init", "-C", str(root), "--stack", "generic"]) == 0
    assert template_plan(root)
    assert cmd_run(SimpleNamespace(path=str(root), verbose=False, clear_stop=False, max_sessions=None,
                                   no_page=True, no_browser=True, no_watch=True)) == 2
    assert cli_main(["next", "-C", str(root)]) == 2
    assert capsys.readouterr().out.count(TEMPLATE_LINE) == 2
    (root / ".agent" / "plan.yaml").write_text(
        "goal: a real app\nphases:\n  - id: P01\n    title: One\n    tasks:\n      - id: P01-T01\n        title: real work\n",
        encoding="utf-8")
    assert not template_plan(root)


def test_init_in_a_code_folder_points_to_adopt_and_run_refuses_the_template(tmp_path, monkeypatch, capsys):
    _no_login_check(monkeypatch)
    root = tmp_path / "code"
    root.mkdir()
    (root / "app.py").write_text("print(1)\n", encoding="utf-8")
    assert cli_main(["init", "-C", str(root), "--stack", "generic"]) == 0
    assert "next:  " + ADOPT_LINE in capsys.readouterr().out  # the template plan is written; the onboarding overwrites it
    assert cli_main(["run", "-C", str(root)]) == 2
    assert cli_main(["start", "-C", str(root)]) == 2  # the detach never starts on the template
    assert capsys.readouterr().out.count(TEMPLATE_LINE) == 2


def test_run_in_a_code_folder_without_a_project_reads_first(tmp_path, monkeypatch, capsys):
    root = tmp_path / "code2"
    root.mkdir()
    (root / "main.go").write_text("package main\n", encoding="utf-8")
    monkeypatch.chdir(root)
    assert cli_main(["run"]) == 2  # no terminal under pytest: the line, never the last project used
    assert NO_PROJECT_LINE in capsys.readouterr().out


def test_baseline_tag_is_set_once_and_never_moved(tmp_path):
    root, g = _repo(tmp_path)
    first = _git(root, "rev-parse", "autopilot/baseline").strip()
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    g.commit_all("more")
    g.ensure_repo("main")
    assert _git(root, "rev-parse", "autopilot/baseline").strip() == first != g.head()


def test_other_vcs_gets_one_line(tmp_path):
    root = tmp_path / "hg"
    root.mkdir()
    (root / ".hg").mkdir()
    assert other_vcs(root) == "Mercurial"
    assert "add .git and .agent to your Mercurial ignore file" in vcs_line("Mercurial")
    (root / ".git").mkdir()
    assert other_vcs(root) == ""
    assert other_vcs(tmp_path) == ""


def test_deleted_file_needs_a_reason(tmp_path):
    root, g = _repo(tmp_path)
    for p, t in (("src/a.py", "x = 1\n"), ("tests/test_a.py", "def test_a():\n    assert 1\n"), ("docs/n.md", "n\n")):
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text(t, encoding="utf-8")
    g.commit_all("base")
    for p in ("src/a.py", "tests/test_a.py", "docs/n.md"):
        (root / p).unlink()
    g.staged_files()
    problems = missing_delete_reasons(Cfg(), g, {})
    assert len(problems) == 1 and "src/a.py" in problems[0] and "docs/n.md" in problems[0]
    assert "tests/test_a.py" not in problems[0] and problems[0].endswith(DELETE_RULE)
    report = {"deleted_files": [{"path": "src/a.py", "reason": "dead"}, {"path": "docs/n.md", "reason": "in README"}]}
    assert missing_delete_reasons(Cfg(), g, report) == []
    assert f"- {DELETE_RULE}\n" in (PROMPTS / "system.md").read_text(encoding="utf-8")  # no drift from the gate
    assert "`deleted_files` lists each deleted non-test file" in (PROMPTS / "task.md").read_text(encoding="utf-8")


def test_discard_keeps_the_owners_files(tmp_path):
    root, g = _repo(tmp_path)
    (root / "owner.txt").write_text("mine\n", encoding="utf-8")  # added by the owner between two attempts
    g.start_branch("autopilot/P01-T01", "main")
    assert (root / "owner.txt").exists()
    (root / "agent.txt").write_text("session work\n", encoding="utf-8")  # written by the session
    g.staged_files()  # the gate stages everything, the owner's file too
    g.discard()
    assert (root / "owner.txt").exists() and not (root / "agent.txt").exists()
    assert _git(root, "status", "--porcelain").strip() == "?? owner.txt"


def test_adopt_summary_ends_with_the_undo_point(tmp_path):
    from test_autopilot import make_project, phases_basic
    root = make_project(tmp_path, phases_basic())
    text = adopt_summary(root)
    assert "git reset --hard autopilot/baseline" in text and ".env and other ignored files" in text
