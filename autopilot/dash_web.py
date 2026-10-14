"""J9: the browser page of the dashboard. One self-contained HTML string from the plain dict of
dashboard.py::dashboard_data. No external resource and no library. Every dynamic value goes through html.escape."""
from __future__ import annotations

from html import escape as e

from . import dash_card, dash_live

CSS = """
:root{color-scheme:light dark;--bg:#f3f4f6;--panel:#fff;--panel-2:#e9ecf0;--line:#b9c0ca;--text:#0b0f16;--muted:#3d4654;
--good:#0f5c24;--bad:#a01b14;--warn:#7a4700;--count:#075a72;--use:#8a1f7a;--model:#1d4fa8;--hl:#dcedf4;--row:3px;--cell:6px;
--s1:4px;--s2:8px;--s3:12px;--s4:16px;--r1:6px;--r2:10px;
--t11:11px;--t12:12px;--t13:13px;--t14:14px;--t16:16px;--t18:18px;--t24:24px;
--font:ui-monospace,Consolas,"Cascadia Mono",monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0b0e13;--panel:#141922;--panel-2:#1b212c;--line:#3a4454;
--text:#f4f7fa;--muted:#b6c0ce;--good:#62d67f;--bad:#ff8e86;--warn:#f2c754;--count:#72deee;--use:#e58ae0;--model:#8ab4ff;--hl:#173440}}
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
.bar i{display:block;height:100%;background:var(--use)}
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
tr[aria-current=true]{background:var(--count);color:var(--bg);font-weight:700}
tr[aria-current=true] td{color:inherit}
.done{color:var(--good)}.running{color:var(--count)}.blocked{color:var(--bad)}.pending{color:var(--muted)}
.st{white-space:nowrap;font-weight:600}
#live .box{max-height:max(240px,calc(40vh - 110px))}
.l{display:flex;gap:var(--s3)}
.l time{color:var(--muted);flex:none;min-width:5ch}
.l span{min-width:0;overflow-wrap:anywhere}
.l.heading span{font-weight:700}.l.goal span{color:var(--muted)}.l.wait span{color:var(--warn);opacity:.6}.l.test span{color:var(--count)}.l .v{color:var(--muted);font-weight:400}.l .took{margin-left:auto;color:var(--muted)}.l.good span{color:var(--good)}
.l.bad span{color:var(--bad)}.l.note span{color:var(--warn)}.l.blank{height:var(--s2)}
.mg{color:var(--use);font-weight:600}.bl{color:var(--model)}.bad{color:var(--bad);font-weight:600}.good{color:var(--good);font-weight:600}
.next{margin-top:var(--s4)}.next ul{margin:0;padding-left:var(--s4)}.next li{padding:var(--row) 0}
code{color:var(--count);font-weight:600}
details{margin-top:var(--s4)}summary{cursor:pointer;color:var(--muted);font-size:var(--t12)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel);border:1px solid var(--line);
border-radius:var(--r2);padding:var(--s4);font:var(--t13)/1.5 var(--font)}
footer{position:fixed;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:var(--s1) var(--s4);align-items:center;
background:var(--panel);border-top:1px solid var(--line);padding:var(--s2) var(--s4);font-size:var(--t12);font-weight:600}
footer .bar{width:96px;margin:0;display:inline-block;vertical-align:middle}
footer .m{color:var(--muted);font-weight:400}
.spin{display:inline-block;width:.9em;height:.9em;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;
vertical-align:-.1em;margin-right:var(--s2);animation:sp .8s steps(8) infinite}
.spin.run{color:var(--count)}.spin.stale{color:var(--warn)}.spin.stopped{color:var(--bad)}.spin.paused{animation-play-state:paused}
@keyframes sp{to{transform:rotate(360deg)}}
#now{background:var(--panel);border:1px solid var(--line);border-radius:var(--r2);padding:var(--s3) var(--s4);margin-bottom:var(--s4)}
#now h2{display:flex;flex-wrap:wrap;gap:var(--s1) var(--s3);align-items:baseline;text-transform:none;letter-spacing:0;font-size:var(--t14);color:var(--text)}
#now h2 .lab{background:var(--count);color:var(--bg);font-weight:700;padding:0 var(--s2);border-radius:var(--r1);text-transform:uppercase;font-size:var(--t11)}
#now h2 .age{margin-left:auto;color:var(--muted);font-weight:400}
#now p{margin:var(--row) 0}
.seg{display:flex;gap:var(--s1);margin:var(--s2) 0}
.seg span{position:relative;overflow:hidden;min-width:3.2em;padding:0 var(--s1);border:1px solid var(--line);border-radius:var(--r1);font-size:var(--t12);white-space:nowrap}
.seg .d{background:var(--good);color:var(--bg);border-color:var(--good)}.seg .n{color:var(--muted)}
.seg .r{color:var(--text)}.seg .r i{position:absolute;left:0;top:0;bottom:0;background:var(--count);opacity:.45}
.seg .r b{position:absolute;top:0;bottom:0;width:.8em;background:var(--text);opacity:.35;animation:sh 1s steps(8) infinite;left:0}
.seg .r em{position:relative;font-style:normal}
@keyframes sh{to{left:calc(var(--fill) - .8em)}}
#now.ended li{margin:var(--row) 0}
@media (prefers-reduced-motion:reduce){.seg .r b{animation:none}}
@media (prefers-reduced-motion:reduce){.spin{animation:none}}
"""

