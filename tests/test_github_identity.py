"""Commits use the GitHub noreply identity for author AND committer (fake gh, no network)."""
import json
import subprocess
from types import SimpleNamespace

from autopilot import github_util
from autopilot.gitops import Git


def test_commit_uses_noreply_for_author_and_committer(tmp_path, monkeypatch):
    real_run, calls = subprocess.run, []

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["gh", "api"]:
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"login": "bob", "id": 42, "name": "Bob B"}))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(github_util, "_cache", None)
    monkeypatch.setattr(github_util.subprocess, "run", fake_run)
    g = Git(tmp_path)
    g.ensure_repo("main")
    (tmp_path / "f").write_text("x")
    g.commit_all("m")
    out = g.run("log", "-1", "--format=A:%an <%ae>%nC:%cn <%ce>")
    assert out == "A:Bob B <42+bob@users.noreply.github.com>\nC:Bob B <42+bob@users.noreply.github.com>"
    assert len(calls) == 1  # gh asked once, then cached
