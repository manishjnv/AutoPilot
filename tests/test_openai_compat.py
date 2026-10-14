"""P12-T01 (W13): the openai_compat backend against a local 127.0.0.1 http.server (no real network)."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autopilot.backends import SessionRequest, get_backend
from autopilot.backends.openai_compat import FILE_FORMAT, OpenAICompatBackend
from autopilot.config import Config, deep_merge, defaults

REPORT = '```json\n{"status": "done", "summary": "wrote a.py"}\n```'


def answer(content, usage=None):
    data = {"id": "chatcmpl-example", "choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage:
        data["usage"] = usage
    return json.dumps(data)


@pytest.fixture
def server():
    state = {"status": 200, "body": answer("no files\n" + REPORT), "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            state["calls"].append({"path": self.path, "headers": dict(self.headers),
                                   "body": json.loads(self.rfile.read(n))})
            out = state["body"].encode("utf-8")
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["port"] = srv.server_address[1]
    yield state
    srv.shutdown()
    srv.server_close()


def cfg_for(tmp_path, port, **agent):
    a = {"backend": "openai_compat", "base_url": f"http://127.0.0.1:{port}/v1"}
    a.update(agent)
    return Config(tmp_path, deep_merge(defaults(), {"agent": a}))


def req(tmp_path, **kw):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return SessionRequest(prompt="build it", model=kw.pop("model", "sonnet"), cwd=str(work), timeout_sec=20, **kw)


def test_one_fenced_file_is_written_and_report_parses(tmp_path, server):
    server["body"] = answer("Here it is.\n```path: src/a.py\nprint('hi')\n```\n" + REPORT,
                            usage={"prompt_tokens": 12, "completion_tokens": 7})
    r = get_backend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert r.ok and r.infra == ""
    assert (tmp_path / "work" / "src" / "a.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert r.report == {"status": "done", "summary": "wrote a.py"}
    assert r.cost == 0.0 and r.usage["sonnet"]["input"] == 12 and r.usage["sonnet"]["output"] == 7


def test_json_block_inside_a_file_is_not_the_report(tmp_path, server):
    inner = '````path: docs/x.md\nexample:\n```json\n{"status": "blocked"}\n```\n````\n'
    server["body"] = answer(inner + REPORT)
    r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert r.ok and r.report["status"] == "done"
    assert '{"status": "blocked"}' in (tmp_path / "work" / "docs" / "x.md").read_text(encoding="utf-8")


def test_500_returns_infra_network(tmp_path, server):
    server["status"], server["body"] = 500, '{"error": "boom"}'
    r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert not r.ok and r.infra == "network" and "HTTP 500" in r.error


def test_4xx_is_a_plain_failure(tmp_path, server):
    server["status"], server["body"] = 404, '{"error": "model not found"}'
    r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert not r.ok and r.infra == "" and "HTTP 404" in r.error


def test_closed_port_is_infra_network(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    r = OpenAICompatBackend(cfg_for(tmp_path, port)).run(req(tmp_path))
    assert not r.ok and r.infra == "network" and "cannot reach" in r.error


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/evil.txt", "C:/evil.txt", "src/../../evil.txt", ".git/config"])
def test_path_outside_the_worktree_is_refused(tmp_path, server, bad):
    server["body"] = answer(f"```path: src/good.py\nx = 1\n```\n```path: {bad}\nbad\n```\n" + REPORT)
    r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert not r.ok and "refused file path outside the worktree" in r.error
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "work" / "src" / "good.py").exists()  # all or nothing


def test_request_has_mapped_model_and_file_format(tmp_path, server):
    cfg = cfg_for(tmp_path, server["port"], model_map={"sonnet": "qwen2.5-coder:7b"})
    OpenAICompatBackend(cfg).run(req(tmp_path, system_append="Project rules."))
    call = server["calls"][-1]
    assert call["path"] == "/v1/chat/completions"
    assert call["body"]["model"] == "qwen2.5-coder:7b" and call["body"]["stream"] is False
    system, user = call["body"]["messages"]
    assert system["role"] == "system" and system["content"].startswith("Project rules.")
    assert FILE_FORMAT in system["content"]
    assert user == {"role": "user", "content": "build it"}
    OpenAICompatBackend(cfg).run(req(tmp_path, model="opus"))
    assert server["calls"][-1]["body"]["model"] == "opus"  # not in the map: sent as is


def test_bearer_header_only_with_api_key_env(tmp_path, server, monkeypatch):
    monkeypatch.setenv("EXAMPLE_FAKE_KEY_ENV", "fake-token-example")
    OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert "Authorization" not in server["calls"][-1]["headers"]
    log = tmp_path / "s.log"
    cfg = cfg_for(tmp_path, server["port"], api_key_env="EXAMPLE_FAKE_KEY_ENV")
    r = OpenAICompatBackend(cfg).run(req(tmp_path, log_path=str(log)))
    assert server["calls"][-1]["headers"]["Authorization"] == "Bearer fake-token-example"
    assert "fake-token-example" not in log.read_text(encoding="utf-8") + r.text + r.error


def test_read_only_and_no_tools_write_no_file(tmp_path, server):
    server["body"] = answer("```path: a.txt\nhello\n```\n" + REPORT)
    for kw in ({"read_only": True}, {"no_tools": True}):
        r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path, **kw))
        assert r.ok and r.report["status"] == "done"
        assert not (tmp_path / "work" / "a.txt").exists()


def test_answer_that_is_not_a_chat_completion(tmp_path, server):
    server["body"] = '{"hello": 1}'
    r = OpenAICompatBackend(cfg_for(tmp_path, server["port"])).run(req(tmp_path))
    assert not r.ok and r.infra == "" and "not a chat completion" in r.error


def test_config_validation_accepts_openai_compat(tmp_path):
    errs = cfg_for(tmp_path, 1).validate()
    assert not [e for e in errs if "agent.backend" in e or "base_url" in e]
    errs = Config(tmp_path, deep_merge(defaults(), {"agent": {"backend": "nope"}})).validate()
    assert "agent.backend must be claude_cli, command or openai_compat, got 'nope'" in errs
    bad = cfg_for(tmp_path, 1, base_url="file:///etc/passwd").validate()
    assert "agent.base_url must start with http:// or https://" in bad
    r = OpenAICompatBackend(cfg_for(tmp_path, 1, base_url="file:///etc")).run(req(tmp_path))
    assert not r.ok and "http://" in r.error


# P12-T02: the doctor row of the endpoint (WARN only, never raises)
def test_endpoint_row_is_ok_with_the_local_server(tmp_path, server):
    from autopilot.doctor import check_endpoint
    assert check_endpoint(cfg_for(tmp_path, server["port"])) == \
        ("ok", "endpoint", f"http://127.0.0.1:{server['port']}/v1 answers")


def test_endpoint_row_is_warn_with_a_closed_port(tmp_path):
    from autopilot.doctor import WARN, check_endpoint
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    level, name, detail = check_endpoint(cfg_for(tmp_path, port), timeout=1)
    assert (level, name) == (WARN, "endpoint")
    assert detail == f"http://127.0.0.1:{port}/v1 does not answer (start Ollama or LM Studio)"


def test_endpoint_default_url_is_the_backend_constant(tmp_path, server, monkeypatch):
    from autopilot import doctor
    import autopilot.backends.openai_compat as backend
    monkeypatch.setattr(backend, "DEFAULT_BASE_URL", f"http://127.0.0.1:{server['port']}/v1")
    cfg = Config(tmp_path, deep_merge(defaults(), {"agent": {"backend": "openai_compat"}}))
    assert doctor.check_endpoint(cfg)[0] == "ok"  # no agent.base_url: the constant is read at call time


def test_runner_login_gives_the_endpoint_row(tmp_path, server):
    from autopilot.doctor import check_endpoint, check_runner_login
    cfg = cfg_for(tmp_path, server["port"])
    assert check_runner_login(cfg) == check_endpoint(cfg)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = cfg_for(tmp_path, port)
    assert check_runner_login(cfg) == check_endpoint(cfg, timeout=2)
    assert check_runner_login(cfg)[0] == "WARN"  # never FAIL: preflight does not stop a local-model run


def test_checks_has_the_endpoint_row_and_never_raises(tmp_path):
    from autopilot.doctor import WARN, checks
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (tmp_path / ".agent").mkdir()  # the runner row needs a chosen backend in project.yaml, as in a real project
    (tmp_path / ".agent" / "project.yaml").write_text(
        f"agent:\n  backend: openai_compat\n  base_url: http://127.0.0.1:{port}/v1\n", encoding="utf-8")
    rows = checks(cfg_for(tmp_path, port))
    assert (WARN, "endpoint", f"http://127.0.0.1:{port}/v1 does not answer (start Ollama or LM Studio)") in rows


def test_bearer_key_is_never_sent_over_plain_http_to_a_remote_host(tmp_path, monkeypatch):
    """M6: http:// to a non-loopback host with a key: refused with one sentence, no request."""
    monkeypatch.setenv("TEST_KEY_X8", "sk-test-not-real")
    c = Config(tmp_path, deep_merge(defaults(), {"agent": {"backend": "openai_compat", "api_key_env": "TEST_KEY_X8",
                                                          "base_url": "http://remote.example/v1"}}))
    r = OpenAICompatBackend(c).run(req(tmp_path))
    assert not r.ok and "http://" in r.error and "clear text" in r.error


def test_dot_git_check_ignores_case(tmp_path):
    from autopilot.backends.openai_compat import bad_path
    assert bad_path(".GIT/config", tmp_path.resolve()) and bad_path("a/.Git/hooks/x", tmp_path.resolve())
