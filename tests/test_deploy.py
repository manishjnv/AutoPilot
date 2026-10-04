from types import SimpleNamespace

from autopilot import deploy as dp
from autopilot.commands import preflight as pf
from autopilot.orchestrator import Orchestrator
from autopilot.plan import Plan
from autopilot.gate import CmdResult
from autopilot.log_scrub import scrub_secrets


def test_scrub_secrets():
    out = scrub_secrets("tok cf_abc123def456 x", {"CLOUDFLARE_TOKEN": "cf_abc123def456", "EMPTY": ""})
    assert out == "tok ***REDACTED[CLOUDFLARE_TOKEN]*** x"


def test_deploy_failure_output_scrubbed(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_TOKEN", "cf_abc123def456")
    monkeypatch.setattr(dp, "run_commands", lambda *a, **k: [CmdResult("d", 1, "boom cf_abc123def456", 0.0)])
    data = {"deploy.prod.cmd": "d"}
    cfg = SimpleNamespace(root=tmp_path, get=lambda k, d=None: data.get(k, d))
    res = dp.deploy(cfg, "prod", "a" * 40, "P1", None)
    assert not res.ok and "cf_abc123def456" not in res.detail
    assert "***REDACTED[CLOUDFLARE_TOKEN]***" in res.detail


def test_deploy_failure_masks_host_and_configured_names(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOY_SSH_HOST", "deploy@vps.example.test")
    monkeypatch.setenv("CF_ZONE_ID", "zone_fake_0000000000000000")
    out = "ssh: connect to deploy@vps.example.test failed; zone zone_fake_0000000000000000 not found"
    monkeypatch.setattr(dp, "run_commands", lambda *a, **k: [CmdResult("d", 1, out, 0.0)])
    data = {"deploy.prod.cmd": "d", "deploy.secret_env": ["CF_ZONE_ID"]}
    cfg = SimpleNamespace(root=tmp_path, get=lambda k, d=None: data.get(k, d))
    res = dp.deploy(cfg, "prod", "a" * 40, "P1", None)
    assert "vps.example.test" not in res.detail and "zone_fake_" not in res.detail
    assert "***REDACTED[DEPLOY_SSH_HOST]***" in res.detail and "***REDACTED[CF_ZONE_ID]***" in res.detail


def _orch(sent, phases):
    plan = Plan.from_dict({"phases": phases})
    return SimpleNamespace(plan=plan, notify=SimpleNamespace(send=lambda kind, text: sent.append((kind, text))),
                           state=SimpleNamespace(set_phase=lambda pid, **kw: sent.append(("phase", pid, kw))))


INFRA = [{"id": "P01", "infra": {"steps": [{"id": "I1", "type": "cloudflare"}]}, "tasks": [{"id": "T1", "title": "x"}]}]


def test_prod_deploy_stops_before_any_change_when_a_token_expired(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_TOKEN", "cf_fake_0000000000000000")
    monkeypatch.setattr(pf, "http_get", lambda url, tok: 401)
    monkeypatch.setattr("autopilot.orchestrator.deploy", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    sent = []
    o = _orch(sent, INFRA)
    o.credentials_stop = lambda pid, env: Orchestrator.credentials_stop(o, pid, env)
    assert Orchestrator.deploy_prod(o, "P01", "a" * 40) == "prod deploy stopped: a credential check failed"
    assert ("phase", "P01", {"prod_status": "awaiting_approval", "prod_ref": "a" * 40}) in sent
    kind, text = sent[0]
    assert kind == "deploy_failed" and "CLOUDFLARE_TOKEN (I1)" in text and "cf_fake_" not in text


def test_credentials_stop_is_empty_for_a_phase_without_infra():
    sent = []
    o = _orch(sent, [{"id": "P01", "tasks": [{"id": "T1", "title": "x"}]}])
    assert Orchestrator.credentials_stop(o, "P01", "staging") == "" and sent == []
