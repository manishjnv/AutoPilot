from types import SimpleNamespace

from autopilot import deploy as dp
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
