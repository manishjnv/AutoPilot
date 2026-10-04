"""J9: the browser page of the dashboard. One self-contained HTML string from the plain dict of
dashboard.py::dashboard_data. No external resource and no library. Every dynamic value goes through html.escape."""
from __future__ import annotations

from html import escape as e

CSS = """
:root{color-scheme:light dark;--bg:#f3f4f6;--panel:#fff;--panel-2:#e9ecf0;--line:#b9c0ca;--text:#0b0f16;--muted:#3d4654;
--good:#0f5c24;--bad:#a01b14;--warn:#7a4700;--count:#075a72;--hl:#dcedf4;--row:3px;--cell:6px;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--r1:6px;--r2:10px;
--t11:11px;--t12:12px;--t13:13px;--t14:14px;--t16:16px;--t18:18px;--t24:24px;
--font:ui-monospace,Consolas,"Cascadia Mono",monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0b0e13;--panel:#141922;--panel-2:#1b212c;--line:#3a4454;
--text:#f4f7fa;--muted:#b6c0ce;--good:#62d67f;--bad:#ff8e86;--warn:#f2c754;--count:#72deee;--hl:#173440}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:var(--t13)/1.4 var(--font);font-variant-numeric:tabular-nums}
main{padding:var(--s4) var(--s4) 64px}
#off{margin:0;padding:var(--s2) var(--s4);background:var(--warn);color:var(--bg);font-size:var(--t13);font-weight:600}
h1{font-size:var(--t18);margin:0 0 var(--s4);overflow-wrap:anywhere}
h2{font-size:var(--t11);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 var(--s2);font-weight:600}
.grid{display:grid;gap:var(--s4);grid-template-columns:minmax(0,1fr)}
.grid section,.next{background:var(--panel);border:1px solid var(--line);border-radius:var(--r2);padding:var(--s4);min-width:0}
.col{display:contents}
@media (max-width:699px){#tasks th:nth-child(n+4),#tasks td:nth-child(n+4){display:none}}
#progress{order:1}#project{order:2}#tasks{order:3}#live{order:4}#usage{order:5}#files{order:6}#issues{order:7}
@media (min-width:700px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}#tasks,#live{grid-column:1/-1}}
@media (min-width:1100px){.grid{grid-template-columns:minmax(260px,1fr) minmax(0,3.2fr) minmax(280px,1.1fr);align-items:start}
.col{display:grid;gap:var(--s4);min-width:0;grid-template-columns:minmax(0,1fr)}#tasks,#live{grid-column:auto}}
dl{margin:0}
dl div{display:flex;justify-content:space-between;gap:var(--s3);padding:var(--row) 0}
dt{color:var(--muted)}dd{margin:0;font-weight:600;text-align:right;overflow-wrap:anywhere;min-width:0}
.big{font-size:var(--t24);font-weight:700;line-height:1.2}
.row{display:flex;justify-content:space-between;gap:var(--s3);padding:var(--row) 0}
.bar{height:8px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--r1);overflow:hidden;margin:var(--s1) 0 var(--s2)}
.bar i{display:block;height:100%;background:var(--count)}
.bar.ok i{background:var(--good)}.bar.warn i{background:var(--warn)}.bar.bad i{background:var(--bad)}
h3{font-size:var(--t11);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:var(--s3) 0 var(--s1);font-weight:600}
.w{color:var(--warn);font-weight:600}.z{color:var(--muted)}.t-good{color:var(--good)}.t-wait{color:var(--warn)}.t-bad{color:var(--bad)}
#needs{background:var(--panel);border:2px solid var(--warn);border-radius:var(--r2);padding:var(--s4);margin-bottom:var(--s4)}
#needs p{margin:0 0 var(--s2)}#needs ul{margin:0 0 var(--s2);padding-left:var(--s4)}
.box{overflow:auto;max-height:max(320px,calc(48vh - 110px))}
table{width:100%;border-collapse:collapse;font-size:var(--t13)}
th{font-size:var(--t11);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);text-align:left;font-weight:600;
padding:var(--cell) var(--s2);border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
td:first-child{white-space:nowrap}
td{padding:var(--cell) var(--s2);border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tr[aria-current=true]{background:var(--hl)}
.done{color:var(--good)}.running{color:var(--good)}.blocked{color:var(--bad)}.pending{color:var(--muted)}
.st{white-space:nowrap;font-weight:600}
#live .box{max-height:max(240px,calc(40vh - 110px))}
.l{display:flex;gap:var(--s3)}
.l time{color:var(--muted);flex:none;min-width:5ch}
.l span{min-width:0;overflow-wrap:anywhere}
.l.heading span{font-weight:700}.l.goal span{color:var(--muted)}.l.good span{color:var(--good)}
.l.bad span{color:var(--bad)}.l.note span{color:var(--warn)}.l.blank{height:var(--s2)}
.num{color:var(--count);font-weight:600}.bad{color:var(--bad);font-weight:600}.good{color:var(--good);font-weight:600}
.next{margin-top:var(--s4)}.next ul{margin:0;padding-left:var(--s4)}.next li{padding:var(--row) 0}
code{color:var(--count);font-weight:600}
details{margin-top:var(--s4)}summary{cursor:pointer;color:var(--muted);font-size:var(--t12)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel);border:1px solid var(--line);
border-radius:var(--r2);padding:var(--s4);font:var(--t13)/1.5 var(--font)}
footer{position:fixed;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:var(--s1) var(--s4);align-items:center;
background:var(--panel);border-top:1px solid var(--line);padding:var(--s2) var(--s4);font-size:var(--t12);font-weight:600}
footer .bar{width:96px;margin:0;display:inline-block;vertical-align:middle}
footer .m{color:var(--muted);font-weight:400}
"""

