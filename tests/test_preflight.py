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


def test_bad_infra_type_rejected():
    with pytest.raises(PlanError):
        Plan.from_dict({"phases": [{"infra": {"steps": [{"type": "ftp"}]}, "tasks": []}]})


def test_owner_task_skipped_by_loop():
    assert Plan.from_dict(DATA).next_ready({"T1": "done"}) is None
