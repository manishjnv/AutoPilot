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
    (tmp_path / "install.sh").write_text("DEFAULT_REF=main\nMIN_VERSION=0.1.0\n")
    (tmp_path / "install.ps1").write_text("$DefaultRef = 'main'\n$MinVersion = '0.1.0'\n")
    for a in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"],
              ["add", "."], ["commit", "-qm", "base"]):
        git(tmp_path, *a)
    subprocess.run([sys.executable, str(BUMP), "0.2.0"], cwd=tmp_path, check=True)  # step 1: files + commit, no tag
    assert git(tmp_path, "tag").split() == []  # the tag waits for green CI (no origin here: a local tag on --tag)
    subprocess.run([sys.executable, str(BUMP), "0.2.0", "--tag"], cwd=tmp_path, check=True)  # step 2
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
    assert '"version": "0.2.0"' in (tmp_path / "plugin/.claude-plugin/plugin.json").read_text()
    assert '"0.2.0"' in (tmp_path / "autopilot/__init__.py").read_text()
    log = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [0.2.0] - " in log and log.index("[0.2.0]") < log.index("a fix")
    assert (tmp_path / "install.sh").read_text() == "DEFAULT_REF=main\nMIN_VERSION=0.2.0\n"  # T1: the ref stays main
    assert (tmp_path / "install.ps1").read_text() == "$DefaultRef = 'main'\n$MinVersion = '0.2.0'\n"
    assert git(tmp_path, "rev-list", "--count", "HEAD").strip() == "2"
    assert git(tmp_path, "tag").split() == ["v0.2.0"]


def test_ap_version_has_version_and_commit(capsys):
    main(["--version"])
    out = capsys.readouterr().out
    assert "(" in out and out.split("(")[1].rstrip(")\n")
    assert any(c.isdigit() for c in out)


def test_python_m_autopilot_version_says_autopilot_not_main(monkeypatch, capsys):
    """Q10 (found in the session-32 Windows dry run): `python -m autopilot --version` printed `__main__ 0.4.0`."""
    import sys

    from autopilot.cli import main
    monkeypatch.setattr(sys, "argv", ["C:\\x\\autopilot\\__main__.py", "--version"])
    assert main() == 0
    assert capsys.readouterr().out.startswith("autopilot ")
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/ap", "--version"])
    main()
    assert capsys.readouterr().out.startswith("ap ")


def test_install_scripts_carry_the_package_version_and_install_main():
    """T1: the script and the code move as one unit: MIN_VERSION equals the package version; a script on main installs main."""
    import re

    from autopilot import __version__
    root = Path(__file__).resolve().parents[1]
    sh = (root / "install.sh").read_text(encoding="utf-8")
    ps1 = (root / "install.ps1").read_text(encoding="utf-8")
    assert re.search(r"^MIN_VERSION=(\S+)$", sh, re.M).group(1) == __version__
    assert re.search(r"^\$MinVersion = '(\S+)'$", ps1, re.M).group(1) == __version__
    assert re.search(r"^DEFAULT_REF=main$", sh, re.M) and re.search(r"^\$DefaultRef = 'main'$", ps1, re.M)
    rel = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "DEFAULT_REF=$GITHUB_REF_NAME" in rel and rel.index("DEFAULT_REF=$GITHUB_REF_NAME") < rel.index("sha256sum install.ps1")
