"""Self-healing: outages of the machinery (CLI, login, network) are healed and retried, never counted as attempts."""
from autopilot.backends import SessionRequest, SessionResult, detect_infra
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic
from test_backend import stub_claude

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}}


class Outage(FakeBackend):
    """The first `n` sessions hit an infra failure of `kind`, then everything works."""

    def __init__(self, kind, n):
        super().__init__()
        self.kind, self.n = kind, n

    def run(self, req):
        if self.n:
            self.n -= 1
            return SessionResult(ok=False, error=f"{self.kind} trouble", infra=self.kind)
        return super().run(req)


def test_an_outage_is_retried_and_never_counts_as_an_attempt(tmp_path):
    sleeps = []
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], BASE), backend=Outage("network", 3),
                        sleep=sleeps.append)
    assert orch.run() == "plan complete"
    assert orch.state.task("P01-T01")["attempts"] == 1 and sleeps[:3] == [60, 300, 900]
    heals = [e["message"] for e in orch.state.events(100) if e["kind"] == "heal"]
    assert any("unreachable" in h for h in heals) and any("run again after 3" in h for h in heals)


def test_lost_login_tells_the_owner_how_to_fix_it(tmp_path):
    orch = Orchestrator(make_project(tmp_path, phases_basic()[:1], BASE), backend=Outage("auth", 1),
                        sleep=lambda s: None)
    assert orch.run() == "plan complete"
    assert any("/login" in e["message"] for e in orch.state.events(100) if e["kind"] == "heal")


def test_the_stop_file_ends_a_heal_wait(tmp_path):
    root = make_project(tmp_path, phases_basic()[:1], BASE)

    def sleep(_):
        (root / ".agent" / "STOP").write_text("stop")
    orch = Orchestrator(root, backend=Outage("network", 99), sleep=sleep)
    assert orch.run() == "stopped by .agent/STOP file"


def test_infra_is_read_from_the_cli_messages_only():
    assert detect_infra("Invalid API key · Please run /login") == "auth"
    assert detect_infra("API Error: Connection error.") == "network"
    assert detect_infra("request to https://api.anthropic.com failed, reason: getaddrinfo ENOTFOUND") == "network"
    assert detect_infra("API Error: 503 upstream unavailable") == "network"
    assert detect_infra("I added retry logic for ECONNRESET and an Invalid API key message") == ""  # prose
    assert detect_infra("tests failed") == ""


def test_a_cli_that_prints_nothing_is_an_infra_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, ""))  # seen: a broken npm install
    res = ClaudeCLIBackend(Config.load(tmp_path)).run(SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path)))
    assert not res.ok and res.infra == "cli" and res.error
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(tmp_path / "missing"))
    assert ClaudeCLIBackend(Config.load(tmp_path)).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path))).infra == "cli"
