from autopilot.commands import preflight as pf
from autopilot.config import Config
from autopilot.plan import Plan, PlanError

import pytest

DATA = {"phases": [{"id": "P01", "infra": {"steps": [{"id": "I1", "type": "cloudflare"}]},
                    "tasks": [{"id": "T1", "title": "x"}, {"id": "T2", "title": "own it", "owner_only": True}]}]}


def _cfg():
    c = Config.__new__(Config)
    c.data = {"agent": {"env_passthrough": ["DATABASE_URL"]}}
    return c


def test_missing_token_blocks(monkeypatch):
    rows = pf.run_preflight(Plan.from_dict(DATA), _cfg(), env={})
    assert {r["status"] for r in rows} == {"missing"} and len(rows) == 3  # token, passthrough, owner task
    assert "NEEDS YOU: 3" in pf.report_text(rows)


def test_all_present_green(monkeypatch):
    monkeypatch.setattr(pf, "http_get", lambda url, tok: 200)
    d = {"phases": [{**DATA["phases"][0], "tasks": [{"id": "T1", "title": "x"}]}]}
    rows = pf.run_preflight(Plan.from_dict(d), _cfg(), env={"CLOUDFLARE_TOKEN": "t", "DATABASE_URL": "u"})
    assert all(r["status"] == "ok" for r in rows) and "preflight OK" in pf.report_text(rows)


def test_bad_token_is_error(monkeypatch):
    monkeypatch.setattr(pf, "http_get", lambda url, tok: 403)
    rows = pf.run_preflight(Plan.from_dict({"phases": [{"infra": DATA["phases"][0]["infra"], "tasks": []}]}),
                            _cfg(), env={"CLOUDFLARE_TOKEN": "t", "DATABASE_URL": "u"})
    assert [r["status"] for r in rows] == ["error", "ok"]


def _deploy_plan(**step):
    return Plan.from_dict({"phases": [{"id": "P01", "infra": {"steps": [{"id": "I1", "type": "deploy", **step}]},
                                       "tasks": []}]})


def test_ssh_precheck_runs_only_with_host(monkeypatch, tmp_path):
    key = tmp_path / "id_fake"
    key.write_text("not a key")
    calls = []
    monkeypatch.setattr(pf, "run_cmd", lambda cmd, shell=False: calls.append(cmd) or (0, ""))
    env = {"DEPLOY_SSH_KEY": str(key), "DATABASE_URL": "u"}
    rows = pf.run_preflight(_deploy_plan(), _cfg(), env=env)
    assert calls == [] and rows[0]["status"] == "ok" and "login not tested" in rows[0]["detail"]
    rows = pf.run_preflight(_deploy_plan(host="deploy@vps.example.test"), _cfg(), env=env)
    assert rows[0] == {"item": "DEPLOY_SSH_KEY (I1)", "status": "ok", "detail": "ssh login works"}
    (cmd,) = calls
    assert cmd[0] == "ssh" and cmd[-2:] == ["deploy@vps.example.test", "true"]  # read-only: log in, run `true`
    assert "BatchMode=yes" in cmd and "ConnectTimeout=10" in cmd  # no password prompt, a short timeout


def test_error_text_from_a_command_is_masked(monkeypatch, tmp_path):
    key = tmp_path / "id_fake"
    key.write_text("not a key")
    said = "deploy@vps.example.test: denied, token re_fake_000000000000000000000000"
    monkeypatch.setattr(pf, "run_cmd", lambda cmd, shell=False: (1, said))
    plan = Plan.from_dict({"phases": [{"id": "P01", "tasks": [], "infra": {"steps": [
        {"id": "I1", "type": "deploy", "host": "deploy@vps.example.test"},
        {"id": "I2", "type": "custom", "verify": "check", "env": ["MAIL_TOKEN"]}]}}]})
    rows = pf.run_preflight(plan, _cfg(), env={"DEPLOY_SSH_KEY": str(key), "DATABASE_URL": "u",
                                               "MAIL_TOKEN": "re_fake_000000000000000000000000"})
    text = pf.report_text(rows)
    assert [r["status"] for r in rows[:2]] == ["error", "error"]
    assert "re_fake_" not in text and "vps.example.test" not in text
    assert "***REDACTED[MAIL_TOKEN]***" in text and "***REDACTED[host:I1]***" in text


def test_host_that_is_an_ssh_option_rejected():
    for host in ("-oProxyCommand=touch x", "deploy@vps.example.test -v"):
        with pytest.raises(PlanError):
            _deploy_plan(host=host)


def test_recheck_names_the_credential_never_the_value(monkeypatch):
    phase = Plan.from_dict(DATA).phases[0]
    monkeypatch.setattr(pf, "http_get", lambda url, tok: 200)
    assert pf.recheck(phase, env={"CLOUDFLARE_TOKEN": "cf_fake_0000000000000000"}) == ""
    monkeypatch.setattr(pf, "http_get", lambda url, tok: 401)  # the token expired during the run
    why = pf.recheck(phase, env={"CLOUDFLARE_TOKEN": "cf_fake_0000000000000000"})
    assert why == "credential check failed before the deploy: CLOUDFLARE_TOKEN (I1) is error"
    assert "missing" in pf.recheck(phase, env={}) and "cf_fake_" not in why


def test_recheck_without_infra_steps_is_empty():
    assert pf.recheck(Plan.from_dict({"phases": [{"tasks": [{"id": "T1", "title": "x"}]}]}).phases[0], env={}) == ""


def test_infra_phase_gets_an_adr_and_is_critical():
    plan = Plan.from_dict({"phases": [DATA["phases"][0], {"id": "P02", "tasks": [{"id": "T3", "title": "y"}]}]})
    p1, p2 = plan.phases
    assert all(t.needs_decision for t in p1.tasks) and p1.max_risk == "critical"
    assert not p2.tasks[0].needs_decision and p2.max_risk == "medium"


def test_bad_infra_type_rejected():
    with pytest.raises(PlanError):
        Plan.from_dict({"phases": [{"infra": {"steps": [{"type": "ftp"}]}, "tasks": []}]})


def test_owner_task_skipped_by_loop():
    assert Plan.from_dict(DATA).next_ready({"T1": "done"}) is None
