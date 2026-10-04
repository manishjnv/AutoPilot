#!/usr/bin/env python3
"""Verify an email sending domain: DNS records (via cloudflare_apply.py), provider check, test mail.

Usage: email_verify.py [--dry-run]
Env: EMAIL_PROVIDER (resend|postmark|ses), EMAIL_API_TOKEN, EMAIL_DOMAIN (must be a Cloudflare zone),
     OWNER_EMAIL, CLOUDFLARE_TOKEN; optional EMAIL_FROM, EMAIL_API_BASE (mocks), EMAIL_POLL_TRIES/EMAIL_POLL_SECS.
     ses uses AWS env credentials + boto3 (EMAIL_API_TOKEN unused).
Exit: 0 ok | 2 bad input | 3 Cloudflare step failed | 4 provider API error | 5 domain not verified yet
"""
import json, os, sys, tempfile, time, urllib.error, urllib.request
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TOKEN = os.environ.get("EMAIL_API_TOKEN", "")
PROVIDER = os.environ.get("EMAIL_PROVIDER", "")
DOMAIN = os.environ.get("EMAIL_DOMAIN", "")
OWNER = os.environ.get("OWNER_EMAIL", "")
BASE = {"resend": "https://api.resend.com", "postmark": "https://api.postmarkapp.com"}
BASE = os.environ.get("EMAIL_API_BASE") or BASE.get(PROVIDER, "")
SPF = {"resend": "include:amazonses.com", "postmark": "include:spf.mtasv.net", "ses": "include:amazonses.com"}


def out(msg, f=sys.stdout):
    print(str(msg).replace(TOKEN, "***") if TOKEN else msg, file=f)


class Fail(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def http(method, path, body=None):
    hdr = {"Content-Type": "application/json", "Accept": "application/json"}
    if PROVIDER == "resend":
        hdr["Authorization"] = f"Bearer {TOKEN}"
    else:  # postmark: one token passed as both account and server token
        hdr["X-Postmark-Account-Token"] = hdr["X-Postmark-Server-Token"] = TOKEN
    req = urllib.request.Request(BASE + path, method=method, headers=hdr,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise Fail(f"{method} {path} -> HTTP {e.code}", 4)
    except urllib.error.URLError as e:
        raise Fail(f"{method} {path} -> {e.reason}", 4)


def planned_records(dkim=None):
    recs = [{"type": "TXT", "name": DOMAIN, "content": f"v=spf1 {SPF[PROVIDER]} ~all"},
            {"type": "TXT", "name": f"_dmarc.{DOMAIN}", "content": f"v=DMARC1; p=none; rua=mailto:{OWNER}"}]
    return recs + (dkim or [{"type": "TXT", "name": f"<dkim selector>._domainkey.{DOMAIN}",
                             "content": "<value fetched from provider on apply>"}])


# --- provider adapters: each returns (dkim_records, domain_id) / bool / None ---
def p_records():
    if PROVIDER == "ses":
        import boto3
        c = boto3.client("sesv2")
        try:
            r = c.get_email_identity(EmailIdentity=DOMAIN)
        except c.exceptions.NotFoundException:
            r = c.create_email_identity(EmailIdentity=DOMAIN)
        return [{"type": "CNAME", "name": f"{t}._domainkey.{DOMAIN}", "content": f"{t}.dkim.amazonses.com"}
                for t in r["DkimAttributes"]["Tokens"]], DOMAIN
    if PROVIDER == "resend":
        d = next((x for x in http("GET", "/domains").get("data", []) if x["name"] == DOMAIN), None)
        d = http("GET", f"/domains/{d['id']}") if d else http("POST", "/domains", {"name": DOMAIN})
        return [{"type": r["type"], "name": r["name"] if r["name"].endswith(DOMAIN) else f"{r['name']}.{DOMAIN}",
                 "content": r["value"]} for r in d["records"] if r.get("record") == "DKIM"], d["id"]
    d = next((x for x in http("GET", "/domains?count=100&offset=0").get("Domains", []) if x["Name"] == DOMAIN), None) \
        or http("POST", "/domains", {"Name": DOMAIN})
    d = http("GET", f"/domains/{d['ID']}")
    return [{"type": "TXT", "name": d["DKIMPendingHost"] or d["DKIMHost"], "content": d["DKIMPendingTextValue"] or d["DKIMTextValue"]}], d["ID"]


def p_verified(did):
    if PROVIDER == "ses":
        import boto3
        return boto3.client("sesv2").get_email_identity(EmailIdentity=DOMAIN)["VerifiedForSendingStatus"]
    if PROVIDER == "resend":
        http("POST", f"/domains/{did}/verify")
        return http("GET", f"/domains/{did}")["status"] == "verified"
    return http("PUT", f"/domains/{did}/verifyDkim")["DKIMVerified"]


def p_send():
    frm = os.environ.get("EMAIL_FROM", f"autopilot@{DOMAIN}")
    subj, text = "Autopilot test mail", f"Email for {DOMAIN} works."
    if PROVIDER == "ses":
        import boto3
        boto3.client("sesv2").send_email(FromEmailAddress=frm, Destination={"ToAddresses": [OWNER]},
            Content={"Simple": {"Subject": {"Data": subj}, "Body": {"Text": {"Data": text}}}})
    elif PROVIDER == "resend":
        http("POST", "/emails", {"from": frm, "to": [OWNER], "subject": subj, "text": text})
    else:
        http("POST", "/email", {"From": frm, "To": OWNER, "Subject": subj, "TextBody": text})


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    try:
        if PROVIDER not in SPF:
            raise Fail("EMAIL_PROVIDER must be resend|postmark|ses", 2)
        if not (DOMAIN and OWNER and (TOKEN or PROVIDER == "ses")):
            raise Fail("EMAIL_DOMAIN, OWNER_EMAIL and EMAIL_API_TOKEN are required", 2)
        if dry:
            out(f"[dry-run] {PROVIDER}: would add these records to Cloudflare zone {DOMAIN}:")
            for r in planned_records():
                out(f"[dry-run]   {r['type']} {r['name']} {r['content']}")
            out(f"[dry-run] would poll {PROVIDER} verify, then send a test mail to {OWNER}")
            return 0
        dkim, did = p_records()
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump({"zones": [{"name": DOMAIN, "dns": planned_records(dkim)}]}, f)
        import cloudflare_apply  # ponytail: needs CLOUDFLARE_TOKEN in env; reuses its snapshot/rollback
        try:
            if cloudflare_apply.main(["--file", f.name, "--snapshot", f"cf_snapshot_{DOMAIN}.json"]):
                raise Fail("Cloudflare apply failed", 3)
        finally:
            os.unlink(f.name)
        for i in range(int(os.environ.get("EMAIL_POLL_TRIES", "6"))):
            if p_verified(did):
                break
            time.sleep(float(os.environ.get("EMAIL_POLL_SECS", "10")))
        else:
            raise Fail("provider has not verified the domain yet. Click the verification email link "
                       "from the provider (if one was sent), wait for DNS, then re-run this script", 5)
        p_send()
        out(f"verified; test mail sent to {OWNER}")
    except Fail as e:
        out(f"ERROR: {e}", sys.stderr)
        return e.code
    except Exception as e:  # boto3 missing, malformed provider reply, etc.
        out(f"ERROR: {type(e).__name__}: {e}", sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
