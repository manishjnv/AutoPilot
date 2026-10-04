"""`ap preflight`: phase 0 check. Every credential the plan needs is present and works (read-only calls), or
the run does not start. Missing items come out as ONE batch for the owner."""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request

from ..log_scrub import scrub_secrets

# type -> env var that must be set; the check is read-only
CRED = {"deploy": "DEPLOY_SSH_KEY", "cloudflare": "CLOUDFLARE_TOKEN", "email": "EMAIL_API_TOKEN"}
CF_VERIFY = "https://api.cloudflare.com/client/v4/user/tokens/verify"


def http_get(url: str, token: str) -> int:  # the one network call; tests replace it
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def run_cmd(cmd: list[str] | str, shell: bool = False) -> tuple[int, str]:  # tests replace it too
    try:
        p = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stderr or p.stdout).strip()[:200]
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)[:200]


def _check(step: dict, val: str, secrets: dict[str, str]) -> tuple[str, str]:
    """-> (ok|error, detail) for one present credential. Text from a command is scrubbed: it can hold a token or host."""
    st, detail = _probe(step, val)
    return st, scrub_secrets(detail, secrets) if st == "error" else detail


def _probe(step: dict, val: str) -> tuple[str, str]:
    t = step["type"]
    if t == "cloudflare":
        code = http_get(CF_VERIFY, val)
        return ("ok", "token valid") if code == 200 else ("error", f"Cloudflare answered HTTP {code}")
    if t == "deploy":
        if not os.path.isfile(val):
            return "error", "DEPLOY_SSH_KEY must be the path of a key file"
        if step["host"]:  # read-only: log in and run `true`
            rc, out = run_cmd(["ssh", "-i", val, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", step["host"], "true"])
            return ("ok", "ssh login works") if rc == 0 else ("error", f"ssh failed: {out}")
        return "ok", "key file found (no `host:` set, login not tested)"
    if step["verify"]:  # email / custom: the plan's own read-only verify command
        rc, out = run_cmd(step["verify"], shell=True)
        return ("ok", "verify command passed") if rc == 0 else ("error", f"verify failed: {out}")
    return "ok", "set (no verify command, not tested)"  # ponytail: email has no default provider endpoint


def run_preflight(plan, cfg, env=None) -> list[dict]:
    """Report rows {item, status: ok|missing|error, detail}. Any row that is not ok blocks the run."""
    env = os.environ if env is None else env
    rows, seen = [], set()
    steps = [s for ph in plan.phases for s in ph.infra.get("steps", [])]
    secrets = {n: env[n] for s in steps for n in [*CRED.values(), *s["env"]] if env.get(n)}
    secrets.update({f"host:{s['id']}": s["host"] for s in steps if s["host"]})
    for ph in plan.phases:
        for s in ph.infra.get("steps", []):
            for name in ([CRED[s["type"]]] if s["type"] in CRED else []) + s["env"]:
                if name not in env or not env[name]:
                    rows.append({"item": f"{name} ({s['id']})", "status": "missing",
                                 "detail": s["description"] or f"needed by {s['type']} step {s['id']}"})
                elif name == CRED.get(s["type"]) or s["verify"]:
                    st, d = _check(s, env[name], secrets)
                    rows.append({"item": f"{name} ({s['id']})", "status": st, "detail": d})
                seen.add(name)
    for name in cfg.get("agent.env_passthrough", []) or []:
        if name not in seen:
            rows.append({"item": name, "status": "ok" if env.get(name) else "missing",
                         "detail": "agent.env_passthrough" if env.get(name) else "listed in agent.env_passthrough"})
    for t in plan.all_tasks():
        if t.owner_only:
            rows.append({"item": f"{t.id} {t.title}", "status": "missing", "detail": "owner_only: you must do this task"})
    return rows


def report_text(rows: list[dict]) -> str:
    bad = [r for r in rows if r["status"] != "ok"]
    lines = [f"{r['status'].upper():8}{r['item']}  {r['detail']}" for r in rows]
    if bad:
        lines += ["", f"NEEDS YOU: {len(bad)} item(s) block the run. Fix them in one go, then run `ap preflight` again."]
    else:
        lines.append("preflight OK" if rows else "preflight OK (nothing to check)")
    return "\n".join(lines)


def approval_setup() -> list[str]:
    """Advice for manual setup to bypass interactive prompts. Does NOT modify global config (owner's standing rule).
    Returns a list of recommendations only (no automatic actions)."""
    actions = []

    # 1. SSH agent (info only)
    ssh_key = os.environ.get("DEPLOY_SSH_KEY")
    if ssh_key and os.path.isfile(ssh_key):
        rc, _ = run_cmd(["ssh-add", "-l"])
        if rc == 0:
            actions.append("SSH agent running; load key with: ssh-add " + ssh_key)
        else:
            actions.append("SSH agent not running; start with: eval $(ssh-agent -s)")

    # 2. GitHub gh CLI (info only)
    rc, _ = run_cmd(["gh", "auth", "status"])
    if rc != 0:
        actions.append("GitHub CLI not authenticated; run: gh auth login")

    # 3. Info for other setup (owner does manually)
    import platform
    if platform.system() == "Windows":
        actions.append("PowerShell: run as Administrator to avoid execution policy prompts")

    return actions
