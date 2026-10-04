"""Mock-HTTP checks for templates/{deploy.sh,cloudflare_apply.py,email_verify.py}."""
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

T = Path(__file__).parent.parent / "autopilot" / "templates"
Z = {"id": "z1"}


class H(BaseHTTPRequestHandler):
    dns, waf, calls, sent = [], [], [], []
    verified, postmark, fail_put = True, False, False

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
            if m == "PUT" and H.fail_put: return self._send(500, None)
            if m == "PUT": H.waf = body["rules"]
            return self._send(200, {"rules": H.waf})
        if H.postmark and p.startswith("/domains"):
            if self.headers.get("X-Postmark-Server-Token") != "pm_fake_0000": return self._send(401, None)
            if m == "GET" and p.startswith("/domains?"): return self._raw({"Domains": []})
            if m == "POST": return self._raw({"ID": 7})
            if p == "/domains/7": return self._raw({"ID": 7, "DKIMPendingHost": "pm._domainkey.example-test.dev",
                                                    "DKIMPendingTextValue": "k=rsa; p=fake", "DKIMHost": "", "DKIMTextValue": ""})
            if p == "/domains/7/verifyDkim": return self._raw({"DKIMVerified": H.verified})
        if H.postmark and p == "/email": H.sent.append(body); return self._raw({"MessageID": "m"})
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
    H.dns, H.waf, H.calls, H.sent, H.verified, H.postmark, H.fail_put = [], [], [], [], True, False, False
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
    r = run("cloudflare_apply.py", ["--rollback"], env, tmp_path)  # K: the drift is a hand edit: stop, show it
    assert r.returncode == 6 and "removed:" in r.stderr and "sekret" not in r.stdout + r.stderr
    assert run("cloudflare_apply.py", ["--rollback", "--force-restore"], env, tmp_path).returncode == 0


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


CF_ENV = {"CLOUDFLARE_TOKEN": "sekret"}


def test_cloudflare_rollback_without_hand_edits_restores(srv, tmp_path):
    env = {**CF_ENV, "CLOUDFLARE_API": srv}
    H.dns.append({"type": "A", "name": "old.example-test.dev", "content": "192.0.2.1", "id": "0"})
    f = str(T / "infra" / "cloudflare.yaml")
    assert run("cloudflare_apply.py", ["--file", f], env, tmp_path).returncode == 0
    assert "example-test.dev" in json.loads((tmp_path / "cf_snapshot.after.json").read_text())
    r = run("cloudflare_apply.py", ["--rollback"], env, tmp_path)  # no hand edit: the WAF rules go back to none
    assert r.returncode == 0 and "rollback example-test.dev: PUT_WAF" in r.stdout and H.waf == []


def test_cloudflare_rollback_after_a_failed_apply_needs_no_force(srv, tmp_path):
    H.fail_put = True  # the DNS records go in, then the WAF call fails
    env = {**CF_ENV, "CLOUDFLARE_API": srv}
    assert run("cloudflare_apply.py", ["--file", str(T / "infra" / "cloudflare.yaml")], env, tmp_path).returncode == 4
    assert run("cloudflare_apply.py", ["--rollback"], env, tmp_path).returncode == 0


def test_cloudflare_rollback_without_apply_record_stops(srv, tmp_path):
    (tmp_path / "cf_snapshot.json").write_text(json.dumps({"example-test.dev": {"dns": [], "waf": []}}))
    r = run("cloudflare_apply.py", ["--rollback"], {**CF_ENV, "CLOUDFLARE_API": srv}, tmp_path)
    assert r.returncode == 6 and "no record of the last apply" in r.stderr
    assert not [c for c in H.calls if c[0] != "GET"]


def test_cloudflare_rollback_checks_the_token_first(srv, tmp_path):
    (tmp_path / "cf_snapshot.json").write_text(json.dumps({"example-test.dev": {"dns": [], "waf": []}}))
    r = run("cloudflare_apply.py", ["--rollback", "--force-restore"], {"CLOUDFLARE_TOKEN": "bad", "CLOUDFLARE_API": srv}, tmp_path)
    assert r.returncode == 3 and H.calls == [("GET", "/user/tokens/verify")]


def test_email_postmark_mocked(srv, tmp_path):  # mocked HTTP only: no real Postmark account
    H.postmark = True
    env = {**email_env(srv), "EMAIL_PROVIDER": "postmark", "EMAIL_API_TOKEN": "pm_fake_0000"}
    r = run("email_verify.py", [], env, tmp_path)
    assert r.returncode == 0 and H.sent[0]["To"] == "o@x.dev" and "pm_fake_0000" not in r.stdout + r.stderr
    assert {"spf.mtasv.net" in d["content"] for d in H.dns if d["name"] == "example-test.dev"} == {True}
    assert any(d["name"] == "pm._domainkey.example-test.dev" for d in H.dns)


def test_email_postmark_not_verified(srv, tmp_path):
    H.postmark, H.verified = True, False
    env = {**email_env(srv), "EMAIL_PROVIDER": "postmark", "EMAIL_API_TOKEN": "pm_fake_0000"}
    r = run("email_verify.py", [], env, tmp_path)
    assert r.returncode == 5 and not H.sent


FAKE_BOTO3 = """import json, os
class NotFound(Exception): pass
class _C:
    class exceptions: NotFoundException = NotFound
    log = os.environ["FAKE_SES_LOG"]
    def _w(s, x): open(s.log, "a").write(json.dumps(x) + "\\n")
    def get_email_identity(s, EmailIdentity):
        if not os.path.exists(s.log + ".made"): raise NotFound()
        return {"DkimAttributes": {"Tokens": ["t1", "t2", "t3"]}, "VerifiedForSendingStatus": True}
    def create_email_identity(s, EmailIdentity):
        open(s.log + ".made", "w").close(); s._w(["create", EmailIdentity])
        return {"DkimAttributes": {"Tokens": ["t1", "t2", "t3"]}}
    def send_email(s, **k): s._w(["send", k["Destination"]["ToAddresses"]])
def client(name):
    assert name == "sesv2"
    return _C()
"""


def test_email_ses_with_fake_boto3(srv, tmp_path):  # a fake boto3 module: passes with or without real boto3
    (tmp_path / "fake").mkdir()
    (tmp_path / "fake" / "boto3.py").write_text(FAKE_BOTO3)
    log = tmp_path / "ses.log"
    env = {**email_env(srv), "EMAIL_PROVIDER": "ses", "EMAIL_API_TOKEN": "", "FAKE_SES_LOG": str(log),
           "PYTHONPATH": str(tmp_path / "fake")}
    r = run("email_verify.py", [], env, tmp_path)
    assert r.returncode == 0, r.stderr
    assert [json.loads(x) for x in log.read_text().splitlines()] == [["create", "example-test.dev"], ["send", ["o@x.dev"]]]
    assert sorted(d["name"] for d in H.dns if d["type"] == "CNAME") == [f"t{i}._domainkey.example-test.dev" for i in (1, 2, 3)]


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
