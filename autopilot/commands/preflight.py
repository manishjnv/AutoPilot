"""`ap preflight`: phase 0 check. Every credential the plan needs is present and works (read-only calls), or
the run does not start. Missing items come out as ONE batch for the owner."""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request

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


def _check(step: dict, val: str) -> tuple[str, str]:
    """-> (ok|error, detail) for one present credential."""
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
    for ph in plan.phases:
        for s in ph.infra.get("steps", []):
            for name in ([CRED[s["type"]]] if s["type"] in CRED else []) + s["env"]:
                if name not in env or not env[name]:
                    rows.append({"item": f"{name} ({s['id']})", "status": "missing",
                                 "detail": s["description"] or f"needed by {s['type']} step {s['id']}"})
                elif name == CRED.get(s["type"]) or s["verify"]:
                    st, d = _check(s, env[name])
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
    """Bypass interactive prompts: PowerShell policy, git credential cache, SSH agent, npm flags, WSL sudo.
    Returns a list of setup actions taken."""
    actions = []

    # 1. PowerShell execution policy (Windows only)
    import platform
    if platform.system() == "Windows":
        rc, _ = run_cmd(["powershell", "-Command", "Set-ExecutionPolicy", "-ExecutionPolicy", "Bypass", "-Scope", "Process", "-Force"])
        if rc == 0:
            actions.append("PowerShell execution policy set to Bypass")

    # 2. Git credential cache (all platforms)
    rc, _ = run_cmd(["git", "config", "--global", "credential.helper", "cache"])
    if rc == 0:
        actions.append("Git credential cache enabled")

    # 3. SSH agent (all platforms)
    # Start ssh-agent if not running, and load DEPLOY_SSH_KEY if present
    ssh_key = os.environ.get("DEPLOY_SSH_KEY")
    if ssh_key and os.path.isfile(ssh_key):
        # Try ssh-add; if agent is not running, it will fail gracefully and we continue
        rc, _ = run_cmd(["ssh-add", ssh_key])
        if rc == 0:
            actions.append(f"SSH key {os.path.basename(ssh_key)} loaded into agent")
        else:
            # Agent may not be running; populate known_hosts as fallback
            if "host" in os.environ:
                host = os.environ.get("host", "").split("@")[-1].split(":")[ 0]
                rc, _ = run_cmd(["ssh-keyscan", "-t", "rsa,ed25519", host, ">>", os.path.expanduser("~/.ssh/known_hosts")], shell=True)
                if rc == 0:
                    actions.append(f"SSH known_hosts updated for {host}")

    # 4. WSL sudo NOPASSWD (Linux only, requires sudo)
    if platform.system() == "Linux" and os.path.exists("/etc/os-release"):
        # Check if running in WSL by reading /etc/os-release
        try:
            with open("/etc/os-release") as f:
                if "microsoft" in f.read().lower():
                    # WSL detected; try to add NOPASSWD for the current user
                    user = os.environ.get("USER", "autopilot")
                    rc, _ = run_cmd(["sudo", "-n", "bash", "-c", f"echo '{user} ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/{user}"])
                    if rc == 0:
                        actions.append(f"WSL sudo NOPASSWD configured for {user}")
        except (OSError, UnicodeDecodeError):
            pass  # Not WSL or permission denied

    # 5. npm flags (non-interactive, no audit/fund warnings)
    rc, _ = run_cmd(["npm", "config", "set", "audit", "false"])
    if rc == 0:
        run_cmd(["npm", "config", "set", "fund", "false"])
        actions.append("npm audit and fund warnings disabled")

    # 6. GitHub gh CLI (pre-authenticate if not already)
    rc, _ = run_cmd(["gh", "auth", "status"])
    if rc != 0:
        actions.append("Warning: GitHub CLI not authenticated; `gh` calls may prompt")

    return actions
