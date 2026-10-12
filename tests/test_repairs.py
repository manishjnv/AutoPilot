"""Q20: five repairs without a question, one fixture each. The PATH edit runs once (a marker in the machine profile); the
migration test loads a v0.3 `.agent/` (the files of tag v0.3.0) and the result passes `ap validate`. Fakes only: nothing
edits the real PATH, the real registry or a real vendor CLI."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from autopilot import migrate, repairs
from autopilot.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "agent_v03"


def P(rc=0, out="", err=""):
    return SimpleNamespace(rc=rc, stdout=out, stderr=err, timed_out=False)


def v03_project(tmp_path) -> Path:
    root = tmp_path / "old"
    (root / ".agent").mkdir(parents=True)
    for f in FIXTURE.iterdir():
        shutil.copy(f, root / ".agent" / f.name)
    pj = root / ".agent" / "project.yaml"
    text = pj.read_text(encoding="utf-8").replace("name: my-project", "name: old", 1)
    pj.write_text(text.replace("  test: []", "  test: ['python -c pass']", 1), encoding="utf-8")  # one check, like a real project
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "README.md").write_text("old project\n")
    return root


def test_repair_1_project_git_settings_are_applied_and_logged(tmp_path):
    ran = []

    def run(cmd, **kw):
        ran.append(cmd)
        if "status" in cmd:
            return P(128, "", "fatal: detected dubious ownership in repository at 'x'")
        return P(0, "git version 2.43.0")
    (tmp_path / ".git").mkdir()
    lines = repairs.project_git(tmp_path, run=run, platform="linux")
    assert len(lines) == 1 and lines[0].startswith("fixed:") and "dubious ownership" in lines[0]
    assert ["git", "config", "--global", "--add", "safe.directory", str(tmp_path)] in ran


def test_repair_2_the_path_edit_runs_once_through_a_marker_in_the_profile(tmp_path):
    ran = []
    first = repairs.persist_path(tmp_path, "linux", run=lambda c, **k: ran.append(c) or P(), which=lambda n: "/bin/uv")
    assert first.startswith("fixed:") and "Open a new terminal once" in first and ran == [["/bin/uv", "tool", "update-shell"]]
    assert json.loads((Path(os.environ["AUTOPILOT_HOME"]) / "machine.json").read_text(encoding="utf-8"))["path_persisted"] is True
    assert repairs.persist_path(tmp_path, "linux", run=lambda c, **k: ran.append(c) or P(), which=lambda n: "/bin/uv") == ""
    assert len(ran) == 1  # the second run does nothing and prints nothing


def test_repair_2_on_windows_edits_the_user_path_only_and_without_uv(tmp_path):
    added = []
    line = repairs.persist_path(tmp_path, "win32", add_windows=added.append)
    assert line.startswith("fixed:") and "user PATH" in line and added == [tmp_path / ".local" / "bin"]
    src = Path(repairs.__file__).read_text(encoding="utf-8") + (Path(repairs.__file__).parent / "doctor.py").read_text(encoding="utf-8")
    assert "HKEY_CURRENT_USER" in src and "HKEY_LOCAL_MACHINE, \"Environment\"" not in src  # never the machine PATH


def test_repair_2_a_failed_helper_says_skipped_and_is_tried_again_next_time(tmp_path):
    assert repairs.persist_path(tmp_path, "linux", run=lambda c, **k: P(1), which=lambda n: "/bin/uv").startswith("skipped:")
    assert repairs.persist_path(tmp_path, "linux", run=lambda c, **k: P(0), which=lambda n: None).startswith("skipped:")
    assert repairs.persist_path(tmp_path, "linux", run=lambda c, **k: P(0), which=lambda n: "/bin/uv").startswith("fixed:")


def test_repair_3_defender_is_one_printed_line_on_windows_and_never_an_elevated_string_from_python(tmp_path):
    line = repairs.defender(tmp_path, "win32")
    assert line.startswith("skipped:") and "Add-MpPreference -ExclusionPath" in line and str(tmp_path) in line
    assert repairs.defender(tmp_path, "linux") == ""
    src = Path(repairs.__file__).read_text(encoding="utf-8")
    assert "RunAs" not in src and "Start-Process" not in src and "run_proc(" not in src.split("def defender")[1].split("def duplicates")[0]


def test_repair_5_a_second_install_of_one_cli_names_both_and_the_removal_command(tmp_path):
    npm, native = "/home/u/.npm-global/bin/codex", "/usr/local/bin/codex"
    lines = repairs.duplicates(which_all=lambda n: [npm, native] if n == "codex" else [])
    assert len(lines) == 1
    assert npm in lines[0] and native in lines[0] and f"PATH picks {npm}" in lines[0]
    assert "npm uninstall -g @openai/codex" in lines[0]  # the first path is the npm one: its removal command is named
    lines = repairs.duplicates(which_all=lambda n: ["/usr/bin/claude", "/home/u/node_modules/.bin/claude"] if n == "claude" else [])
    assert "npm uninstall -g @anthropic-ai/claude-code" in lines[0]  # the removal command of the npm copy
    assert repairs.duplicates(which_all=lambda n: ["/usr/bin/codex"] if n == "codex" else []) == []

def test_repair_4_a_v03_agent_folder_is_backed_up_migrated_and_still_validates(tmp_path, capsys):
    root = v03_project(tmp_path)
    assert migrate.written_by(root) == "legacy" and migrate.pending(root)
    before = (root / ".agent" / "project.yaml").read_text(encoding="utf-8")
    assert main(["validate", "-C", str(root)]) == 0  # a v0.3 project (with its test command) loads on the new version
    capsys.readouterr()
    assert migrate.migrate(root, check=True)[0].endswith("brings it up to date (backup first)")  # --check changes nothing
    assert not (root / ".agent" / "backup-legacy").exists()
    lines = migrate.migrate(root)
    assert "moved from legacy to" in lines[0] and "backup in .agent/backup-legacy/" in lines[0]
    assert any("quality_baseline.json" in line for line in lines) and any(".gitignore" in line for line in lines)
    bk = root / ".agent" / "backup-legacy"
    assert (bk / "project.yaml").read_text(encoding="utf-8") == before and (bk / "plan.yaml").exists()  # the old shape is kept
    assert (root / ".agent" / "project.yaml").read_text(encoding="utf-8") == before  # the config itself is never rewritten
    assert ".agent/backup-*/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert main(["validate", "-C", str(root)]) == 0  # `ap validate` passes after the migration
    out = capsys.readouterr().out
    assert "plan    OK" in out and "ERROR" not in out
    assert migrate.migrate(root) == [] and not migrate.pending(root)  # a second run changes nothing


def test_repair_4_a_broken_step_is_skipped_and_a_failed_backup_changes_nothing(tmp_path, monkeypatch):
    root = v03_project(tmp_path)
    monkeypatch.setattr(migrate, "STEPS", (("boom", lambda r: 1 / 0),))
    lines = migrate.migrate(root)
    assert any("skipped boom (ZeroDivisionError)" in line for line in lines)  # the project never fails on a new version
    root2 = v03_project(tmp_path / "two")
    monkeypatch.setattr(migrate, "backup", lambda r, o: None)
    assert "nothing was changed" in migrate.migrate(root2)[0] and not (root2 / ".agent" / "schema").exists()


def test_ap_upgrade_prints_the_migration_line_for_the_project_of_this_folder(tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    from autopilot.upgrade import cmd_upgrade
    root = v03_project(tmp_path)
    monkeypatch.chdir(root)
    cmd_upgrade(Namespace(check=True, ref=None, daily=False), run=lambda *a, **k: P(0, ""), detect=lambda: "editable", root=root)
    assert "was written by legacy" in capsys.readouterr().out
    cmd_upgrade(Namespace(check=False, ref=None, daily=False), run=lambda *a, **k: P(0, ""), detect=lambda: "editable", root=root)
    assert "moved from legacy to" in capsys.readouterr().out and (root / ".agent" / "backup-legacy").is_dir()


def test_fix_all_runs_the_repairs_and_a_second_run_prints_none_of_them_as_not_done(tmp_path):
    run = lambda c, **k: P(0, "git version 2.43.0")
    first = repairs.fix_all(tmp_path, home=tmp_path, platform="linux", run=run)
    again = repairs.fix_all(tmp_path, home=tmp_path, platform="linux", run=run)
    assert not any(line.startswith("fixed: `uv tool") or "Open a new terminal" in line for line in again)
    assert len(again) <= len(first)