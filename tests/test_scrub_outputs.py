"""X5 (M7, M8, L7): alerts, session transcripts and crash reports never carry a secret; a bare ntfy topic is warned."""
import json

from test_backend import stub_claude

from autopilot import notify, orchestrator
from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.cli import main as cli_main
from autopilot.config import Config

KEY = "sk-" + "a" * 24  # built from pieces: the secret scan refuses one literal


def project(tmp_path):
    assert cli_main(["init", "-C", str(tmp_path), "--stack", "python"]) == 0
    return tmp_path


def test_gate_error_text_does_not_reach_the_alert_body(tmp_path, monkeypatch):
    n = notify.Notifier(Config.load(project(tmp_path)))
    n.events.add("blocked")
    n.env = lambda k: "https://hook.example/x" if k == "webhook_env" else ""
    sent = []
    monkeypatch.setattr(notify, "_post", lambda url, data, headers: sent.append(data.decode()))
    n.send("blocked", f"gate failed: token {KEY} in output")
    assert sent and KEY not in sent[0] and "REDACTED" in sent[0]


def test_session_transcript_is_redacted_on_write(tmp_path, monkeypatch):
    log = tmp_path / "s.log"
    monkeypatch.setenv("AUTOPILOT_CLAUDE_BIN", stub_claude(
        tmp_path, "print(json.dumps({'type': 'user', 'message': {'content': 'out: " + KEY + "'}}))\n"
                  "print(json.dumps({'is_error': False, 'result': 'ok'}))\n"))
    ClaudeCLIBackend(Config.load(project(tmp_path))).run(
        SessionRequest(prompt="x", model="sonnet", cwd=str(tmp_path), log_path=str(log)))
    text = log.read_text(encoding="utf-8")
    assert KEY not in text and "REDACTED" in text
    for line in text.split("STDOUT:\n", 1)[1].splitlines():
        if line.startswith("{"):
            json.loads(line)  # still valid JSON


def test_crash_file_is_redacted(tmp_path):
    root = project(tmp_path)
    logs = root / ".agent" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "autopilot.log").write_text(f"deploy used {KEY}\n", encoding="utf-8")
    _, rel = orchestrator._crash_report(root, RuntimeError(f"boom {KEY}"), "T1")
    body = (root / rel).read_text(encoding="utf-8")
    assert KEY not in body and "REDACTED" in body


def test_validate_warns_on_a_bare_ntfy_topic(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    monkeypatch.setenv("AUTOPILOT_NTFY_TOPIC", "my-alerts")
    cli_main(["validate", "-C", str(root)])
    assert "ntfy topic my-alerts is public on ntfy.sh" in capsys.readouterr().out
    monkeypatch.setenv("AUTOPILOT_NTFY_TOPIC", "https://ntfy.example.org/mine")
    cli_main(["validate", "-C", str(root)])
    assert "is public on ntfy.sh" not in capsys.readouterr().out
