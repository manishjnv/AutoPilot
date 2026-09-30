"""Fire-and-forget notifications (Telegram, Slack, generic webhook, ntfy). Never raises."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("autodev")


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
        return os.environ.get(name, "") if name else ""

    def send(self, event: str, message: str):
        text = f"[AutoDev · {self.project}] {event}: {message}"
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
            _post(url, text.encode(), {"Title": f"AutoDev {event}"})