SCRIPT = ("<script type=module>const end=x=>x.scrollHeight-x.scrollTop-x.clientHeight<8,"
          "see=()=>{const r=document.querySelector('tr[aria-current]'),b=r&&r.closest('[data-keep]');"
          "if(b)b.scrollTop=r.offsetTop-b.clientHeight/2;const l=document.querySelector('#live [data-keep]');"
          "if(l)l.scrollTop=l.scrollHeight};see();"
          "setInterval(async()=>{const off=document.getElementById('off');try{const r=await "
          "fetch(location.href,{cache:'no-store'});if(!r.ok)throw 0;const d=new DOMParser().parseFromString("
          "await r.text(),'text/html');const o=document.querySelector('details')?.open,"
          "s=[...document.querySelectorAll('[data-keep]')].map(x=>x.id=='out'&&end(x)?1e9:x.scrollTop);"
          "document.querySelector('main').replaceWith(d.querySelector('main'));"
          "const n=document.querySelector('details');if(n&&o)n.open=true;"
          "document.querySelectorAll('[data-keep]').forEach((x,i)=>{x.scrollTop=s[i]||0});"
          "document.title=d.title;off.hidden=true}catch(x){off.hidden=false}},REFRESH_MS)</script>")

WORDS = {"done": ("Complete", "✓"), "running": ("In progress", "▶"), "blocked": ("Blocked", "✗"),
         "pending": ("Pending", "○")}


def _v(v) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _bar(v, label: str, cls: str = "") -> str:
    p = round(_v(v) * 100)
    return f'<div class="bar {cls}" role="img" aria-label="{e(label)} {p} percent"><i style="width:{p}%"></i></div>'


def _dl(rows) -> str:
    return "<dl>" + "".join(f"<div><dt>{e(k)}</dt><dd>{e(str(v))}</dd></div>" for k, v in rows if str(v or "") != "") + "</dl>"


def _sec(i: str, title: str, body: str) -> str:
    return f'<section id="{i}" aria-labelledby="{i}-h"><h2 id="{i}-h">{e(title)}</h2>{body}</section>'


def _tasks(tasks) -> str:
    rows = []
    for t in tasks:
        st = t.get("status") or "pending"
        word, sym = WORDS.get(st, WORDS["pending"])
        cur = ' aria-current="true"' if st == "running" else ""
        rows.append(f'<tr{cur}><td>{e(str(t.get("n", "")))}</td><td>{e(str(t.get("title", "")))}</td>'
                    f'<td class="st {e(st if st in WORDS else "pending")}">{sym} {word}</td>'
                    f'<td>{e(str(t.get("time", "")))}</td><td>{e(str(t.get("detail", "")))}</td></tr>')
    head = "".join(f"<th scope=col>{h}</th>" for h in ("#", "Task", "Status", "Time", "Detail"))
    return f'<div class="box" data-keep tabindex="0"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _live(rows) -> str:
    if not rows:
        return "<p>No output yet.</p>"
    out = []
    for r in rows:
        k = r.get("kind") or "step"
        k = k if k in ("heading", "goal", "step", "good", "bad", "note", "blank") else "step"
        out.append(f'<div class="l {k}"><time>{e(str(r.get("at", "")))}</time><span>{e(str(r.get("text", "")))}</span></div>'
                   if k != "blank" else '<div class="l blank"></div>')
    return f'<div class="box" id="out" data-keep tabindex="0">{"".join(out)}</div>'


