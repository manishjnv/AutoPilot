"""`autopilot doctor`: environment checks before a run (read-only, no agent session)."""
import yaml

from autopilot.cli import main as cli_main
from autopilot.config import Config
from autopilot.doctor import FAIL, OK, WARN, checks
from test_backend import stub_claude


def project(tmp_path, extra=None):
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "python"]) == 0
    if extra:
        p = tmp_path / ".agent" / "project.yaml"
        p.write_text(p.read_text(encoding="utf-8") + "\n" + yaml.safe_dump(extra), encoding="utf-8")
    return Config.load(tmp_path)


def by_name(rows):
    return {name: (level, detail) for level, name, detail in rows}


def test_a_broken_claude_install_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('Bun 1.4.3')\n"))  # seen on this machine
    rows = by_name(checks(project(tmp_path)))
    assert rows["claude CLI"][0] == FAIL and "Bun 1.4.3" in rows["claude CLI"][1] and "claude login" not in rows
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", str(tmp_path / "missing-claude"))
    assert by_name(checks(Config.load(tmp_path)))["claude CLI"][0] == FAIL


def test_a_working_claude_passes_and_login_is_checked(tmp_path, monkeypatch):
    body = ("import sys\nif sys.argv[1:] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "else: sys.exit(1)  # auth status: not logged in\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body))
    rows = by_name(checks(project(tmp_path)))
    assert rows["claude CLI"][0] == OK and "2.1.286" in rows["claude CLI"][1]
    assert rows["claude login"][0] == FAIL and "claude auth login" in rows["claude login"][1] and rows["git"][0] == OK


NO_LOGIN = "import sys\nif sys.argv[1:] == ['--version']: print('%s (Claude Code)')\nelse: sys.exit(1)\n"


def test_a_missing_login_does_not_fail_an_old_cli_or_an_api_key_user(tmp_path, monkeypatch):
    """H2: only a login that is surely missing is a FAIL. An old CLI has no `auth status`; an API key needs no login."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)
    cfg = project(tmp_path)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, NO_LOGIN % "2.1.200"))
    level, detail = by_name(checks(cfg))["claude login"]
    assert level == WARN and "older than 2.1.268" in detail
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, NO_LOGIN % "2.1.286"))
    assert by_name(checks(cfg))["claude login"][0] == FAIL
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    level, detail = by_name(checks(cfg))["claude login"]
    assert level == WARN and "ANTHROPIC_API_KEY" in detail and "placeholder" not in detail  # the name, never the value
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    cfg = project(tmp_path / "api", {"usage": {"billing": "api"}})
    assert by_name(checks(cfg))["claude login"][0] == WARN


def test_a_free_plan_gets_its_own_message(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    body = ("if sys.argv[1:] == ['--version']: print('2.1.286 (Claude Code)')\n"
            "else: print(json.dumps({'loggedIn': True, 'authMethod': %r, 'subscriptionType': 'free'}))\n")
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body % "claude.ai"))
    cfg = project(tmp_path)
    level, detail = by_name(checks(cfg))["claude login"]
    assert level == FAIL and "free Claude plan" in detail
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, body % "apiKey"))  # not a plan login: no stop
    assert by_name(checks(cfg))["claude login"][0] == OK


def test_notifications_chat_and_config(tmp_path, monkeypatch):
    for k in ("AUTOPILOT_TG_TOKEN", "AUTOPILOT_TG_CHAT", "AUTOPILOT_SLACK_WEBHOOK", "AUTOPILOT_WEBHOOK",
              "AUTOPILOT_NTFY_TOPIC", "AUTODEV_TG_TOKEN", "AUTODEV_NTFY_TOPIC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('2.1.286 (Claude Code)')\n"))
    rows = by_name(checks(project(tmp_path, {"chat": {"enabled": True}, "git": {"mode": "pr"}})))
    assert rows["notifications"][0] == WARN and rows["telegram chat"][0] == FAIL
    assert rows["config"][0] == FAIL and "git.push" in rows["config"][1]  # PR mode without push is a blocking error
    monkeypatch.setenv("AUTOPILOT_NTFY_TOPIC", "my-topic")
    assert by_name(checks(Config.load(tmp_path)))["notifications"][0] == OK


def test_cli_exit_code(tmp_path, monkeypatch, capsys):
    assert cli_main(["doctor", "-C", str(tmp_path)]) == 1 and "autopilot init" in capsys.readouterr().out
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(tmp_path, "print('Bun 1.4.3')\n"))
    project(tmp_path)
    assert cli_main(["doctor", "-C", str(tmp_path)]) == 1 and "problem(s) to fix" in capsys.readouterr().out
