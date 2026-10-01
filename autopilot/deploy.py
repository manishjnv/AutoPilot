"""Phase deployments with health checks, smoke tests and automatic rollback."""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass

from .gate import run_commands


@dataclass
class DeployResult:
    ok: bool
    detail: str
    rolled_back: bool = False


def health_check(url: str, timeout: int) -> bool:
    if not url:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                if 200 <= r.status < 400:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    return False


def deploy(cfg, env_name: str, ref: str, phase_id: str, prev_ref: str | None) -> DeployResult:
    c = f"deploy.{env_name}"
    env = {"AUTOPILOT_ENV": env_name, "AUTOPILOT_REF": ref, "AUTOPILOT_PHASE": phase_id,
           "AUTOPILOT_PREV_REF": prev_ref or "", "AUTOPILOT_URL": cfg.get(f"{c}.health_url", "")}
    env.update({"AUTODEV_" + k[10:]: v for k, v in list(env.items())})
    timeout = int(cfg.get("verify_timeout_sec", 1200))

    res = run_commands([cfg.get(f"{c}.cmd")], cfg.root, timeout, env)
    failure = None
    if res[-1].rc != 0:
        failure = f"deploy command failed:\n{res[-1].output[-1500:]}"
    elif not health_check(cfg.get(f"{c}.health_url", ""), int(cfg.get(f"{c}.health_timeout_sec", 180))):
        failure = f"health check failed: {cfg.get(f'{c}.health_url')}"
    else:
        smoke = run_commands(cfg.commands("smoke"), cfg.root, timeout, env)
        bad = [r for r in smoke if r.rc != 0]
        if bad:
            failure = f"smoke test failed: {bad[0].cmd}\n{bad[0].output[-1500:]}"
    if not failure:
        return DeployResult(True, f"{env_name} deployed {ref[:10]}")

    rolled = False
    rb = cfg.get(f"{c}.rollback_cmd")
    if rb and prev_ref:
        rb_res = run_commands([rb], cfg.root, timeout, env)
        rolled = rb_res[-1].rc == 0
        failure += f"\nrollback to {prev_ref[:10]}: {'ok' if rolled else 'FAILED'}"
    return DeployResult(False, failure, rolled_back=rolled)