SCRIPT = ("<script type=module>const end=x=>x.scrollHeight-x.scrollTop-x.clientHeight<8,"
          "see=()=>{const r=document.querySelector('tr[aria-current]'),b=r&&r.closest('[data-keep]');"
          "if(b)b.scrollTop=r.offsetTop-b.clientHeight/2;const l=document.querySelector('#live [data-keep]');"
          "if(l)l.scrollTop=l.scrollHeight};see();"
          "setInterval(async()=>{const off=document.getElementById('off');try{const r=await "
          "fetch(location.href,{cache:'no-store'});if(!r.ok)throw 0;const d=new DOMParser().parseFromString("
          "await r.text(),'text/html');const o=document.querySelector('details')?.open,m0=document.querySelector('.spin')?.dataset.m,"
          "s=[...document.querySelectorAll('[data-keep]')].map(x=>x.id=='out'&&end(x)?1e9:x.scrollTop);"
          "document.querySelector('main').replaceWith(d.querySelector('main'));"
          "document.querySelectorAll('.spin').forEach(sp=>{if(sp.dataset.m==m0)sp.classList.add('paused')});"
          "const n=document.querySelector('details');if(n&&o)n.open=true;"
          "document.querySelectorAll('[data-keep]').forEach((x,i)=>{x.scrollTop=s[i]||0});"
          "document.title=d.title;off.hidden=true}catch(x){off.hidden=false}},REFRESH_MS)</script>")

RISK = {"critical": "bad", "high": "w", "medium": "", "low": "z"}  # J13/17: crit red, high yellow, med white, low grey
PAGE_TITLE = "Autopilot builds your software project while you are away"  # J15: the plain-words opening
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
    """rows of (label, value) or (label, value, class); a class colours the value."""
    out = []
    for k, v, *c in rows:
        if str(v or "") != "":
            cls = f' class="{c[0]}"' if c and c[0] else ""
            out.append(f"<div><dt>{e(k)}</dt><dd{cls}>{e(str(v))}</dd></div>")
    return "<dl>" + "".join(out) + "</dl>"


def _sec(i: str, title: str, body: str) -> str:
    return f'<section id="{i}" aria-labelledby="{i}-h"><h2 id="{i}-h">{e(title)}</h2>{body}</section>'


