#!/usr/bin/env python3
"""Declarative, idempotent Cloudflare apply (DNS + WAF custom rules).

Usage: cloudflare_apply.py [--dry-run] [--file infra/cloudflare.yaml]
                           [--snapshot cf_snapshot.json] [--rollback [--force-restore]]
Env: CLOUDFLARE_TOKEN (never printed), CLOUDFLARE_API (override base URL, for mocks)
Exit: 0 ok | 2 bad input | 3 auth failed | 4 API/verify error | 6 records changed by hand since the last apply
Rollback: the zone must still be in the state that the last apply left (<snapshot>.after.json). If it is not,
the differences are printed and nothing changes, unless --force-restore is given. It never asks for input.
WAF: unless a zone sets `stage: production`, every rule is downgraded to managed_challenge.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request
import yaml

API = os.environ.get("CLOUDFLARE_API", "https://api.cloudflare.com/client/v4")
TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")
WAF_PHASE = "http_request_firewall_custom"


class CFError(Exception):
    def __init__(self, msg, code=4):
        super().__init__(msg)
        self.code = code


def scrub(s):
    return str(s).replace(TOKEN, "***") if TOKEN else str(s)


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise CFError(f"{method} {path} -> HTTP {e.code}", 3 if e.code in (401, 403) else 4)
    except urllib.error.URLError as e:
        raise CFError(f"{method} {path} -> {scrub(e.reason)}")
    if not data.get("success", True):
        raise CFError(f"{method} {path} -> {scrub(data.get('errors'))}")
    return data.get("result")


def dns_key(r):
    return (r["type"], r["name"], r["content"].strip('"') if r["type"] in ("TXT", "MX") else "")


def dns_val(r):
    return {"content": r["content"].strip('"'), "proxied": bool(r.get("proxied", False)), "ttl": r.get("ttl", 1)}


def want_rules(zone):
    prod = zone.get("stage") == "production"
    return [{"description": r["description"], "expression": r["expression"],
             "action": r["action"] if prod else "managed_challenge"} for r in zone.get("waf", [])]


def get_state(zid):
    dns = call("GET", f"/zones/{zid}/dns_records?per_page=500")
    try:
        rs = call("GET", f"/zones/{zid}/rulesets/phases/{WAF_PHASE}/entrypoint")
    except CFError as e:
        if "404" not in str(e):
            raise
        rs = {"rules": []}
    return {"dns": dns, "waf": [{k: r.get(k) for k in ("description", "expression", "action")}
                                for r in rs.get("rules", [])]}


def plan(zone, state):
    """Return list of (op, payload) for one zone. Matching items yield no op."""
    ops = []
    have = {dns_key(r): r for r in state["dns"]}
    for d in zone.get("dns", []):
        cur = have.get(dns_key(d))
        if cur is None:
            ops.append(("POST_DNS", d))
        elif dns_val(cur) != dns_val({**{"ttl": 1}, **d}):
            ops.append(("PATCH_DNS", {**d, "id": cur["id"]}))
    if zone.get("waf") is not None and want_rules(zone) != state["waf"]:
        ops.append(("PUT_WAF", want_rules(zone)))
    return ops


def run_op(zid, op, p):
    if op == "POST_DNS":
        call("POST", f"/zones/{zid}/dns_records", p)
    elif op == "PATCH_DNS":
        call("PATCH", f"/zones/{zid}/dns_records/{p['id']}", {k: v for k, v in p.items() if k != "id"})
    elif op == "PUT_WAF":
        call("PUT", f"/zones/{zid}/rulesets/phases/{WAF_PHASE}/entrypoint", {"rules": p})


def zone_id(name):
    res = call("GET", "/zones?name=" + urllib.parse.quote(name))
    if not res:
        raise CFError(f"zone {name} not found")
    return res[0]["id"]


def after_path(snap_path):
    return os.path.splitext(snap_path)[0] + ".after.json"


def hand_edits(left, now):
    """What changed between the state that the last apply left and the state now (as lines)."""
    rec = lambda st: {json.dumps([dns_key(r), dns_val(r)]) for r in st["dns"]}  # noqa: E731
    a, b = rec(left), rec(now)
    return ([f"removed: {x}" for x in sorted(a - b)] + [f"added or changed: {x}" for x in sorted(b - a)]
            + (["WAF rules changed"] if left["waf"] != now["waf"] else []))


def rollback(snap_path, dry, force=False):
    snap = json.load(open(snap_path))
    try:
        left = json.load(open(after_path(snap_path)))
    except FileNotFoundError:
        left = {}
    zones, edits = [], []
    for name in snap:
        zid = zone_id(name)
        cur = get_state(zid)
        zones.append((name, zid, cur))
        edits += [f"{name}: {x}" for x in (hand_edits(left[name], cur) if name in left
                                          else ["no record of the last apply, so hand edits are not known"])]
    if edits and not force:  # never overwrite hand edits without notice
        for x in edits:
            print(scrub(x), file=sys.stderr)
        raise CFError("the zone changed since the last apply; nothing was restored. "
                      "Check the lines above, then run again with --force-restore to overwrite them", 6)
    for name, zid, cur in zones:
        s = snap[name]
        # ponytail: restore = re-create snapshot records missing now + restore WAF; extra records are left.
        want = {"dns": [d for d in s["dns"]], "waf": s["waf"]}
        ops = plan({"dns": want["dns"], "waf": want["waf"], "stage": "production"}, cur)
        for op, p in ops:
            print(f"{'[dry-run] ' if dry else ''}rollback {name}: {op} {scrub(json.dumps(p))}")
            if not dry:
                run_op(zid, op, p)


def apply(cfg, dry, snap_path):
    zones = cfg.get("zones") or []
    if not zones:
        raise CFError("no zones in file", 2)
    snap, work = {}, []
    for z in zones:
        zid = zone_id(z["name"])
        st = get_state(zid)
        snap[z["name"]] = st
        work.append((z, zid, plan(z, st)))
    for z, zid, ops in work:
        if z.get("waf") and z.get("stage") != "production":
            print(f"note {z['name']}: staging, WAF actions forced to managed_challenge")
        if not ops:
            print(f"{z['name']}: no changes")
        for op, p in ops:
            print(f"{'[dry-run] ' if dry else ''}{z['name']}: {op} {scrub(json.dumps(p))}")
    if dry:
        return
    if any(ops for _, _, ops in work):
        json.dump(snap, open(snap_path, "w"), indent=2)
        print(f"snapshot saved: {snap_path}")
    after = {}
    try:
        for z, zid, ops in work:
            for op, p in ops:
                run_op(zid, op, p)
            after[z["name"]] = st = get_state(zid)
            left = plan(z, st)  # verify
            if left:
                raise CFError(f"verify failed for {z['name']}: {len(left)} pending ops")
            print(f"{z['name']}: verified")
    finally:  # a rollback compares the zone with this state first; a failed apply must leave it too
        if any(ops for _, _, ops in work):
            for z, zid, _ in work:
                if z["name"] not in after:
                    try:
                        after[z["name"]] = get_state(zid)
                    except CFError:
                        pass  # no record for this zone: its rollback then needs --force-restore
            json.dump(after, open(after_path(snap_path), "w"), indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--force-restore", action="store_true", help="rollback even if records changed by hand")
    ap.add_argument("--file", default="infra/cloudflare.yaml")
    ap.add_argument("--snapshot", default="cf_snapshot.json")
    a = ap.parse_args(argv)
    try:
        if not TOKEN:
            raise CFError("CLOUDFLARE_TOKEN not set", 3)
        call("GET", "/user/tokens/verify")  # fail early on bad token, before any change (apply and rollback)
        if a.rollback:
            rollback(a.snapshot, a.dry_run, a.force_restore)
        else:
            apply(yaml.safe_load(open(a.file)) or {}, a.dry_run, a.snapshot)
    except (CFError, OSError, yaml.YAMLError, KeyError) as e:
        code = e.code if isinstance(e, CFError) else 2
        print(f"ERROR: {scrub(e)}", file=sys.stderr)
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
