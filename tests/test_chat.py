"""P5: owner commands from the private Telegram chat (status, answer, approve, unblock)."""
import json

from autopilot.notify import Notifier
from autopilot.config import Config
from autopilot.orchestrator import Orchestrator
from test_autopilot import FakeBackend, make_project, phases_basic

BASE = {"audit": {"completion_audit": False}, "decide": {"enabled": False}, "chat": {"enabled": True}}


class FakeTG:
    """Stands in for Notifier.telegram_commands: one batch of texts per poll (the first poll is the baseline)."""

    def __init__(self, *batches, on_wait=()):
        self.batches, self.polls, self.replies = [list(b) for b in batches], [], []
        self.on_wait = list(on_wait)  # delivered to the first long poll (timeout > 0), i.e. during a wait

    def __call__(self, offset, timeout=0):
        self.polls.append((offset, timeout))
        if timeout and self.on_wait:
            texts, self.on_wait = self.on_wait, []
        else:
            texts = self.batches.pop(0) if self.batches else []
        return (offset or 0) + len(texts) + 1, texts


def orch_with(tmp_path, tg, phases=None, cfg=None):
    root = make_project(tmp_path, phases or phases_basic()[:1], {**BASE, **(cfg or {})})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=lambda s: None)
    orch.notify.telegram_commands = tg
    orch.notify.reply = tg.replies.append
    return orch


def test_first_poll_drops_old_messages_then_commands_work(tmp_path):
    tg = FakeTG(["approve P01"], ["status", "/help"])
    orch = orch_with(tmp_path, tg)
    orch.reload_plan()
    assert orch.chat() is False and tg.replies == []  # stale backlog from before the first run: ignored
    assert tg.polls[0][0] == -1  # offset -1: Telegram drops everything queued before the newest update
    assert orch.chat() is False and tg.polls[1][0] >= 0
    assert tg.replies[0].startswith("0/2 tasks done") and "Open decisions: none" in tg.replies[0]
    assert tg.replies[1].startswith("Commands: status")


def test_a_failing_command_is_answered_not_raised(tmp_path):
    tg = FakeTG([], ["status"])
    orch = orch_with(tmp_path, tg)
    orch.reload_plan()
    orch.command = lambda text: 1 / 0
    assert orch.chat() is False and orch.chat() is False
    assert tg.replies == ["That command failed (ZeroDivisionError); see the log."]


def test_answer_from_chat_unparks_the_task_during_the_wait(tmp_path):
    tg = FakeTG(on_wait=["answer d-001 use the sandbox key"])
    fake = FakeBackend({"P01-T01": ["blocked", "blocked", "blocked", "ok"]})
    root = make_project(tmp_path, phases_basic()[:1], {**BASE, "needs_you": {"wait": True, "poll_minutes": 1},
                                                       "unstick": {"enabled": False}})
    orch = Orchestrator(root, backend=fake, sleep=lambda s: None)
    orch.notify.telegram_commands, orch.notify.reply = tg, tg.replies.append
    assert orch.run() == "plan complete"
    assert "D-001 answered; applying it now." in tg.replies
    assert orch.state.decision("D-001")["status"] == "APPLIED"
    assert any(t > 0 for _, t in tg.polls)  # the wait long-polls the chat instead of sleeping


def test_approve_and_unblock_check_their_target(tmp_path):
    orch = orch_with(tmp_path, FakeTG())
    orch.reload_plan()
    assert orch.command("approve P01") == ("P01 is not awaiting prod approval.", False)
    assert orch.command("approve ../../etc") == ("../../etc is not awaiting prod approval.", False)
    orch.state.set_phase("P01", prod_status="awaiting_approval", prod_ref="abc")
    assert orch.command("/approve P01")[1] and (orch.ad / "approvals" / "P01").exists()
    assert orch.command("unblock P01-T01") == ("P01-T01 is not blocked.", False)
    orch.state.set_task("P01-T01", status="blocked", attempts=3)
    assert orch.command("unblock P01-T01")[1] and orch.state.task("P01-T01")["status"] == "pending"


def test_off_or_unconfigured_just_sleeps(tmp_path):
    slept = []
    root = make_project(tmp_path, phases_basic()[:1], {"chat": {"enabled": True}})
    orch = Orchestrator(root, backend=FakeBackend(), sleep=slept.append)
    orch._wait(90)  # no Telegram env vars: no poll, plain sleep
    assert len(slept) == 1 and 89 < slept[0] <= 90


def test_template_has_no_duplicate_keys():
    """A repeated top-level key (e.g. two `notify:` blocks) silently drops the first one's settings."""
    import collections

    import yaml

    from autopilot.config import TEMPLATES

    class Strict(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [k.value for k, _ in node.value]
        assert not [k for k, c in collections.Counter(keys).items() if c > 1], keys
        return yaml.SafeLoader.construct_mapping(loader, node, deep)
    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    yaml.load((TEMPLATES / "agent" / "project.yaml").read_text(encoding="utf-8"), Strict)  # noqa: S506


def test_only_the_owners_private_chat_is_obeyed(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TG_TOKEN", "t")
    monkeypatch.setenv("AUTOPILOT_TG_CHAT", "42")
    updates = {"ok": True, "result": [
        {"update_id": 5, "message": {"chat": {"id": 42, "type": "private"}, "text": "status"}},
        {"update_id": 6, "message": {"chat": {"id": 42, "type": "group"}, "text": "approve P01"}},
        {"update_id": 7, "message": {"chat": {"id": 99, "type": "private"}, "text": "approve P01"}}]}

    class Resp:
        def read(self, limit=-1):
            return json.dumps(updates).encode()[:limit if limit > 0 else None]
    seen = []
    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout: seen.append(url) or Resp())
    n = Notifier(Config.load(make_project(tmp_path, phases_basic()[:1])))
    assert n.telegram_commands(3, 20) == (8, ["status"])
    assert "offset=3" in seen[0] and "timeout=20" in seen[0]
