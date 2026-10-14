"""W59: the usage bars of a Claude login, read live from the OAuth usage endpoint (undocumented), cached per login,
with a kill switch. The token is read from the login's `.credentials.json`, sent only to api.anthropic.com and never
logged or returned."""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

URL = "https://api.anthropic.com/api/oauth/usage"
BETA = "oauth-2025-04-20"
CACHE_SEC = 60  # one call per login at most this often; the watch loop and the status page reuse the cached row
_cache: dict[str, tuple[float, dict]] = {}


def config_dir(folder: str = "") -> Path:
    """The Claude config folder of a login: `folder` (an `agent.env` CLAUDE_CONFIG_DIR), else the environment's, else
    `~/.claude`."""
    if folder and folder != "default":
        return Path(folder)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def read_token(folder: str = "") -> str:
    """The OAuth access token of the login in `folder`, or ''. Keep it out of every log and print."""
    try:
        creds = json.loads((config_dir(folder) / ".credentials.json").read_text(encoding="utf-8"))
        return str((creds.get("claudeAiOauth") or {}).get("accessToken") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _when(s) -> float:
    """An ISO time to unix seconds, 0 when it does not parse."""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _bar(percent, resets_at) -> dict | None:
    """{pct 0..1, reset unix seconds} from a percent 0..100 and an ISO time; None for anything odd (same trust rules as
    `claude_cli.window_info`)."""
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent):
        return None
    reset = _when(resets_at)
    if not 0 <= percent <= 100 or not 0 < reset < 4e9:
        return None
    return {"pct": float(percent) / 100, "reset": reset}


def parse(body) -> dict:
    """The bars from the endpoint answer (live shape probed 2026-10-14): `limits[]` rows of kind `session`,
    `weekly_all` and `weekly_scoped` (per model, named by `scope.model.display_name`), and `seven_day_breakdown.rows`
    per surface. Returns {five_hour: {pct, reset}, seven_day: {pct, reset}, models: {name: {pct, reset}}, surfaces:
    {key: pct}}; every key is optional and an odd value is dropped."""
    out: dict = {"models": {}, "surfaces": {}}
    if not isinstance(body, dict):
        return out
    for row in body.get("limits") or []:
        if not isinstance(row, dict):
            continue
        bar = _bar(row.get("percent"), row.get("resets_at"))
        if bar is None:
            continue
        kind = row.get("kind")
        if kind == "session":
            out["five_hour"] = bar
        elif kind == "weekly_all":
            out["seven_day"] = bar
        elif kind == "weekly_scoped":
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            if model.get("display_name"):
                out["models"][str(model["display_name"]).lower()] = bar
    for name in ("five_hour", "seven_day"):  # the flat objects, when the limits list says nothing
        flat = body.get(name)
        if name not in out and isinstance(flat, dict):
            bar = _bar(flat.get("utilization"), flat.get("resets_at"))
            if bar:
                out[name] = bar
    breakdown = body.get("seven_day_breakdown")
    for row in (breakdown.get("rows") if isinstance(breakdown, dict) else None) or []:
        pct = row.get("percent") if isinstance(row, dict) else None
        if row.get("key") and isinstance(pct, (int, float)) and not isinstance(pct, bool) and 0 <= pct <= 100:
            out["surfaces"][str(row["key"])] = float(pct) / 100
    return out


def _open(url, headers):
    import urllib.request  # W47: lazy

    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15)


def fetch(folder: str = "", *, cfg=None, urlopen=_open, now=time.time, cache=_cache) -> dict:
    """The live bars of one login (`parse` output plus `at`, the fetch time), at most one call per CACHE_SEC per login.
    {} when `usage.live` is false, the login has no token, the call fails or the shape is unknown: the caller then
    keeps the CLI stream figures and marks them `(cli)`. Never raises."""
    if cfg is not None and cfg.get("usage.live", True) is False:
        return {}
    key = str(config_dir(folder))
    hit = cache.get(key)
    if hit and now() - hit[0] < CACHE_SEC:
        return hit[1]
    token = read_token(folder)
    bars: dict = {}
    if token:
        try:
            with urlopen(URL, {"Authorization": "Bearer " + token, "anthropic-beta": BETA,
                               "User-Agent": "autopilot-usage"}) as r:
                bars = parse(json.loads(r.read(1 << 20).decode("utf-8")))
        except Exception:  # noqa: BLE001  any HTTP, network or JSON fault: the CLI figures stay the source
            bars = {}
        if bars.get("five_hour") or bars.get("seven_day"):
            bars["at"] = now()
        else:
            bars = {}
    cache[key] = (now(), bars)
    return bars
