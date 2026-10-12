"""J13 rows 3 to 8: project rows, Risk and Tries, rate, file lines, issue reasons, step times."""
import os
import subprocess
import time

from autopilot.dash_term import frame
from autopilot.dash_web import render
from autopilot.dashboard import by_commit, dashboard_data, live_rows
from test_dashboard import built
from test_dashboard_time import at, finish, many, session


def test_project_rows_risk_tries_rate_retries_and_reasons(tmp_path):
    orch = many(tmp_path, 3)
    session(orch, "task", "T01", 0, 10)
    finish(orch, "T01", 0, 10)
    session(orch, "task", "T02", 11, 20)
    finish(orch, "T02", 11, 22, tries=3)  # 11 min
    orch.state.set_task("T03", status="blocked", last_error="PROBLEM: the checks fail. More text.", updated_at=at(30))
    hist = orch.cfg.root / ".agent" / "history" / "P01"
    hist.mkdir(parents=True)
    (hist / "T02.md").write_text("# T02\n\n## Gate warnings\n- outside files_in_scope: cli.py\n", encoding="utf-8")
    orch.state.set_meta("window_seen", {"five_hour": {"pct": 0.2, "reset": time.time() + 3600}})
    d = dashboard_data(orch.cfg, orch.plan, orch.state, {"status": "finished", "started_at": at(0), "updated_at": at(40)})
    p = d["project"]
    assert p["runner"] == "claude" and p["login"] == "not checked" and len(p["resets"]) == 5 and p["resets"] != "—"
    assert p["last_error"] == "the checks fail."
    assert [(t["risk"], t["tries"]) for t in d["tasks"]] == [("low", 1), ("low", 3), ("low", 0)]
    assert d["usage"]["rate"] == "10 min per task"  # (10 + 11) / 2 = 10.5 -> 10 (round half to even)
    assert d["progress"]["retries"] == 2
    assert d["progress"]["warned_why"] == [{"id": "T02", "why": "out of scope: cli.py"}]
    text = "\n".join(frame(d, 120, 30))
    assert "Risk" in text and "Tries" in text and "Rate" in text and "T02 out of scope: cli.py" in text
    assert "Retries" in text and "Runner" in text
    page = render(d)
    assert "<th scope=col>Risk</th>" in page and "10 min per task" in page and "out of scope: cli.py" in page


def test_no_source_shows_a_dash(tmp_path):
    orch = built(tmp_path)
    d = dashboard_data(orch.cfg, orch.plan, orch.state, {})
    assert d["project"]["resets"] == "—" and d["project"]["last_error"] == "—"
    assert "Resets   : —" in "\n".join(frame(d, 120, 30))


def test_run_lines_match_git_diff_stat(tmp_path):
    def git(*a, **env):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True,
                              env={**os.environ, **env}).stdout
    git("init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    old = {"GIT_AUTHOR_DATE": "2020-01-01T00:00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    git("add", "."), git("commit", "-q", "-m", "a", **old)
    base = git("rev-parse", "HEAD").strip()
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "test_a.py").write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n")
    git("add", "."), git("commit", "-q", "-m", "b", **{**old, "GIT_AUTHOR_DATE": "2021-06-01T00:00:00",
                                                       "GIT_COMMITTER_DATE": "2021-06-01T00:00:00"})
    f = by_commit(tmp_path, "main", "2021-01-01T00:00:00")["files"]
    stat = git("diff", "--shortstat", base, "main")
    assert "5 insertions(+), 1 deletion(-)" in stat
    assert (f["plus"], f["minus"], f["tests"]) == (5, 1, 2)


def test_steps_get_their_time_and_a_long_wait_a_dim_line(tmp_path):
    orch = built(tmp_path)
    log = orch.cfg.root / ".agent" / "logs" / "autopilot.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-10-03 18:07:00 INFO   ▸ P01-T01 a [haiku] · Write /x/x.py · 0m10s\n"
                   "2026-10-03 18:07:40 INFO   ▸ P01-T01 a [haiku] · Bash pytest -q · 0m50s\n"
                   "2026-10-03 18:08:20 INFO   ▸ P01-T01 a [haiku] · Write /x/y.py · 1m30s\n", encoding="utf-8")
    old = time.time() - 120
    os.utime(log, (old, old))
    rows = live_rows(orch.cfg.root, orch.plan, live=True)
    steps = [r for r in rows if r["kind"] == "step"]
    # write + test is one group (10 s to 90 s on the session clock); the group still open has no length yet
    assert steps[0].get("took") == "1m20s" and steps[1].get("took") == "0m00s"
    assert rows[-1]["kind"] == "wait" and "2m" in rows[-1]["text"]
    assert not any(r["kind"] == "wait" for r in live_rows(orch.cfg.root, orch.plan))
    d = {"live": rows, "tasks": [], "asof": None}
    assert "1m20s" in "\n".join(frame(d, 120, 30))