def _tasks(tasks, other: str = "", spin=None) -> str:
    rows = []
    for t in tasks:
        st = t.get("status") or "pending"
        word, sym = WORDS.get(st, WORDS["pending"])
        cur = ' aria-current="true"' if st == "running" else ""
        risk, tries = str(t.get("risk") or "—"), t.get("tries") if t.get("tries") not in (None, "") else "—"
        model, sep, rest = str(t.get("detail", "")).partition(" · ")
        if not sep and model.endswith(" tries"):
            model, rest = "", model
        hint = f' title="{e(str(t["took"]))}"' if t.get("took") else ""
        ring = _spin(spin) if cur and spin and spin.get("kind") == "run" else ""  # W18b: the spinner starts the active row
        rows.append(f'<tr{cur}><td>{ring}{e(str(t.get("n", "")))}</td><td>{e(str(t.get("title", "")))}</td>'
                    f'<td class="st {e(st if st in WORDS else "pending")}">{sym} {word}</td>'
                    f'<td class="{"w" if t.get("slow") else ""}"{hint}>{e(str(t.get("time", "")))}</td>'
                    f'<td class="{RISK.get(risk, "")}">{e(risk)}</td>'
                    f'<td class="{"w" if _i(tries) >= 2 else ""}">{e(str(tries))}</td>'
                    f'<td><span class="bl">{e(model)}</span>{" · " if sep else ""}{e(rest)}</td></tr>')
    if other:  # J13/15: tasks + this row = Elapsed
        rows.append(f'<tr><td></td><td>Other: decide, research, docs, audit, waits</td><td></td><td>{e(other)}</td><td></td><td></td><td></td></tr>')
    head = "".join(f"<th scope=col>{h}</th>" for h in ("#", "Task", "Status", "Time", "Risk", "Tries", "Detail"))
    return f'<div class="box" data-keep tabindex="0"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _live(rows) -> str:
    if not rows:
        return "<p>No output yet.</p>"
    out = []
    for r in rows:
        k = r.get("kind") or "step"
        k = k if k in ("heading", "goal", "step", "good", "bad", "note", "blank", "wait") else "step"
        text = str(r.get("text", ""))
        body = e(text)
        if k == "step":  # J13/17: a test run is cyan; otherwise the verb is grey and what it works on stays white
            if "test" in text.lower():
                k = "step test"
            else:
                verb, sep, rest = text.partition(" ")
                body = f'<b class="v">{e(verb)}</b>{sep}{e(rest)}'
        out.append(f'<div class="l {k}"><time>{e(str(r.get("at", "")))}</time><span>{body}</span>'
                   + (f'<span class="took">{e(str(r["took"]))}</span>' if r.get("took") else "") + "</div>"
                   if k != "blank" else '<div class="l blank"></div>')
    return f'<div class="box" id="out" data-keep tabindex="0">{"".join(out)}</div>'


def _lvl(v) -> str:
    """A usage bar: magenta, yellow over 75 percent, red over 90 percent."""
    return "bad" if _v(v) > 0.9 else "warn" if _v(v) > 0.75 else "use"


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


def _asof(a) -> str:
    """J13/11: how old the data is; yellow with 'stale' over 30 s; a stopped run says when; no source is a dash."""
    if not a:
        return ""
    if a.get("stopped"):
        return f'<p class="z">stopped {e(str(a["stopped"]))}</p>'
    age = a.get("age")
    if not isinstance(age, (int, float)):
        return '<p class="z">data —</p>'
    t = f"{int(age)}s" if age < 60 else f"{int(age) // 60}m"
    return f'<p class="w">data {t} old stale</p>' if age > 30 else f'<p class="z">data {t} old</p>'


def _spin(sp) -> str:
    """J13/18: the one running indicator. A ring that turns while the data changes, frozen when stale or stopped;
    data-m is the data time, so the fetch loop can pause the ring when two fetches show the same time."""
    if not sp or sp.get("kind") not in ("run", "stale", "stopped"):
        return ""
    k, text = sp["kind"], str(sp.get("text") or "")
    ring = (f'<span class="spin {k}{"" if k == "run" else " paused"}" data-m="{e(str(sp.get("mtime")))}" role=img '
            f'aria-label="{e(text if k != "run" else "running")}"></span>')
    return ring + (f'<span class="{"w" if k == "stale" else "bad"}">{e(text)} </span>' if k != "run" else "")


