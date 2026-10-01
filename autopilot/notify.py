"""Fire-and-forget notifications (Telegram, Slack, generic webhook, ntfy). Never raises."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("autopilot")


def _post(url: str, data: bytes, headers: dict):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=15).read()


class Notifier:
    def __init__(self, cfg, state=None):
        self.cfg = cfg
        self.state = state
        self.project = cfg.get("name", cfg.root.name)
        self.events = set(cfg.get("notify.events", []) or [])

    def env(self, key: str) -> str:
        name = self.cfg.get(f"notify.{key}")
        if not name:
            return ""
        val = os.environ.get(name, "")
        if not val and name.startswith("AUTOPILOT_"):
            val = os.environ.get("AUTODEV_" + name[10:], "")
        return val

    def send(self, event: str, message: str):
        text = f"[Autopilot · {self.project}] {event}: {message}"
        log.info(text)
        if self.state is not None:
            self.state.event(event, message)
        if event not in self.events:
            return
        channels = {
            "telegram": self._telegram, "slack": self._slack, "webhook": self._webhook, "ntfy": self._ntfy,
        }
        for name, fn in channels.items():
            try:
                fn(event, text)
            except Exception as exc:  # noqa: BLE001 — notifications must never break the run
                log.warning("notify via %s failed: %s", name, exc)

    def reply(self, text: str):
        """A chat answer (P5): Telegram only, whatever `notify.events` says."""
        try:
            self._telegram("reply", f"[Autopilot · {self.project}] {text}")
        except Exception as exc:  # noqa: BLE001
            log.warning("chat reply failed: %s", type(exc).__name__)

    def telegram_commands(self, offset: int | None, timeout: int = 0) -> tuple[int | None, list[str]] | None:
        """P5: (next offset, texts) from the owner's private chat with the bot, long-polling up to `timeout` seconds.
        `offset` is the Bot API one: -1 = only the newest update (all older ones are dropped), 0/None = none sent.
        Messages from any other chat, or from a group, are dropped. None = Telegram is not configured.
        Raises on network errors; callers must never log the URL (it holds the bot token)."""
        token, chat = self.env("telegram_token_env"), self.env("telegram_chat_env")
        if not (token and chat):
            return None
        import urllib.parse
        q = {"timeout": int(timeout), "allowed_updates": '["message"]', **({"offset": offset} if offset else {})}
        url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(q)}"
        data = json.loads(urllib.request.urlopen(url, timeout=int(timeout) + 15).read(2_000_000))  # 100 updates fit
        texts, nxt = [], offset
        for u in data.get("result") or []:
            nxt = max(nxt or 0, int(u["update_id"]) + 1)
            m = u.get("message") or {}
            c = m.get("chat") or {}
            if str(c.get("id")) == str(chat) and c.get("type") == "private" and isinstance(m.get("text"), str):
                texts.append(m["text"])
        return nxt, texts

    def _telegram(self, event, text):
        token, chat = self.env("telegram_token_env"), self.env("telegram_chat_env")
        if token and chat:
            body = json.dumps({"chat_id": chat, "text": text[:4000]}).encode()
            _post(f"https://api.telegram.org/bot{token}/sendMessage", body, {"Content-Type": "application/json"})

    def _slack(self, event, text):
        url = self.env("slack_webhook_env")
        if url:
            _post(url, json.dumps({"text": text[:3000]}).encode(), {"Content-Type": "application/json"})

    def _webhook(self, event, text):
        url = self.env("webhook_env")
        if url:
            body = json.dumps({"project": self.project, "event": event, "message": text}).encode()
            _post(url, body, {"Content-Type": "application/json"})

    def _ntfy(self, event, text):
        topic = self.env("ntfy_topic_env")
        if topic:
            url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
            _post(url, text.encode(), {"Title": f"Autopilot {event}"})
