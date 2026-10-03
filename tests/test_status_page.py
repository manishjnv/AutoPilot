"""P5: `autopilot serve`, a read-only live status page built from plan.yaml + state.db on every request."""
import threading
import urllib.error
import urllib.request

import pytest

from autopilot.report import html_page, is_loopback, status_server
from test_autopilot import make_project, phases_basic


def get(srv, path="/"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), dict(e.headers)


@pytest.fixture
def serve(tmp_path):
    started, root = [], make_project(tmp_path, phases_basic())

    def start(**kw):
        srv = status_server(root, "127.0.0.1", 0, **kw)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return srv
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def test_page_shows_the_report_and_refreshes(serve):
    srv = serve(refresh=7)
    code, body, headers = get(srv)
    assert code == 200 and "text/html" in headers["Content-Type"] and headers["Cache-Control"] == "no-store"
    assert "Autopilot report" in body and "| P01 | One |" in body and "http-equiv=refresh content=7" in body
    assert get(srv, "/state.db")[0] == 404 and get(srv, "/.agent/plan.yaml")[0] == 404  # only the page


def test_token_is_required_when_set(serve):
    srv = serve(token="s3cret-token")
    assert get(srv)[0] == 403 and get(srv, "/?token=wrong")[0] == 403 and get(srv, "/?token=%C3%A9")[0] == 403
    assert get(srv, "/?token=s3cret-token")[0] == 200


def test_dns_rebinding_is_refused_without_a_token(serve):
    import http.client
    srv = serve()
    for host, code in (("evil.example:8765", 403), ("localhost:8765", 200), ("[::1]:8765", 200)):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/", headers={"Host": host})
        assert c.getresponse().status == code, host
        c.close()


def test_public_bind_without_token_is_refused(tmp_path):
    with pytest.raises(ValueError, match="AUTOPILOT_STATUS_TOKEN"):
        status_server(tmp_path, "0.0.0.0", 0)
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("example.com")


def test_page_starts_with_what_the_run_is_doing_now(serve, tmp_path):
    import json
    agent = tmp_path / "proj" / ".agent"
    (agent / "logs").mkdir(parents=True, exist_ok=True)
    (agent / "run.json").write_text(json.dumps({"status": "running", "current": "task P01-T01 attempt 1"}))
    (agent / "logs" / "autopilot.log").write_text(
        "2026-10-02 09:44:55 INFO   ▸ P01-T01 Skeleton [haiku] · Write src/app/cli.py · 2m02s\n", encoding="utf-8")
    body = get(serve())[1]
    assert body.index("Now (running)") < body.index("Autopilot report")
    assert "09:44  Writes cli.py." in body and "INFO" not in body and "09:44:55" not in body  # J7: plain words


def test_watch_shows_progress_then_follows_until_the_run_finishes(tmp_path, capsys):
    import json
    import threading
    import time

    from autopilot.cli import main as cli_main
    root = make_project(tmp_path, phases_basic())
    log = root / ".agent" / "logs" / "autopilot.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-10-02 09:00:00 INFO session #1 task P01-T01 model=haiku attempt=1\n", encoding="utf-8")
    (root / ".agent" / "run.json").write_text(json.dumps({"status": "running", "current": "task P01-T01"}))

    def finish():
        time.sleep(1.5)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("2026-10-02 09:01:00 INFO   ▸ P01-T01 · Write src/x.py · 0m30s\n")
        (root / ".agent" / "run.json").write_text(json.dumps({"status": "finished", "outcome": "plan complete"}))
    threading.Thread(target=finish).start()
    assert cli_main(["watch", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "0/3 tasks done" in out and "now: task P01-T01" in out and "session #1" in out
    assert "Write src/x.py" in out and "run finished: plan complete" in out
    assert out.rstrip().endswith("all commands")  # ends with the next-steps hint
    # G8: not a terminal, so the status line is printed when the run moves on, and never an escape code
    assert "Done │ Task 0/3 0% │ Ph 0/2 │ Blk 0" in out and "\x1b" not in out


def test_page_title_and_first_line_are_the_status_line(serve, tmp_path):
    import json
    agent = tmp_path / "proj" / ".agent"
    (agent / "run.json").write_text(json.dumps({"status": "running", "state": "Code", "task": "P01-T01",
                                                "attempt": 1, "max_attempts": 3, "git": "OK", "build": "OK"}))
    body = get(serve())[1]
    assert "<title>ON │ Code │ Task 0/3 0% │ Ph 0/2 │ Blk 0</title>" in body  # the tab shows it even in the background
    assert body.index("ON │ Code │ P01-T01 Try 1/3 │ Task 0/3 0%") < body.index("Now (running)")


def test_a_second_run_or_plain_autopilot_follows_the_active_run(tmp_path, monkeypatch, capsys):
    import json

    from autopilot.cli import main as cli_main
    from autopilot.cli import run_active
    from autopilot.proc import exclusive_lock
    root = make_project(tmp_path, phases_basic())
    (root / ".agent" / "run.json").write_text(json.dumps({"status": "finished", "outcome": "plan complete"}))
    assert not run_active(root)
    with exclusive_lock(root / ".agent" / "run.lock"):  # stands in for a run in another process
        assert run_active(root)
        assert cli_main(["run", "-C", str(root)]) == 0
        assert "already active" in capsys.readouterr().out
        monkeypatch.chdir(root)
        assert cli_main([]) == 0 and "following it" in capsys.readouterr().out
    assert cli_main([]) == 0 and "What you can do next" in capsys.readouterr().out  # no run: next steps


def test_a_headless_run_opens_a_watch_window(tmp_path, monkeypatch):
    import subprocess

    from autopilot import cli
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/xterm" if name == "xterm" else None)
    how = cli.open_watch_window(tmp_path)
    assert how and started
    cmd, kw = started[0]
    assert cmd[-4:] == ["autopilot", "watch", "-C", str(tmp_path)] or "watch" in " ".join(map(str, cmd))


def test_report_text_is_escaped():
    assert "<script>" not in html_page("<script>alert(1)</script>") and "&lt;script&gt;" in html_page("<script>")