def _card(data: dict) -> str:
    """W18b: the Now card, the first block under the question banner; at the end of the run the final summary."""
    c = dash_card.norm(data.get("card"), lambda x: str(x if x is not None else ""))
    if not c:
        return ""
    sp, total = data.get("spin") or {}, _i((data.get("progress") or {}).get("total"))
    clock = sp.get("clock") or None
    age = sp.get("data_age", sp.get("age"))
    age_t = (f"data {_i(age)}s" if _i(age) < 60 else f"data {_i(age) // 60}m") if age is not None else "data —"
    ring = _spin(sp)

    def txt(parts):
        return "".join(e(t) for t, _ in parts)
    if c["kind"] == "ended":
        li = "".join(f"<li>{e(x['what'])} &rarr; <code>{e(x['how'])}</code></li>" for x in c["pending"]) \
            or "<li class=z>Nothing is pending.</li>"
        t = {"green": "good", "yellow": "w", "red": "bad"}.get(c["tone"], "")
        return (f'<section id="now" class="ended" aria-labelledby="now-h"><h2 id="now-h"><span class="lab">Now</span> Run ended '
                f'<strong class="{t}">{e(c["word"])}</strong><span class="age">stopped {e(c["at"])}</span></h2>'
                f'<p>{c["done"]} of {c["total"]} tasks done &middot; {c["retries"]} retries &middot; ${c["cost"] or 0:.2f}'
                f'{" &middot; " + e(c["elapsed"]) if c["elapsed"] else ""}</p><ul>{li}</ul></section>')
    idx, frac, pct = dash_card.progress(c, clock)
    segs = []
    for i, name in enumerate(c["steps"]):
        w = round(c["weights"][i] * 100)
        if i < idx:
            segs.append(f'<span class="d" style="flex:{w}">&#10003; {e(name)}</span>')
        elif i == idx:
            segs.append(f'<span class="r" style="flex:{w};--fill:{round(frac * 100)}%"><i style="width:{round(frac * 100)}%"></i>'
                        f'<b></b><em>{e(name)}</em></span>')
        else:
            segs.append(f'<span class="n" style="flex:{w}">{e(name)}</span>')
    head = dash_card.head_text(c, total)
    title = f" &middot; <strong>{e(c['title'])}</strong>" if c["kind"] == "task" else ""
    rest = " &middot; ".join(e(x) for x in (dash_card.work_text(c, clock), dash_card.eta_text(c["eta"])) if x)
    if c["kind"] == "end":
        rest += " &middot; <span class=w>do not close</span>"
    if c.get("why"):
        rest += f' &middot; <span class="w">why: {e(c["why"])}</span>'
    return (f'<section id="now" aria-labelledby="now-h"><h2 id="now-h"><span class="lab">Now</span>{ring}{e(head)}{title}'
            f' &middot; {e(txt(dash_card.who(c)))}<span class="age {"w" if _i(age) > 30 else ""}">{e(age_t)}</span></h2>'
            f'<p>{rest}</p><div class="seg" role="img" aria-label="Steps, about {pct} percent">{"".join(segs)}</div>'
            f'<p>about {pct}%</p><p>{e(txt(dash_card.sofar(c)))}</p>'
            f'<p class="z">{e(txt(dash_card.last_line(c, clock)))}</p></section>')


