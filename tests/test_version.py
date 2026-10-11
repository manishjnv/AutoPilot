import subprocess
import sys
from pathlib import Path

from autopilot.cli import main

BUMP = Path(__file__).resolve().parent.parent / "scripts" / "bump.py"


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_bump_updates_files_commits_and_tags(tmp_path):
    (tmp_path / "plugin/.claude-plugin").mkdir(parents=True)
    (tmp_path / "autopilot").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (tmp_path / "plugin/.claude-plugin/plugin.json").write_text('{\n  "version": "0.1.0"\n}\n')
    (tmp_path / "autopilot/__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n- a fix\n")
    (tmp_path / "install.sh").write_text("DEFAULT_REF=main\n")
    (tmp_path / "install.ps1").write_text("$DefaultRef = 'main'\n")
    for a in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"],
              ["add", "."], ["commit", "-qm", "base"]):
        git(tmp_path, *a)
    subprocess.run([sys.executable, str(BUMP), "0.2.0"], cwd=tmp_path, check=True)
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
    assert '"version": "0.2.0"' in (tmp_path / "plugin/.claude-plugin/plugin.json").read_text()
    assert '"0.2.0"' in (tmp_path / "autopilot/__init__.py").read_text()
    log = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [0.2.0] - " in log and log.index("[0.2.0]") < log.index("a fix")
    assert (tmp_path / "install.sh").read_text() == "DEFAULT_REF=v0.2.0\n"
    assert (tmp_path / "install.ps1").read_text() == "$DefaultRef = 'v0.2.0'\n"
    assert git(tmp_path, "rev-list", "--count", "HEAD").strip() == "2"
    assert git(tmp_path, "tag").split() == ["v0.2.0"]


def test_ap_version_has_version_and_commit(capsys):
    main(["--version"])
    out = capsys.readouterr().out
    assert "(" in out and out.split("(")[1].rstrip(")\n")
    assert any(c.isdigit() for c in out)
