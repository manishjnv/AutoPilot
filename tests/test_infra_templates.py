"""Mock-HTTP checks for templates/{deploy.sh,cloudflare_apply.py,email_verify.py}."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

T = Path(__file__).parent.parent / "autopilot" / "templates"
Z = {"id": "z1"}


class H(BaseHTTPRequestHandler):
    dns, waf, calls, sent = [], [], [], []
    verified = True

    def log_message(self, *a): pass

    def _send(self, code, res):
        b = json.dumps({"success": code < 400, "result": res, "errors": []}).encode()
        self.send_response(code); self.end_headers(); self.wfile.write(b)

    def _do(self, m):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        p = self.path
        H.calls.append((m, p))
        if "Bearer bad" in (self.headers.get("Authorization") or ""): return self._send(401, None)
        if p.startswith("/user/tokens/verify"): return self._send(200, {})
        if p.startswith("/zones?name"): return self._send(200, [Z])
        if "/dns_records" in p:
            if m == "POST": H.dns.append({**body, "id": str(len(H.dns))})
            elif m == "PATCH": H.dns[int(p.rsplit("/", 1)[1])].update(body)
            return self._send(200, H.dns)
        if "/rulesets/" in p:
            if m == "PUT": H.waf = body["rules"]
            return self._send(200, {"rules": H.waf})
        if p == "/domains" and m == "GET": return self._send(200, None) if False else self._raw({"data": []})
        if p == "/domains": return self._raw({"id": "d1", "records": [{"record": "DKIM", "type": "TXT", "name": "k._domainkey", "value": "pk"}]})
        if p.startswith("/domains/d1/verify"): return self._raw({})
        if p == "/domains/d1": return self._raw({"status": "verified" if H.verified else "pending"})
        if p == "/emails": H.sent.append(body); return self._raw({"id": "e"})
        self._send(404, None)

    def _raw(self, d):
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(d).encode())

    do_GET = lambda s: s._do("GET")
    do_POST = lambda s: s._do("POST")
    do_PUT = lambda s: s._do("PUT")
    do_PATCH = lambda s: s._do("PATCH")


@pytest.fixture
def srv():
    H.dns, H.waf, H.calls, H.sent, H.verified = [], [], [], [], True
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def run(script, args, env, cwd):
    e = {**os.environ, **env}
    return subprocess.run([sys.executable, str(T / script), *args], env=e, cwd=cwd, capture_output=True, text=True)


def test_cloudflare_dry_apply_idempotent_rollback(srv, tmp_path):
    env = {"CLOUDFLARE_TOKEN": "sekret", "CLOUDFLARE_API": srv}
    f = str(T / "infra" / "cloudflare.yaml")
    r = run("cloudflare_apply.py", ["--dry-run", "--file", f], env, tmp_path)
    assert r.returncode == 0 and "POST_DNS" in r.stdout and not H.dns
    r = run("cloudflare_apply.py", ["--file", f], env, tmp_path)
    assert r.returncode == 0 and len(H.dns) == 3 and all(x["action"] == "managed_challenge" for x in H.waf)
    assert "sekret" not in r.stdout + r.stderr
    n = len(H.calls)
    r = run("cloudflare_apply.py", ["--file", f], env, tmp_path)
    assert "no changes" in r.stdout and not [c for c in H.calls[n:] if c[0] != "GET"]
    H.dns.pop()  # drift, then rollback from snapshot (taken before 1st apply = empty) must not crash
    assert run("cloudflare_apply.py", ["--rollback"], env, tmp_path).returncode == 0


def test_cloudflare_bad_token(srv, tmp_path):
    r = run("cloudflare_apply.py", ["--dry-run"], {"CLOUDFLARE_TOKEN": "bad", "CLOUDFLARE_API": srv}, tmp_path)
    assert r.returncode == 3 and "ERROR" in r.stderr and "bad" not in r.stderr.replace("bad_", "").split("HTTP")[0]


def email_env(srv):
    return {"EMAIL_PROVIDER": "resend", "EMAIL_API_TOKEN": "tok123", "EMAIL_DOMAIN": "example-test.dev",
            "OWNER_EMAIL": "o@x.dev", "EMAIL_API_BASE": srv, "CLOUDFLARE_API": srv,
            "CLOUDFLARE_TOKEN": "cf", "EMAIL_POLL_TRIES": "2", "EMAIL_POLL_SECS": "0"}


def test_email_dry_and_apply(srv, tmp_path):
    r = run("email_verify.py", ["--dry-run"], email_env(srv), tmp_path)
    assert r.returncode == 0 and "DMARC1" in r.stdout and not H.calls
    r = run("email_verify.py", [], email_env(srv), tmp_path)
    assert r.returncode == 0 and H.sent and len(H.dns) == 3 and "tok123" not in r.stdout + r.stderr


def test_email_not_verified(srv, tmp_path):
    H.verified = False
    r = run("email_verify.py", [], email_env(srv), tmp_path)
    assert r.returncode == 5 and "Click" in r.stderr and not H.sent


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX bash; CI/WSL covers it")
def test_deploy(tmp_path):
    bash = "bash"
    fake = tmp_path / "fakessh"
    fake.write_text('#!/usr/bin/env bash\ncat >/dev/null\necho PREV_REF=old123\necho NEW_REF=new456\n')
    fake.chmod(0o755)
    env = {"DEPLOY_SSH_HOST": "h", "DEPLOY_SSH_KEY_PATH": "k", "DEPLOY_REF": "main",
           "DEPLOY_HEALTH_URL": "http://127.0.0.1:1/x", "DEPLOY_SSH_CMD": fake.as_posix()}
    e = {**os.environ, **env}
    run_ = lambda *a: subprocess.run([bash, (T / "deploy.sh").as_posix(), *a], env=e, cwd=tmp_path, capture_output=True, text=True)
    r = run_("--dry-run")
    assert r.returncode == 0 and "[dry-run]" in r.stdout and not (tmp_path / ".deploy_prev_ref").exists()
    r = run_()  # health URL is dead -> exit 4, previous ref logged + saved
    assert r.returncode == 4 and "old123" in r.stderr and (tmp_path / ".deploy_prev_ref").read_text().strip() == "old123"
    r = run_("--rollback", "--dry-run")
    assert r.returncode == 0 and "old123" in r.stdout