def _project(p: dict, total: int, sz, asof=None, spin=None) -> str:
    tone = p.get("tone") if p.get("tone") in ("good", "wait", "bad") else ""
    st = e(str(p.get("status") or ""))
    ring = _spin(spin)
    status = (f'<div class="row"><span class="z">Status</span><span>{ring}<strong class="t-{tone}">{st}</strong></span></div>'
              if tone else f'<div class="row"><span class="z">Status</span><span>{ring}<strong>{st}</strong></span></div>'
              if st else "")
    out = (_asof(asof) + _dl([("Branch", p.get("branch"))]) + status  # 'Time left' lives in the bar
           + ("" if p.get("status") == "running" else f'<p>{e(str(p.get("state_words") or ""))}</p>')  # not "Writes the code."
           + _dl([("Start", p.get("started")), ("Elapsed", p.get("elapsed"))])
           + "".join(f'<p class="z">{e(str(p[k]))}</p>' for k in ("version", "run_line") if p.get(k)))
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
        c = "w" if m and a >= m else ""  # white, yellow on the last try
        body += f'<p class="{c}">Try {a}{f" of {m}" if m else ""}</p>'
    if nw.get("n"):
        body += _dl([("Task time", nw.get("time"))])
    body += _dl([("Model", nw.get("model"))])
    wt = dash_live.tick(p.get("wait"), None)  # W18a: what the run waits for
    body += f'<p class="z">{e(wt)}</p>' if wt and nw else ""
    out += _group("Now", body if nw else "")
    out += _group("Next", f'<p>{e(str(p["next"]))}</p>' if p.get("next") else "")
    login = str(p.get("login") or "")
    login = "not checked" if login in ("", "—") else login
    err, resets = p.get("last_error") or "—", p.get("resets") or "—"
    old = err == "—" or bool(p.get("error_old"))  # W18a: the age of the error; dim after the next successful session
    err = f'{p["error_age"]}: {err}' if err != "—" and p.get("error_age") else err
    out += _group("Agent", _dl([("Runner", p.get("runner") or "—"),
                                ("Login", login, "w" if login == "not checked" else
                                 "good" if login.lower().startswith(("pro", "max")) else "bad"),
                                ("Resets", resets, "z" if resets == "—" else "mg"),
                                ("Error", err, "z" if old else "bad")]))
    if sz:
        rows = [("Code", f'{_i(sz.get("code")):,} lines'),
                ("Tests", f'{_i(sz.get("tests")):,} lines, {_i(sz.get("test_count")):,} tests'),
                ("Docs", f'{_i(sz.get("docs")):,} lines')]
        if sz.get("run_lines") is not None:
            rows.append((f'This run ({_i(sz.get("run_tasks"))} tasks)', f'+{_i(sz["run_lines"]):,} lines', "good"))
            rows.append(("", f'{_i(sz.get("run_files")):,} files'))
        out += _group("Size", _dl(rows))
    if p.get("last_commit"):
        age = (f' <span class="{"w" if p.get("commit_stalled") else "z"}">{e(str(p["last_commit_age"]))} ago</span>'
               if p.get("last_commit_age") else "")
        out += _group("Last commit", f'<p>{e(str(p["last_commit"]))}{age}</p>')
    return out


