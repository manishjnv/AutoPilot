"""J9: the browser page of the dashboard. One self-contained HTML string from the plain dict of
dashboard.py::dashboard_data. No external resource and no library. Every dynamic value goes through html.escape."""
from __future__ import annotations

from html import escape as e

CSS = """
:root{--bg:#f3f4f6;--panel:#fff;--panel-2:#eef0f3;--line:#c9ced6;--text:#14181f;--muted:#505968;
--good:#17702f;--bad:#b3261e;--warn:#8a5300;--count:#0a6680;--hl:#e3f1f6;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--r1:6px;--r2:10px;
--t11:11px;--t12:12px;--t13:13px;--t14:14px;--t16:16px;--t18:18px;--t24:24px;
--font:ui-monospace,Consolas,"Cascadia Mono",monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0b0e13;--panel:#141922;--panel-2:#1b212c;--line:#2d3542;
--text:#e8edf3;--muted:#9aa5b5;--good:#4cc16a;--bad:#ff7b72;--warn:#e6b84a;--count:#5cd0e0;--hl:#16303a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:var(--t13)/1.5 var(--font);font-variant-numeric:tabular-nums}
main{padding:var(--s4) var(--s4) 64px;max-width:1600px;margin:0 auto}
#off{margin:0;padding:var(--s2) var(--s4);background:var(--warn);color:var(--bg);font-size:var(--t13);font-weight:600}
h1{font-size:var(--t18);margin:0 0 var(--s4);overflow-wrap:anywhere}
h2{font-size:var(--t11);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 var(--s3);font-weight:600}
.grid{display:grid;gap:var(--s4);grid-template-columns:minmax(0,1fr)}
.grid section,.next{background:var(--panel);border:1px solid var(--line);border-radius:var(--r2);padding:var(--s4);min-width:0}
.col{display:contents}
@media (max-width:699px){#tasks th:nth-child(n+4),#tasks td:nth-child(n+4){display:none}}
#progress{order:1}#project{order:2}#tasks{order:3}#live{order:4}#usage{order:5}#files{order:6}#issues{order:7}
@media (min-width:700px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}#tasks,#live{grid-column:1/-1}}
@media (min-width:1100px){.grid{grid-template-columns:280px minmax(0,1fr) 300px;align-items:start}
.col{display:grid;gap:var(--s4);min-width:0;grid-template-columns:minmax(0,1fr)}#tasks,#live{grid-column:auto}}
dl{margin:0}
dl div{display:flex;justify-content:space-between;gap:var(--s3);padding:var(--s1) 0}
dt{color:var(--muted)}dd{margin:0;font-weight:600;text-align:right;overflow-wrap:anywhere;min-width:0}
.big{font-size:var(--t24);font-weight:700;line-height:1.2}
.row{display:flex;justify-content:space-between;gap:var(--s3);padding:var(--s1) 0}
.bar{height:8px;background:var(--panel-2);border:1px solid var(--line);border-radius:var(--r1);overflow:hidden;margin:var(--s1) 0 var(--s2)}
.bar i{display:block;height:100%;background:var(--count)}
.bar.ok i{background:var(--good)}
.box{overflow:auto;max-height:420px}
table{width:100%;border-collapse:collapse;font-size:var(--t13)}
th{font-size:var(--t11);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);text-align:left;font-weight:600;
padding:var(--s2);border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
td:first-child{white-space:nowrap}
td{padding:var(--s2);border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tr[aria-current=true]{background:var(--hl)}
.done{color:var(--good)}.running{color:var(--count)}.blocked{color:var(--bad)}.pending{color:var(--muted)}
.st{white-space:nowrap;font-weight:600}
#live .box{max-height:300px}
.l{display:flex;gap:var(--s3);padding:1px 0}
.l time{color:var(--muted);flex:none;min-width:5ch}
.l span{min-width:0;overflow-wrap:anywhere}
.l.heading span{font-weight:700}.l.goal span{color:var(--muted)}.l.good span{color:var(--good)}
.l.bad span{color:var(--bad)}.l.note span{color:var(--warn)}.l.blank{height:var(--s2)}
.num{color:var(--count);font-weight:600}.bad{color:var(--bad);font-weight:600}.good{color:var(--good);font-weight:600}
.next{margin-top:var(--s4)}.next ul{margin:0;padding-left:var(--s4)}.next li{padding:var(--s1) 0}
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


def render(data: dict, refresh: int = 30, report_md: str = "") -> str:
    p, g, u = data.get("project") or {}, data.get("progress") or {}, data.get("usage") or {}
    tasks, health, files = data.get("tasks") or [], data.get("health") or {}, data.get("files")
    done, total, pct = int(g.get("done") or 0), int(g.get("total") or 0), int(g.get("pct") or 0)
    eta = p.get("eta") or ""
    run = next((t for t in tasks if t.get("status") == "running"), None)
    here = run.get("n") if run else done

    proj = _dl([("Name", p.get("name")), ("Branch", p.get("branch")), ("Commit", p.get("commit")), ("Model", p.get("model")),
                ("Run id", p.get("run_id")), ("Start", p.get("started")), ("Status", p.get("status")),
                ("Elapsed", p.get("elapsed")), ("Time left", eta),
                ("Attempt", p.get("attempt") if int(p.get("attempt") or 0) > 1 else "")])
    proj = f'<p>{e(str(p.get("state_words") or ""))}</p>' + proj

    prog = (f'<div class="big">{pct}%</div>{_bar(pct / 100, "Progress", "ok")}'
            f'<div class="row"><span>{done} of {total} tasks</span></div>'
            f'<div class="row"><span>{int(g.get("phases_done") or 0)} of {int(g.get("phases_total") or 0)} phases</span></div>'
            + (f'<div class="row"><span>Time left</span><span class="num">{e(str(eta))}</span></div>' if eta else ""))

    bars = "".join(f'<div class="row"><span>{lab}</span><span class="num">{round(_v(u[k]) * 100)}%</span></div>{_bar(u[k], lab)}'
                   for k, lab in (("five", "5-hour window"), ("week", "Week"), ("context", "Context"))
                   if u.get(k) is not None)
    models = "".join(f'<div class="row"><span>{e(str(m.get("name", "")))}</span>'
                     f'<span>{e(str(m.get("tokens_text", "")))} <span class="num">{round(_v(m.get("share")) * 100)}%</span></span></div>'
                     f'{_bar(m.get("share"), str(m.get("name", "")))}' for m in u.get("models") or [])
    usage = (bars + f'<div class="row"><span>Tokens</span><strong>{e(str(u.get("tokens_text") or "0"))}</strong></div>'
             + models + f'<div class="row"><span>Cost</span><strong>${float(u.get("cost") or 0):.2f}</strong></div>')

    def n(k):
        return f'<span class="num">{int(g.get(k) or 0)}</span>'

    issues = (f'<div class="row"><span>Blocked tasks</span>{n("blocked")}</div>'
              f'<div class="row"><span>Questions for you</span>{n("questions")}</div>'
              f'<div class="row"><span>Gate warnings</span>{n("warnings")}</div>')
    for lab, k in (("Git", "git"), ("Checks", "checks")):
        if health.get(k):
            ok = health[k] == "OK"
            issues += f'<div class="row"><span>{lab}</span><span class="{"good" if ok else "bad"}">{e(str(health[k]))}</span></div>'

    # three columns on a wide window; on a narrow one the columns dissolve and the `order` of each panel decides
    right = [_sec("progress", "Progress", prog), _sec("usage", "Usage", usage)]
    if files is not None:
        right.append(_sec("files", "Files", _dl([("Added", files.get("added", 0)), ("Modified", files.get("modified", 0)),
                                                  ("Deleted", files.get("deleted", 0))])))
    right.append(_sec("issues", "Issues", issues))
    cols = ([_sec("project", "Project", proj)],
            [_sec("tasks", "Tasks", _tasks(tasks)), _sec("live", "Live output", _live(data.get("live") or []))], right)
    cells = [f'<div class="col">{"".join(c)}</div>' for c in cols]

    nxt = "".join(f"<li><code>{e(str(r[0]))}</code> {e(str(r[1]) if len(r) > 1 else '')}</li>"
                  for r in data.get("next") or [] if r)
    nxt = f'<section class="next" aria-labelledby="next-h"><h2 id="next-h">What you can do next</h2><ul>{nxt}</ul></section>' if nxt else ""

    bar = (f'<footer><span>{e(str(p.get("name") or ""))}</span><span class="m">{e(str(p.get("branch") or ""))}</span>'
           f'<span class="m">{e(str(p.get("commit") or ""))}</span><span>Task {e(str(here))}/{total}</span>'
           f'<span>{_bar(pct / 100, "Progress", "ok")}{pct}%</span>'
           + (f"<span>Left {e(str(eta))}</span>" if eta else "")
           + f'<span>Blocked {int(g.get("blocked") or 0)}</span><span>Tok {e(str(u.get("tokens_text") or "0"))}</span>'
           f'<span>${float(u.get("cost") or 0):.2f}</span></footer>')

    rep = f"<details><summary>Full report</summary><pre>{e(report_md)}</pre></details>" if report_md else ""
    ms = int(refresh) * 1000
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(str(data.get('line') or ''))}</title><style>{CSS}</style>"
            f"<noscript><meta http-equiv=refresh content={int(refresh)}></noscript></head><body>"
            "<p id=off hidden>The build stopped, or the status server is off. This page shows the last status. "
            "For the status now, run: ap status</p>"
            f'<main><h1>{e(str(p.get("name") or "Autopilot"))}</h1><div class="grid">{"".join(cells)}</div>'
            f"{nxt}{bar}{rep}</main>{SCRIPT.replace('REFRESH_MS', str(ms))}</body></html>")
