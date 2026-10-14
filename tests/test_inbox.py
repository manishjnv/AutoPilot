"""W48a/b: the inbox, the local answers and the helper call. Fake backends only, never a live login."""
import json
import time

from test_autopilot import FakeBackend, make_project, phases_basic

from autopilot import inbox
from autopilot.backends import SessionResult
from autopilot.cli import main
from autopilot.orchestrator import Orchestrator


def setup(tmp_path):
    root = make_project(tmp_path, phases_basic())
    Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None).reload_plan()  # fills state.db
    (root / ".agent" / "run.json").write_text(json.dumps(
        {"status": "running", "state": "Code", "task": "P01-T01", "current": "task P01-T01 a", "model": "sonnet",
         "run_id": "r1", "started_at": "2026-10-14T10:00:00", "updated_at": "2026-10-14T10:05:00"}))
    return root


class Stream:
    """A fake helper backend: three chunks, a pause between them."""
    def __init__(self, ok=True, gap=0.0):
        self.ok, self.gap, self.calls = ok, gap, 0

    def run(self, req):
        self.calls += 1
        assert req.read_only and req.no_tools and req.model == "haiku"
        if not self.ok:
            raise RuntimeError("down")
        for piece in ("It is ", "fine ", "now."):
            req.on_text(piece)
            time.sleep(self.gap)
        return SessionResult(ok=True, text="It is fine now.")


def finish(root, text, backend):
    rid, th = inbox.submit(root, text, backend)
    if th:
        th.join(10)
    return inbox.latest(root)


def test_hint_lands_in_state_and_reply_within_a_second(tmp_path):
    root = setup(tmp_path)
    t0 = time.monotonic()
    rid, th = inbox.submit(root, "hint P01-T01 use the cache")
    cur = inbox.latest(root)
    assert time.monotonic() - t0 < 1 and th is None
    assert cur["kind"] == "command" and cur["reply"].startswith("hint for P01-T01, next session")
    from autopilot.state import State
    assert State(root / ".agent" / "state.db").get_meta("hints:P01-T01")[0]["text"] == "use the cache"


def test_change_and_stop_reply_where_it_went(tmp_path):
    root = setup(tmp_path)
    assert finish(root, "change add a login page", None)["reply"] == "change: next replan, after P01"
    assert "before the next session" in finish(root, "stop", None)["reply"]
    assert (root / ".agent" / "STOP").exists()


def test_ap_question_prints_the_task_id(tmp_path, capsys):
    root = setup(tmp_path)
    assert inbox.cmd_line(root, "what runs now") == 0
    out = capsys.readouterr().out
    assert "P01-T01" in out and "[from run.json]" in out


def test_shell_fallback_sends_the_line_through_the_inbox(tmp_path, capsys, monkeypatch):
    root = setup(tmp_path)
    monkeypatch.chdir(root)
    assert main(["what", "runs", "now"]) == 0
    assert "P01-T01" in capsys.readouterr().out
    assert inbox.latest(root)["kind"] == "question"


def test_unknown_question_is_kind_question_and_streams(tmp_path):
    root = setup(tmp_path)
    cur = finish(root, "why is the sky blue", Stream())
    assert cur["kind"] == "question" and cur["reply"] == "It is fine now." and not cur["partial"]


def test_first_chunk_is_written_before_the_last(tmp_path):
    root = setup(tmp_path)
    rid, th = inbox.submit(root, "why is the sky blue", Stream(gap=0.4))
    seen = []
    while th.is_alive():
        cur = inbox.latest(root)
        if cur["reply"] and (not seen or seen[-1] != cur["reply"]):
            seen.append(cur["reply"])
        time.sleep(0.05)
    assert seen[0] != "It is fine now." and len(seen) >= 2
    rows = [json.loads(x) for x in (root / ".agent" / "inbox.jsonl").read_text().splitlines()]
    assert [r["partial"] for r in rows if "reply" in r] == [True, True, True, False]


def test_21st_question_gets_the_limit_text(tmp_path):
    root = setup(tmp_path)
    be = Stream()
    for i in range(20):
        assert finish(root, f"why number {i}", be)["reply"] == "It is fine now."
    cur = finish(root, "why number 21", be)
    assert cur["reply"].endswith("(helper limit)") and be.calls == 20


def test_failing_helper_gives_the_local_fallback(tmp_path):
    root = setup(tmp_path)
    t0 = time.monotonic()
    cur = finish(root, "why is the sky blue", Stream(ok=False))
    assert time.monotonic() - t0 < 1 and cur["reply"].startswith("Now:") and not cur["partial"]


def test_one_helper_call_at_a_time(tmp_path):
    root = setup(tmp_path)
    live, worst = [0], [0]

    class Slow(Stream):
        def run(self, req):
            live[0] += 1
            worst[0] = max(worst[0], live[0])
            time.sleep(0.2)
            live[0] -= 1
            return SessionResult(ok=True, text="ok")
    be = Slow()
    ths = [inbox.submit(root, q, be)[1] for q in ("why a", "why b")]
    for t in ths:
        t.join(10)
    assert worst[0] == 1


def test_existing_commands_and_help_are_unchanged(tmp_path, capsys):
    root = setup(tmp_path)
    main(["next", "-C", str(root)])
    assert "P01-T01" in capsys.readouterr().out
    try:
        main(["-h"])
    except SystemExit as e:
        assert e.code == 0
    assert "stop" in capsys.readouterr().out


def test_w53_shell_command_lands_in_the_inbox(tmp_path, capsys, monkeypatch):
    root = setup(tmp_path)
    monkeypatch.chdir(root)
    assert main(["hint", "P01-T01", "use the cache"]) == 0
    rows = [json.loads(x) for x in (root / ".agent" / "inbox.jsonl").read_text().splitlines()]
    asks = [r for r in rows if "text" in r]
    assert len(asks) == 1 and asks[0]["kind"] == "command" and asks[0]["text"].startswith("hint P01-T01")
    assert inbox.latest(root)["reply"]


def test_w53_slow_helper_falls_back_in_the_shell_and_lands_later(tmp_path, capsys):
    import threading
    root = setup(tmp_path)

    def slow(root_, rid, text, fb):  # stands in for the detached process
        def run():
            time.sleep(0.6)
            inbox._append(root_, {"id": rid, "reply": "the model answer", "partial": False})
        threading.Thread(target=run, daemon=True).start()

    assert inbox.cmd_line(root, "why is the sky blue", wait=0.2, spawn=slow) == 0
    assert "(the full answer lands in ap watch)" in capsys.readouterr().out
    time.sleep(1.0)
    assert inbox.latest(root)["reply"] == "the model answer"