def render(data: dict, refresh: int = 30, report_md: str = "") -> str:
    p, g, u = data.get("project") or {}, data.get("progress") or {}, data.get("usage") or {}
    tasks, health, files = data.get("tasks") or [], data.get("health") or {}, data.get("files")
    done, total, pct = _i(g.get("done")), _i(g.get("total")), _i(g.get("pct"))
    eta, active = p.get("eta") or "", _i(g.get("active"))
    card = _card(data)
    proj = _project({**p, "now": None} if card else p, total, data.get("size"), data.get("asof"), data.get("spin"))

    prog = (f'<div class="big">{pct}%</div>{_bar(pct / 100, "Progress", "ok")}'
            + (f'<div class="z">{e(str(g["word"]))}</div>' if g.get("word") else "")
            + (f'<div class="w">audit added {_i(g["audit_added"])} tasks</div>' if _i(g.get("audit_added")) else "")
            + f'<div class="row"><span>{done} done · {_i(g.get("working"))} working</span></div>'
            f'<div class="row"><span><span class="{"bad" if _i(g.get("blocked")) > 0 else ""}">{_i(g.get("blocked"))} blocked</span>'
            f' · <span class="z">{_i(g.get("waiting"))} waiting</span></span></div>'
            f'<div class="row"><span>{_i(g.get("phases_done"))} of {_i(g.get("phases_total"))} phases</span></div>')

    bars = ""
    for k, lab in (("five", "5-hour window"), ("week", "Week"), ("context", "Context")):
        if u.get(k) is not None:
            bars += (f'<div class="row"><span>{lab}</span><span class="mg">{round(_v(u[k]) * 100)}%</span></div>'
                     f'{_bar(u[k], lab, _lvl(u[k]))}')
            if k == "five" and u.get("reset_in"):
                bars += f'<div class="z">Resets in {e(str(u["reset_in"]))}</div>'
    models = "".join(f'<div class="row"><span class="bl">{e(str(m.get("name", "")))}</span>'
                     f'<span>{e(str(m.get("tokens_text", "")))} {round(_v(m.get("share")) * 100)}%</span></div>'
                     f'{_bar(m.get("share"), str(m.get("name", "")))}' for m in u.get("models") or [])
    usage = (bars + f'<div class="row"><span>Tokens</span><strong>{e(str(u.get("tokens_text") or "0"))}</strong></div>'
             + models + f'<div class="row"><span>Cost</span><strong class="mg">${float(u.get("cost") or 0):.2f}</strong></div>'
             + f'<div class="row"><span>Rate</span><span>{e(str(u.get("rate") or "—"))}</span></div>')

    bw = data.get("blocked_why") or {}
    issues = _count("Blocked tasks", g.get("blocked"), "bad")
    if bw:
        age = f'{e(str(bw["age"]))} ' if bw.get("age") else ""  # W18a: the age; grey after the next successful session
        issues += f'<div class="{"z" if bw.get("old") else "bad"}">{age}{e(str(bw.get("id", "")))}: {e(str(bw.get("why", "")))}</div>'
    issues += _count("Questions for you", g.get("questions"), "w") + _count("Gate warnings", g.get("warnings"), "w")
    issues += "".join(f'<div class="w">{e(str(x.get("id", "")))} {e(str(x.get("why", "")))}</div>'
                      for x in (g.get("warned_why") or [])[:3])
    issues += _count("Retries", g.get("retries"), "w")
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
        more = (fv("plus", "good").replace(">Plus<", ">Lines +<") + fv("minus", "bad").replace(">Minus<", ">Lines -<")
                + fv("tests", "").replace(">Tests<", ">Tests +<")) if files.get("plus") is not None else ""
        right.append(_sec("files", "Files", fv("added", "good") + fv("modified", "") + fv("deleted", "bad") + more))
    right.append(_sec("issues", "Issues", issues))
    cols = ([_sec("project", "Project", proj)],
            [_sec("tasks", "Tasks", _tasks(tasks, str(p.get("other") or ""), data.get("spin"))), _sec("live", "Live output", _live(data.get("live") or []))], right)
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
    five = u.get("five")
    bar = (f'<footer><span>{e(str(p.get("name") or ""))}</span>'
           + (f"<span>Task {active}/{total}</span>" if active > 0 else f"<span>Done {done}/{total}</span>")
           + f'<span>{_bar(pct / 100, "Progress", "ok")}{pct}%</span>'
           + (f"<span>Left{':' if str(eta).startswith('after') else ''} {e(str(eta))}</span>" if eta else "")
           + f'<span class="{"bad" if nb else "z"}">Blocked {nb}</span><span>Tok {e(str(u.get("tokens_text") or "0"))}</span>'
           f'<span>${float(u.get("cost") or 0):.2f}</span>'
           + (f"<span>5h {round(float(five) * 100)}%</span>" if isinstance(five, (int, float)) else "") + "</footer>")

    rep = f"<details><summary>Full report</summary><pre>{e(report_md)}</pre></details>" if report_md else ""
    ms = int(refresh) * 1000
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(str(data.get('line') or ''))} · {PAGE_TITLE}"
            f"{' · ' + e(str(p['version'])) if p.get('version') else ''}</title><style>{CSS}</style>"
            f"<noscript><meta http-equiv=refresh content={int(refresh)}></noscript></head><body>"
            "<p id=off hidden>The build stopped, or the status server is off. This page shows the last status. "
            "For the status now, run: ap status</p>"
            f'<main><h1>{e(str(p.get("name") or "Autopilot"))}</h1>{needs}{card}<div class="grid">{"".join(cells)}</div>'
            f"{nxt}{bar}{rep}</main>{SCRIPT.replace('REFRESH_MS', str(ms))}</body></html>")
