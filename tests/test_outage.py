"""Q22: four rules for a running build, on the fake runner and the real state.db of the orchestrator tests. No retry count
of an existing test changes: these runs use new fakes that fail in new ways."""
from test_autopilot import FakeBackend, make_project, phases_basic

from autopilot import outage
from autopilot.backends import SessionResult
from autopilot.orchestrator import Orchestrator

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "unstick": {"enabled": False}}


class Scripted(FakeBackend):
    """The first task sessions return the given results in order; then everything works."""

    def __init__(self, results):
        super().__init__()
        self.results, self.sent = list(results), 0

    def run(self, req):
        if "implement task" in req.prompt and self.results:
            self.sent += 1
            return self.results.pop(0)
        return super().run(req)


def make(tmp_path, backend, sleeps=None):
    root = make_project(tmp_path, phases_basic()[:1], BASE)
    return root, Orchestrator(root, backend=backend, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def err5xx(n=1):
    return [SessionResult(ok=False, error="API Error: 503 Service Unavailable", infra="network") for _ in range(n)]


def test_three_5xx_in_a_row_wait_fifteen_minutes_and_continue(tmp_path):
    sleeps = []
    fake = Scripted(err5xx(9))
    _root, orch = make(tmp_path, fake, sleeps)
    assert orch.run() == "plan complete"  # a blip does not end a night's work
    assert fake.sent == 9 and sleeps.count(900) >= 3  # every third answer: one 15-minute wait (the heal ladder adds its own)
    assert sleeps[:2] == [60, 300]  # the old heal waits only between the first answers
    assert orch.state.task("P01-T01")["attempts"] == 1  # no try was spent on the outage
    events = [e["message"] for e in orch.state.events(100)]
    assert not any("/login" in m or "not logged in" in m for m in events)  # no login prompt for an outage


def test_a_long_outage_ends_the_run_after_four_waits(tmp_path):
    sleeps = []
    fake = Scripted(err5xx(40))
    _root, orch = make(tmp_path, fake, sleeps)
    assert orch.run() == "The service is down, try again in 15 minutes."
    assert sleeps.count(900) >= 4 and fake.sent == 15  # 3 answers per wait, 4 waits, the 15th answer ends it
    assert orch.state.task("P01-T01")["attempts"] in (0, None)


def test_two_5xx_then_a_good_answer_keeps_the_old_heal(tmp_path):
    _root, orch = make(tmp_path, Scripted(err5xx(2)))
    assert orch.run() == "plan complete" and orch.state.task("P01-T01")["attempts"] == 1


def test_the_outage_counter_only_counts_fifteen_minutes():
    t = [0.0]
    tr = outage.Tracker(now=lambda: t[0])
    assert not tr.outage("API Error: 503") and not tr.outage("Request timed out")
    t[0] = 901
    assert not tr.outage("API Error: 502")  # the first two are older than the window
    t[0], x = 1000, tr.outage("API Error: 504")
    t[0] = 1100
    assert not x and tr.outage("API Error: 529")  # three inside the window
    assert not tr.outage("a test failed") and not tr.outage("line 502 of the log")  # not a vendor failure


def test_an_expired_login_parks_the_task_prints_the_login_command_and_resumes_after_a_fake_login(tmp_path, monkeypatch):
    from autopilot import doctor
    monkeypatch.setattr(doctor, "check_runner_login", lambda cfg, env=None: (doctor.FAIL, "claude", "claude auth login"))
    fake = Scripted([SessionResult(ok=False, error="OAuth token has expired", infra="auth")])
    root, orch = make(tmp_path, fake)
    out = orch.run()
    assert "Log in again with `claude auth login`" in out and "no try was lost" in out
    assert orch.state.task("P01-T01")["attempts"] in (0, None)  # no retry burned
    assert orch.state.get_meta("auth_paused") and any(e["kind"] == "auth" for e in orch.state.events(100))
    orch.state.close()  # the fake login is done: the next start clears the pause and finishes the same task
    orch2 = Orchestrator(root, backend=fake, sleep=lambda s: None)
    assert orch2.run() == "plan complete" and orch2.state.task("P01-T01")["attempts"] == 1
    assert not orch2.state.get_meta("auth_paused")


def test_a_transient_401_with_a_live_login_keeps_the_old_wait_and_retry(tmp_path, monkeypatch):
    from autopilot import doctor
    monkeypatch.setattr(doctor, "check_runner_login", lambda cfg, env=None: (doctor.OK, "claude", ""))
    _root, orch = make(tmp_path, Scripted([SessionResult(ok=False, error="OAuth token has expired", infra="auth")]))
    assert orch.run() == "plan complete" and not orch.state.get_meta("auth_paused")


def test_a_first_time_missing_login_keeps_the_old_wait_and_retry(tmp_path):
    _root, orch = make(tmp_path, Scripted([SessionResult(ok=False, error="Please run /login", infra="auth")]))
    assert orch.run() == "plan complete"
    assert any("/login" in e["message"] for e in orch.state.events(100) if e["kind"] == "heal")

def test_a_model_that_is_not_available_gets_one_sentence_with_the_alias_that_works():
    s = outage.model_sentence("claude-opus-9")
    assert s.endswith(".") and s.count(". ") == 0 and "claude-opus-9" in s and "alias sonnet" in s
    assert "alias haiku" in outage.model_sentence("sonnet") and outage.is_model_problem("model_not_found: xyz")
    assert not outage.is_model_problem("the tests failed")


def test_a_model_error_in_a_task_session_names_the_alias_in_the_notice(tmp_path):
    _root, orch = make(tmp_path, Scripted([SessionResult(ok=False, error="model_not_found: the model xyz does not exist")]))
    orch.run()
    heals = [e["message"] for e in orch.state.events(100) if e["kind"] == "heal"]
    assert any("is not available on this plan or in this region" in h and "alias" in h for h in heals)


def test_the_same_parsed_error_from_three_tasks_stops_the_run_with_the_checklist(tmp_path):
    phases = phases_basic()[:1]
    phases[0]["tasks"] = [{"id": f"P01-T0{i}", "title": f"t{i}"} for i in (1, 2, 3, 4)]
    root = make_project(tmp_path, phases, {**BASE, "retries": {"max_attempts_per_task": 1}})
    fake = Scripted([SessionResult(ok=False, error="connect ECONNREFUSED 10.0.0.1:443") for _ in range(4)])
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    out = orch.run()
    assert "The same error stopped three tasks" in out and "Next:" in out and "Done:" in out and "Not done:" in out
    assert fake.sent == 3  # the fourth task never starts: the window is not spent
    fatal = [e["message"] for e in orch.state.events(100) if e["kind"] == "fatal"]
    assert fatal and "The same error stopped three tasks" in fatal[0]


def test_two_tasks_with_the_same_error_do_not_stop_the_run():
    tr = outage.Tracker()
    assert tr.repeat("T1", "connect ECONNREFUSED") == "" and tr.repeat("T2", "connect ECONNREFUSED") == ""
    assert tr.repeat("T2", "connect ECONNREFUSED") == ""  # the same task twice is still two tasks
    assert tr.repeat("T3", "connect ECONNREFUSED") == "blocked-host"
    assert tr.repeat("T4", "some text no line knows") == ""