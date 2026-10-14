"""X7: timeouts, log rotation, tail reads, cached status page."""
import logging.handlers
import subprocess
import threading
import time
import urllib.request

import pytest

from autopilot import report
from autopilot.gitops import Git, GitError
from autopilot.proc import tail_lines
from test_autopilot import make_project, phases_basic


def test_git_has_a_timeout_and_never_prompts(monkeypatch, tmp_path):
    seen = {}

    def fake(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(GitError, match="fetch origin timed out"):
        Git(tmp_path).run("fetch", "origin")
    assert seen["timeout"] == 300
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["env"]["GIT_ASKPASS"] == "echo"


def test_the_log_handler_rotates(tmp_path):
    from autopilot.cli import setup_logging
    root = logging.getLogger()
    old = root.handlers[:]
    root.handlers[:] = []  # basicConfig does nothing when handlers exist
    try:
        setup_logging(tmp_path, False)
        h = [x for x in root.handlers if isinstance(x, logging.handlers.RotatingFileHandler)]
        assert h and h[0].maxBytes == 10 * 1024 * 1024 and h[0].backupCount == 3
    finally:
        for x in root.handlers[:]:
            if x not in old:
                x.close()
        root.handlers[:] = old


def test_tail_of_a_huge_log_is_fast(tmp_path):
    f = tmp_path / "autopilot.log"
    with open(f, "wb") as fh:
        fh.seek(50 * 1024 * 1024)
        fh.write(b"\nline a\nNEEDLE\n")
    t = time.perf_counter()
    rows = tail_lines(f, 40)
    assert rows[-1] == "NEEDLE" and time.perf_counter() - t < 0.2
    assert tail_lines(tmp_path / "missing", 5) == []


def test_two_gets_with_unchanged_inputs_render_once(tmp_path, monkeypatch):
    root = make_project(tmp_path, phases_basic())
    calls = []
    real = report.build_report
    monkeypatch.setattr(report, "build_report", lambda *a: calls.append(1) or real(*a))
    srv = report.status_server(root, "127.0.0.1", 0)
    from http.server import ThreadingHTTPServer
    assert isinstance(srv, ThreadingHTTPServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/?token={srv.token}"
        bodies = [urllib.request.urlopen(url, timeout=10).read() for _ in range(2)]
    finally:
        srv.shutdown()
        srv.server_close()
    assert bodies[0] == bodies[1] and len(calls) == 1
