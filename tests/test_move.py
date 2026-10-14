"""Q15: a project in OneDrive, on a share or under /mnt gets one sentence and one command; `ap move` clones it with the
same HEAD, the same remotes and `.agent/`, and leaves the old folder with a MOVED.md note. Fixture repositories only."""
import subprocess
import sys
from pathlib import Path

import pytest

from autopilot import move as mv
from autopilot.cli import main, recent_projects


def git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.mark.parametrize("path,platform,kind", [
    (r"C:\Users\jo\OneDrive - Diageo\Documents\app", "win32", "onedrive"),
    ("/home/jo/OneDrive/app", "linux", "onedrive"),
    (r"\\fileserver\share\app", "win32", "unc"),
    ("/mnt/c/Users/jo/app", "linux", "mnt"),
    ("/home/jo/dev/app", "linux", ""),
    (r"C:\Users\jo\AppData\Local\dev\app", "win32", ""),
])
def test_bad_places_are_found(path, platform, kind):
    assert mv.location_kind(path, env={}, platform=platform, drive_type=lambda letter: 3) == kind


def test_a_redirected_documents_folder_and_a_mapped_drive_are_found():
    env = {"OneDrive": r"C:\Users\jo\Contoso Cloud"}  # Known Folder Move can use any folder name
    assert mv.location_kind(r"C:\Users\jo\Contoso Cloud\Documents\app", env=env, platform="win32", drive_type=lambda x: 3) == "onedrive"
    assert mv.location_kind(r"Z:\work\app", env={}, platform="win32", drive_type=lambda x: 4 if x == "Z" else 3) == "mapped"
    assert mv.location_kind(r"D:\work\app", env={}, platform="win32", drive_type=lambda x: 4 if x == "Z" else 3) == ""


def test_the_warning_is_one_sentence_and_the_command_with_the_default_target():
    lines = mv.warning(Path("/home/jo/OneDrive - Diageo/app"), env={}, platform="linux", home=Path("/home/jo"))
    assert len(lines) == 2 and lines[0].endswith(".") and lines[0].count(". ") == 0 and "sync locks" in lines[0]
    assert lines[1] == 'Move it with: ap move "/home/jo/dev/app"'
    win = mv.warning(Path(r"C:\Users\jo\OneDrive - Diageo\app"), env={"LOCALAPPDATA": r"C:\Users\jo\AppData\Local"}, platform="win32")
    assert win and "AppData" in win[1] and "dev" in win[1] and win[1].endswith('app"')
    assert mv.warning(Path("/home/jo/dev/app"), env={}, platform="linux") == []


def test_setup_and_doctor_project_print_the_warning_and_the_command(tmp_path, capsys):
    root = tmp_path / "OneDrive - Diageo" / "app"
    root.mkdir(parents=True)
    import autopilot.commands.setup as st
    said = []
    st.run_setup(root, dry_run=True, wanted="codex", say=said.append, env={"PATH": ""}, home=tmp_path, platform="linux")
    text = "\n".join(said)
    assert "OneDrive folder: sync locks" in text and "ap move" in text
    (root / ".agent").mkdir()
    (root / ".agent" / "project.yaml").write_text("name: app\n", encoding="utf-8")
    assert main(["doctor", "--project", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "not done  project place" in out and "ap move" in out

def make_repo(tmp_path):
    root = tmp_path / "OneDrive" / "app"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "a.txt").write_text("one\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "first")
    (root / ".agent").mkdir()
    (root / ".agent" / "project.yaml").write_text("name: app\nagent:\n  preset: codex\n", encoding="utf-8")
    (root / ".agent" / "plan.yaml").write_text("phases: []\n", encoding="utf-8")
    git(root, "remote", "add", "origin", "https://example.invalid/me/app.git")
    git(root, "remote", "add", "backup", "https://example.invalid/me/backup.git")
    return root


def test_move_clones_with_the_same_head_remotes_and_agent_folder(tmp_path):
    root = make_repo(tmp_path)
    target = tmp_path / "local" / "dev" / "app"
    said = []
    assert mv.move_project(root, target, say=said.append) == 0
    assert git(target, "rev-parse", "HEAD") == git(root, "rev-parse", "HEAD")
    remotes = {n: git(target, "remote", "get-url", n) for n in git(target, "remote").split()}
    assert remotes == {"origin": "https://example.invalid/me/app.git", "backup": "https://example.invalid/me/backup.git"}
    assert (target / ".agent" / "project.yaml").read_text(encoding="utf-8").startswith("name: app")
    assert (target / ".agent" / "plan.yaml").exists() and (target / "a.txt").read_text() == "one\n"
    assert (root / "a.txt").exists() and (root / ".agent" / "project.yaml").exists()  # the old folder is untouched
    assert str(target) in (root / "MOVED.md").read_text(encoding="utf-8") and "moved" in "\n".join(said)
    assert target in recent_projects()  # the new path is in the recent-projects list


def test_move_refuses_a_busy_target_a_non_repository_and_a_target_inside_the_project(tmp_path):
    root = make_repo(tmp_path)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x")
    said = []
    assert mv.move_project(root, busy, say=said.append) == 1 and "already holds files" in said[-1]
    assert mv.move_project(root, root / "inner", say=said.append) == 1 and "outside the old one" in said[-1]
    plain = tmp_path / "plain"
    plain.mkdir()
    assert mv.move_project(plain, tmp_path / "t", say=said.append) == 1 and "not a git repository" in said[-2]
    assert not (root / "MOVED.md").exists()  # a refused move writes nothing


def test_move_without_a_terminal_only_prints_the_command_and_yes_moves_at_once(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    target = tmp_path / "new" / "app"
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(["move", str(target), "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert f'ap move "{target}" --yes' in out and not target.exists()
    assert main(["move", str(target), "--yes", "-C", str(root)]) == 0
    assert (target / ".git").exists() and (root / "MOVED.md").exists()


def test_move_keeps_a_repository_with_no_remote_without_an_origin(tmp_path):
    root = tmp_path / "solo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "f").write_text("1")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "c")
    target = tmp_path / "solo2"
    assert mv.move_project(root, target, say=lambda s: None) == 0
    assert git(target, "remote") == ""