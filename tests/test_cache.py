"""U7 cache hygiene: the shared project context rides in a byte-stable system prompt, not in every task prompt."""
from autopilot.backends import SessionRequest
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.backends.command import CommandBackend
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic

NO_AUDIT = {"audit": {"completion_audit": False}}


class Recorder(FakeBackend):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.reqs = []

    def run(self, req):
        self.reqs.append(req)
        return super().run(req)


def test_system_prompt_is_identical_across_sessions_and_holds_the_brain(tmp_path):
    root = make_project(tmp_path, phases_basic(), {"decide": {"enabled": False}})
    (root / ".agent" / "BRAIN.md").write_text("# Brain\nUse SQLite. BRAIN-MARKER-42\n", encoding="utf-8")
    fake = Recorder()
    Orchestrator(root, backend=fake, sleep=lambda s: None).run()
    kinds = {r.prompt.split("\n", 1)[0][:40] for r in fake.reqs}
    assert len(fake.reqs) >= 4 and len(kinds) >= 2  # several tasks plus the completion audit
    systems = {r.system_append for r in fake.reqs}
    assert len(systems) == 1  # byte-identical: one cache entry serves every session on the same model
    system = systems.pop()
    assert "BRAIN-MARKER-42" in system and "## Project goal\ndemo app" in system
    assert all("BRAIN-MARKER-42" not in r.prompt for r in fake.reqs)  # not repeated in every prompt


def test_cache_ttl_env_is_opt_in(tmp_path):
    cfg = Config.load(tmp_path)
    assert "CLAUDE_CODE_PROMPT_CACHE_TTL" not in ClaudeCLIBackend(cfg).env()
    cfg.data["agent"]["cache_ttl"] = "1h"
    assert ClaudeCLIBackend(cfg).env()["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "1h"


def test_command_backend_puts_the_system_text_first(tmp_path):
    cfg = Config.load(tmp_path)
    cfg.data["agent"]["command"] = 'python -c "import sys; print(sys.stdin.read())"'
    res = CommandBackend(cfg).run(SessionRequest(prompt="the task", model="m", cwd=str(tmp_path),
                                                 system_append="RULES and BRAIN"))
    assert res.ok and res.text.index("RULES and BRAIN") < res.text.index("the task")