def _lvl(v) -> str:
    return "ok" if _v(v) < 0.7 else "warn" if _v(v) < 0.9 else "bad"


def _i(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _count(label: str, v, cls: str) -> str:
    """One row with a count; cls is the colour class for a value above 0 (muted at 0)."""
    c = cls if _i(v) > 0 else "z"
    return f'<div class="row"><span>{label}</span><span class="{c}">{_i(v)}</span></div>'


def _group(title: str, body: str) -> str:
    return f"<h3>{e(title)}</h3>{body}" if body else ""


def _project(p: dict, total: int, sz) -> str:
    tone = p.get("tone") if p.get("tone") in ("good", "wait", "bad") else ""
    st = e(str(p.get("status") or ""))
    status = (f'<div class="row"><span class="z">Status</span><strong class="t-{tone}">{st}</strong></div>' if tone
              else _dl([("Status", p.get("status"))]))
    out = (_dl([("Branch", p.get("branch"))]) + status + f'<p>{e(str(p.get("state_words") or ""))}</p>'
           + _dl([("Start", p.get("started")), ("Elapsed", p.get("elapsed")), ("Time left", p.get("eta"))]))
    if _i(p.get("stale_min")) > 0:
        c = {"warn": "w", "bad": "bad"}.get(p.get("stale"), "z")
        out += f'<p class="{c}">No change for {_i(p.get("stale_min"))} min.</p>'
    nw, body = p.get("now") or {}, ""
    if nw.get("n"):
        body += f'<p>Task {_i(nw["n"])} of {total}</p>'
    if nw.get("title"):
        body += f'<p><strong>{e(str(nw["title"]))}</strong></p>'
    if nw.get("n") and _i(nw.get("attempt")) > 0:
        a, m = _i(nw["attempt"]), _i(nw.get("max_attempts"))
        c = "z" if a < 2 else "w" if a == 2 else "bad"
        body += f'<p class="{c}">Try {a}{f" of {m}" if m else ""}</p>'
    if nw.get("n"):
        body += _dl([("Time", nw.get("time"))])
    body += _dl([("Model", nw.get("model"))])
    out += _group("Now", body if nw else "")
    out += _group("Next", f'<p>{e(str(p["next"]))}</p>' if p.get("next") else "")
    if sz:
        rows = [("Code", f'{_i(sz.get("code")):,} lines'),
                ("Tests", f'{_i(sz.get("tests")):,} lines, {_i(sz.get("test_count")):,} tests'),
                ("Docs", f'{_i(sz.get("docs")):,} lines')]
        if sz.get("run_lines") is not None:
            rows.append(("This run", f'+{_i(sz["run_lines"]):,} lines, {_i(sz.get("run_files")):,} files'))
        out += _group("Size", _dl(rows))
    if p.get("last_commit"):
        age = f' <span class="z">{e(str(p["last_commit_age"]))} ago</span>' if p.get("last_commit_age") else ""
        out += _group("Last commit", f'<p>{e(str(p["last_commit"]))}{age}</p>')
    return out


def render(data: dict, refresh: int = 30, report_md: str = "") -> str:
    p, g, u = data.get("project") or {}, data.get("progress") or {}, data.get("usage") or {}
    tasks, health, files = data.get("tasks") or [], data.get("health") or {}, data.get("files")
    done, total, pct = _i(g.get("done")), _i(g.get("total")), _i(g.get("pct"))
    eta, active = p.get("eta") or "", _i(g.get("active"))
    proj = _project(p, total, data.get("size"))

    prog = (f'<div class="big">{pct}%</div>{_bar(pct / 100, "Progress")}'
            f'<div class="row"><span>{done} done · {_i(g.get("working"))} working</span></div>'
            f'<div class="row"><span><span class="{"bad" if _i(g.get("blocked")) > 0 else ""}">{_i(g.get("blocked"))} blocked</span>'
            f' · {_i(g.get("waiting"))} waiting</span></div>'
            f'<div class="row"><span>{_i(g.get("phases_done"))} of {_i(g.get("phases_total"))} phases</span></div>'
            + (f'<div class="row"><span>Time left</span><span class="num">{e(str(eta))}</span></div>' if eta else ""))

    bars = ""
    for k, lab in (("five", "5-hour window"), ("week", "Week"), ("context", "Context")):
        if u.get(k) is not None:
            bars += (f'<div class="row"><span>{lab}</span><span class="num">{round(_v(u[k]) * 100)}%</span></div>'
                     f'{_bar(u[k], lab, _lvl(u[k]))}')
            if k == "five" and u.get("reset_in"):
                bars += f'<div class="z">Resets in {e(str(u["reset_in"]))}</div>'
    models = "".join(f'<div class="row"><span>{e(str(m.get("name", "")))}</span>'
                     f'<span>{e(str(m.get("tokens_text", "")))} <span class="num">{round(_v(m.get("share")) * 100)}%</span></span></div>'
                     f'{_bar(m.get("share"), str(m.get("name", "")))}' for m in u.get("models") or [])
    usage = (bars + f'<div class="row"><span>Tokens</span><strong>{e(str(u.get("tokens_text") or "0"))}</strong></div>'
             + models + f'<div class="row"><span>Cost</span><strong>${float(u.get("cost") or 0):.2f}</strong></div>')

    bw = data.get("blocked_why") or {}
    issues = _count("Blocked tasks", g.get("blocked"), "bad")
    if bw:
        issues += f'<div class="bad">{e(str(bw.get("id", "")))}: {e(str(bw.get("why", "")))}</div>'
    issues += _count("Questions for you", g.get("questions"), "w") + _count("Gate warnings", g.get("warnings"), "w")
    for lab, k in (("Git", "git"), ("Checks", "checks")):
        if health.get(k):
            issues += (f'<div class="row"><span>{lab}</span><span class="{"good" if health[k] == "OK" else "bad"}">'
                       f'{e(str(health[k]))}</span></div>')
    if health.get("words"):
        issues += f'<p class="bad">{e(str(health["words"]))}</p>'

    def fv(k, cls):
        v = _i((files or {}).get(k))
        return (f'<div class="row"><span class="z">{k.capitalize()}</span>'
                f'<strong class="{cls if v > 0 and cls else "" if v > 0 else "z"}">{v}</strong></div>')

    # three columns on a wide window; on a narrow one the columns dissolve and the `order` of each panel decides
    right = [_sec("progress", "Progress", prog), _sec("usage", "Usage", usage)]
    if files is not None:
        right.append(_sec("files", "Files", fv("added", "good") + fv("modified", "") + fv("deleted", "bad")))
    right.append(_sec("issues", "Issues", issues))
    cols = ([_sec("project", "Project", proj)],
            [_sec("tasks", "Tasks", _tasks(tasks)), _sec("live", "Live output", _live(data.get("live") or []))], right)
    cells = [f'<div class="col">{"".join(c)}</div>' for c in cols]

    need, needs = data.get("needs_you") or [], ""
    if need:
        k = len(need)
        li = "".join(f"<li>{e(str(x.get('title', '')))}</li>" for x in need)
        needs = (f'<section id="needs" role="status" aria-labelledby="needs-h"><h2 id="needs-h">Questions for you</h2>'
                 f'<p><strong>{k} question{" waits" if k == 1 else "s wait"} for you.</strong></p><ul>{li}</ul>'
                 f'<p>Run: <code>ap answer</code></p></section>')

    nxt = "".join(f"<li><code>{e(str(r[0]))}</code> {e(str(r[1]) if len(r) > 1 else '')}</li>"
                  for r in data.get("next") or [] if r)
    nxt = f'<section class="next" aria-labelledby="next-h"><h2 id="next-h">What you can do next</h2><ul>{nxt}</ul></section>' if nxt else ""

    nb = _i(g.get("blocked"))
    bar = (f'<footer><span>{e(str(p.get("name") or ""))}</span><span class="m">{e(str(p.get("branch") or ""))}</span>'
           + (f"<span>Task {active}/{total}</span>" if active > 0 else f"<span>Done {done}/{total}</span>")
           + f'<span>{_bar(pct / 100, "Progress")}{pct}%</span>'
           + (f"<span>Left {e(str(eta))}</span>" if eta else "")
           + f'<span class="{"bad" if nb else "z"}">Blocked {nb}</span><span>Tok {e(str(u.get("tokens_text") or "0"))}</span>'
           f'<span>${float(u.get("cost") or 0):.2f}</span></footer>')

    rep = f"<details><summary>Full report</summary><pre>{e(report_md)}</pre></details>" if report_md else ""
    ms = int(refresh) * 1000
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(str(data.get('line') or ''))}</title><style>{CSS}</style>"
            f"<noscript><meta http-equiv=refresh content={int(refresh)}></noscript></head><body>"
            "<p id=off hidden>The build stopped, or the status server is off. This page shows the last status. "
            "For the status now, run: ap status</p>"
            f'<main><h1>{e(str(p.get("name") or "Autopilot"))}</h1>{needs}<div class="grid">{"".join(cells)}</div>'
            f"{nxt}{bar}{rep}</main>{SCRIPT.replace('REFRESH_MS', str(ms))}</body></html>")
