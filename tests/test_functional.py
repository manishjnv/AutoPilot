"""L4: one functional check per phase; a failing journey becomes a [bug] fix task, then a NEEDS-YOU decision."""
import json
from pathlib import Path

from autopilot.backends import SessionRequest, SessionResult
from autopilot.backends.claude_cli import ClaudeCLIBackend
from autopilot.config import Config
from autopilot.gate import protected_files
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, git, make_project

NO_AUDIT = {"audit": {"completion_audit": False}}
FEATURES = [{"id": "P01-F01", "title": "Login", "journey": "POST /login returns a token"},
            "GET /items lists items"]  # a bare string is a journey; its id becomes P01-F02


def phases(features=FEATURES):
    return [{"id": "P01", "title": "One", "features": features,
             "tasks": [{"id": "P01-T01", "title": "a", "risk": "medium"}]}]


class Fixer(FakeBackend):
    """Fix tasks add a regression test; `heal` = whether a fix task makes the feature pass."""

    def __init__(self, failing=(), heal=True, **kw):
        super().__init__(**kw)
        self.failing_features, self.heal, self.reqs = set(failing), heal, []

    def run(self, req):
        self.reqs.append(req)
        res = super().run(req)
        if "implement task FIX" in req.prompt:
            (Path(req.cwd) / "tests").mkdir(exist_ok=True)
            (Path(req.cwd) / "tests" / "test_journey.py").write_text("def test_journey():\n    assert True\n")
            if self.heal:
                self.failing_features.clear()
        return res


def run(tmp_path, fake, plan=None, cfg=None):
    root = make_project(tmp_path, plan or phases(), {**NO_AUDIT, **(cfg or {})})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    return root, orch, orch.run()


def features_json(root):
    return {f["id"]: f for f in json.loads((root / ".agent" / "features.json").read_text(encoding="utf-8"))["features"]}


def test_passing_check_closes_the_phase_and_records_features(tmp_path):
    root, orch, outcome = run(tmp_path, Fixer())
    assert outcome == "plan complete" and [c[0] for c in orch.backend.calls] == ["P01-T01", "verify"]
    req = orch.backend.reqs[-1]
    assert req.read_only and not req.web_only and req.model == "sonnet" and "P01-F02` GET /items lists items" in req.prompt
    f = features_json(root)
    assert f["P01-F01"]["passes"] is True and f["P01-F02"]["passes"] is True and f["P01-F01"]["phase"] == "P01"
    assert orch.state.phase("P01")["status"] == "done"
    assert git(root, "status", "--porcelain").strip() == ""  # features.json committed with the phase close


def test_the_full_evidence_is_kept_as_proof_and_linked_from_the_phase(tmp_path):
    """G4: .agent/history/<phase>/PROOF.md has every feature's verdict, journey and full evidence; it is committed."""
    long_evidence = "$ curl -s localhost:8000/login\n" + "\n".join(f"line {i}" for i in range(60))
    fake_key = "AKIA" + "Z" * 16  # built at runtime so this file holds no key-shaped literal

    class Verbose(Fixer):
        def run(self, req):
            res = super().run(req)
            if req.prompt.startswith("# Assignment: functional check of phase"):
                for f in res.report["features"]:
                    f["evidence"] = f"AWS_KEY={fake_key}\n{long_evidence}\n```nested fence```"
            return res
    root, orch, outcome = run(tmp_path, Verbose())
    assert outcome == "plan complete"
    proof = (root / ".agent" / "history" / "P01" / "PROOF.md").read_text(encoding="utf-8")
    assert "## P01-F01 · PASS" in proof and "Journey: POST /login returns a token" in proof
    assert "line 59" in proof and len(features_json(root)["P01-F01"]["evidence"]) == 500  # proof is not cut
    assert fake_key not in proof and "(removed: it looked like a secret)" in proof
    assert fake_key not in (root / ".agent" / "features.json").read_text(encoding="utf-8")
    assert proof.count("```") == 4  # two fenced blocks; the nested fence was neutralised
    assert "[PROOF.md](PROOF.md)" in (root / ".agent" / "history" / "P01" / "PHASE.md").read_text(encoding="utf-8")
    assert ".agent/history/P01/PROOF.md" in git(root, "ls-files")


def test_redact_secrets_drops_a_whole_pem_block_and_keeps_ordinary_lines():
    from autopilot.docs import REDACTED, redact_secrets
    kind = "RSA " + "PRIVATE KEY"  # built at runtime so this file holds no key-shaped literal
    pem = f"-----BEGIN {kind}-----\nMIIEow" + "A" * 40 + "\nQ" * 3 + f"\n-----END {kind}-----"
    out = redact_secrets(f"$ cat key.pem\r\n{pem}\nHTTP 200 OK")
    assert out.splitlines() == ["$ cat key.pem", REDACTED, "HTTP 200 OK"]


def test_failing_feature_becomes_a_bug_fix_then_rechecks(tmp_path):
    root, orch, outcome = run(tmp_path, Fixer(failing={"P01-F01"}))
    assert outcome == "plan complete"
    assert [c[0] for c in orch.backend.calls] == ["P01-T01", "verify", "FIX001-T01", "verify"]
    fix = orch.plan.task_by_id["FIX001-T01"]
    assert fix.description.startswith("[bug]") and "POST /login returns a token" in fix.description
    assert "ran P01-F01" in fix.description  # the evidence travels with the bug
    assert features_json(root)["P01-F01"]["passes"] is True
    assert orch.state.phase("P01")["status"] == "done"


def test_still_failing_after_the_fix_asks_the_owner(tmp_path):
    root, orch, outcome = run(tmp_path, Fixer(failing={"P01-F02"}, heal=False))
    assert outcome.startswith("stalled: waiting on 1 decisions")
    assert orch.state.phase("P01")["status"] == "failed"
    d = orch.state.decision("D-001")
    assert d["kind"] == "phase" and "P01-F02" in d["question"]
    assert features_json(root)["P01-F02"]["passes"] is False
    assert [c[0] for c in orch.backend.calls].count("verify") == 2  # one check, one recheck, no more


def test_no_features_or_disabled_means_no_check(tmp_path):
    _, orch, _ = run(tmp_path, Fixer(), plan=phases(features=[]))
    assert "verify" not in [c[0] for c in orch.backend.calls]
    (tmp_path / "off").mkdir()
    _, orch, _ = run(tmp_path / "off", Fixer(), cfg={"functional": {"enabled": False}})
    assert "verify" not in [c[0] for c in orch.backend.calls]


def test_a_broken_check_never_holds_the_phase(tmp_path):
    class Broken(Fixer):
        def run(self, req):
            if req.prompt.startswith("# Assignment: functional check"):
                self.calls.append(("verify", req.model))
                return SessionResult(ok=False, error="crashed")
            return super().run(req)

    root, orch, outcome = run(tmp_path, Broken())
    assert outcome == "plan complete" and orch.state.phase("P01")["status"] == "done"


def test_mcp_config_flag_and_protected_features_file(tmp_path):
    cfg = Config.load(tmp_path)
    cmd = ClaudeCLIBackend(cfg).build_cmd(SessionRequest(prompt="x", model="sonnet", cwd=".", mcp_config=".agent/mcp.json"))
    i = cmd.index("--mcp-config")
    assert cmd[i + 1] == ".agent/mcp.json" and cmd[i + 2] == "--strict-mcp-config"
    assert "--mcp-config" not in ClaudeCLIBackend(cfg).build_cmd(SessionRequest(prompt="x", model="sonnet", cwd="."))
    assert ".agent/features.json" in protected_files(cfg)
