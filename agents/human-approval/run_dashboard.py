"""Local admin dashboard for the human-approval Skill.

A self-contained web UI (Python standard library only) where an admin reviews the
aggregated evidence per restaurant and records APPROVE / HOLD / REJECT decisions.
It reads and writes the same SQLite store via the Skill's own functions, so the
dashboard and the CLI/API stay perfectly in sync.

Binds to 127.0.0.1 only (local admin tool). All dynamic text is HTML-escaped.

Usage
-----
    python run_dashboard.py --db approval.db            # open an existing queue
    python run_dashboard.py --db approval.db --seed sources.json
    python run_dashboard.py --demo                      # seed demo data + serve

Then open http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from human_approval import ApprovalConfig, build_review_queue, get_queue, record_decision
from human_approval.errors import ApprovalError

CONFIG = ApprovalConfig(db_path="approval.db")
STATE_DIR = None  # set in main(): folder with the pipeline stage JSON outputs

_STATUS_BADGE = {
    "pending": ("PENDING", "#8a6d1f", "#fff6e0"),
    "approved": ("APPROVED", "#1f7a3d", "#e6f6ec"),
    "rejected": ("REJECTED", "#a32020", "#fdeaea"),
    "on_hold": ("ON HOLD", "#355a9a", "#e9f0fb"),
}
_VERDICT_COLOR = {"pass": "#1f7a3d", "partial": "#8a6d1f", "fail": "#a32020"}

_STYLE = """
:root {
  --bg:#f3f6fc; --card:#ffffff; --ink:#1b2230; --muted:#8a93a7; --line:#e7ecf5;
  --blue:#2f6bff; --blue-soft:#eaf1ff; --green:#17a558; --green-soft:#e7f7ee;
  --red:#e5484d; --red-soft:#fdecec; --amber:#c07f1a; --amber-soft:#fff5e3;
}
* { box-sizing:border-box; }
body { margin:0; font-family:'Segoe UI', system-ui, -apple-system, sans-serif; background:var(--bg); color:var(--ink); }
a { text-decoration:none; }
header { background:#fff; padding:22px 32px 0; border-bottom:1px solid var(--line); }
header h1 { margin:0; font-size:22px; font-weight:700; letter-spacing:-.2px; }
header .sub { color:var(--muted); font-size:14px; margin:6px 0 14px; }
.nav { display:flex; gap:6px; }
.tab { color:var(--muted); padding:11px 18px; font-size:14px; font-weight:600; border-radius:10px 10px 0 0; border:1px solid transparent; border-bottom:none; }
.tab:hover { color:var(--blue); }
.tab.active { color:var(--blue); background:var(--bg); border-color:var(--line); }
.chips { display:flex; gap:8px; flex-wrap:wrap; padding:16px 32px 0; max-width:1000px; margin:0 auto; }
.chip { background:#fff; color:var(--muted); padding:7px 14px; border-radius:999px; font-size:13px; font-weight:600; border:1px solid var(--line); }
.chip:hover { border-color:#c9d4ea; }
.chip.active { background:var(--blue); color:#fff; border-color:var(--blue); box-shadow:0 2px 8px rgba(47,107,255,.3); }
main { max-width:1000px; margin:22px auto; padding:0 32px; display:grid; gap:16px; }
main.wide { max-width:1320px; }
.card { background:var(--card); border-radius:16px; padding:22px 24px; box-shadow:0 4px 18px rgba(26,45,90,.06); border:1px solid var(--line); }
.card-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.card-head h2 { margin:0; font-size:18px; font-weight:700; }
.badge { font-size:12px; font-weight:700; padding:5px 12px; border-radius:999px; letter-spacing:.3px; }
.meta { color:#5b6475; font-size:14px; margin:10px 0; }
.meta a { color:var(--blue); font-weight:600; }
.validation { font-weight:700; margin:8px 0; }
.issues { margin:4px 0 8px; padding-left:18px; color:var(--amber); font-size:14px; }
.sample { margin:6px 0; padding-left:18px; color:#444c5e; font-size:14px; }
.rec { display:inline-block; background:var(--blue-soft); color:var(--blue); padding:5px 12px; border-radius:999px; font-size:13px; font-weight:600; margin:8px 0; }
form.decide { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:16px; border-top:1px solid var(--line); padding-top:16px; }
form.decide input { padding:10px 14px; border:1px solid #dbe2ef; border-radius:10px; font-size:14px; background:#fbfcff; }
form.decide input:focus { outline:none; border-color:var(--blue); box-shadow:0 0 0 3px var(--blue-soft); }
form.decide input[name=notes] { flex:1; min-width:170px; }
button { border:0; border-radius:10px; padding:10px 18px; font-weight:600; font-size:14px; cursor:pointer; transition:transform .05s, box-shadow .2s; }
button:hover { transform:translateY(-1px); }
button.approve { background:var(--green); color:#fff; box-shadow:0 3px 10px rgba(23,165,88,.3); }
button.hold { background:var(--blue-soft); color:var(--blue); }
button.reject { background:var(--red-soft); color:var(--red); }
.decided { color:var(--muted); font-size:13px; margin-top:12px; }
.empty { text-align:center; color:var(--muted); padding:48px; background:#fff; border-radius:16px; border:1px solid var(--line); }
footer { text-align:center; color:var(--muted); font-size:12px; padding:24px; }
/* status accent dot on queue cards */
.dot { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:8px; vertical-align:middle; }
/* pipeline stepper legend */
.stepper { display:flex; align-items:flex-start; gap:0; background:#fff; border:1px solid var(--line); border-radius:16px; padding:22px 10px; margin-bottom:18px; box-shadow:0 4px 18px rgba(26,45,90,.06); overflow-x:auto; }
.step { display:flex; flex-direction:column; align-items:center; text-align:center; min-width:120px; position:relative; }
.step .num { width:34px; height:34px; border-radius:50%; background:var(--blue); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:15px; z-index:1; box-shadow:0 2px 8px rgba(47,107,255,.3); }
.step .t { font-weight:700; font-size:13px; margin-top:8px; }
.step .d { color:var(--muted); font-size:11px; margin-top:2px; }
.step:not(:last-child)::after { content:""; position:absolute; top:17px; left:50%; width:100%; height:2px; background:var(--line); z-index:0; }
/* pipeline table */
table.pipe { width:100%; border-collapse:separate; border-spacing:0; background:#fff; border-radius:16px; overflow:hidden; border:1px solid var(--line); box-shadow:0 4px 18px rgba(26,45,90,.06); font-size:13px; }
table.pipe th, table.pipe td { padding:11px 12px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap; }
table.pipe th { background:#f7f9ff; color:#5b6475; font-weight:700; font-size:11px; text-transform:uppercase; letter-spacing:.4px; position:sticky; top:0; }
table.pipe tr:last-child td { border-bottom:none; }
table.pipe tbody tr:hover { background:#fafbff; }
table.pipe td.name { font-weight:700; white-space:normal; min-width:150px; }
.cell { display:inline-block; padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.c-good { background:var(--green-soft); color:var(--green); }
.c-warn { background:var(--amber-soft); color:var(--amber); }
.c-bad { background:var(--red-soft); color:var(--red); }
.c-none { background:#eef1f7; color:var(--muted); }
.src { font-size:10px; color:var(--muted); margin-left:5px; text-transform:uppercase; letter-spacing:.3px; }
a.cell { text-decoration:none; } a.cell:hover { text-decoration:underline; }
a.cellwrap { text-decoration:none; }
table.pipe td.name a { color:var(--ink); } table.pipe td.name a:hover { color:var(--blue); }
.sec-head { display:flex; align-items:center; gap:12px; margin-bottom:10px; }
.sec-head .num { width:30px; height:30px; border-radius:50%; background:var(--blue); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:14px; flex:0 0 auto; }
.sec-head h2 { margin:0; font-size:17px; }
.kv { margin:6px 0; font-size:14px; }
.kv .k { color:var(--muted); font-weight:600; margin-right:6px; }
.subh { font-weight:700; margin:14px 0 6px; color:#44506a; }
pre.raw { background:#f6f8fd; border:1px solid var(--line); padding:14px; border-radius:10px; max-height:320px; overflow:auto; font-size:12px; white-space:pre-wrap; color:#303a4f; }
.minitable { width:100%; border-collapse:collapse; font-size:13px; }
.minitable th, .minitable td { padding:7px 9px; border-bottom:1px solid var(--line); text-align:left; }
.minitable th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.3px; }
.notreached { color:var(--muted); font-style:italic; font-size:14px; }
.back { color:var(--blue); font-weight:600; }
.detail-link { font-size:13px; }
.dtabs { display:flex; gap:7px; flex-wrap:wrap; margin-bottom:18px; }
.dtab { display:flex; align-items:center; gap:7px; padding:9px 14px; border-radius:10px; background:#fff; border:1px solid var(--line); color:#44506a; font-weight:600; font-size:13px; cursor:pointer; }
.dtab:hover { border-color:#c9d4ea; }
.dtab.active { background:var(--blue); color:#fff; border-color:var(--blue); box-shadow:0 2px 8px rgba(47,107,255,.3); }
.dtab .dot { width:9px; height:9px; border-radius:50%; }
.dtab.active .dot { background:#fff !important; }
.secpane { display:none; }
.secpane.active { display:block; }
.scroll { overflow-x:auto; }
.searchbar { display:flex; align-items:center; gap:14px; margin:0 0 14px; }
.searchbar input { flex:1; max-width:420px; padding:11px 14px; font-size:14px; border:1px solid var(--line); border-radius:12px; background:#fff; color:var(--ink); outline:none; box-shadow:0 2px 8px rgba(26,45,90,.05); }
.searchbar input:focus { border-color:var(--blue); box-shadow:0 0 0 3px rgba(47,107,255,.15); }
.searchbar .count { color:var(--muted); font-size:13px; font-weight:600; }
.rowdecide { display:flex; gap:4px; align-items:center; white-space:nowrap; }
.rowdecide input { padding:5px 7px; font-size:12px; border:1px solid var(--line); border-radius:7px; background:#fff; color:var(--ink); width:78px; }
.rowdecide input:focus { outline:none; border-color:var(--blue); }
.rowdecide button { border:none; border-radius:7px; padding:5px 9px; font-size:13px; font-weight:700; cursor:pointer; color:#fff; line-height:1; }
.rowdecide button.approve { background:var(--green); }
.rowdecide button.hold { background:var(--amber); }
.rowdecide button.reject { background:var(--red); }
.rowdecide button:hover { filter:brightness(1.08); }
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _host(url) -> str:
    if not url:
        return ""
    return str(url).replace("https://", "").replace("http://", "")


def _card_html(it: dict) -> str:
    status = it.get("status", "pending")
    label, color, bg = _STATUS_BADGE.get(status, (status.upper(), "#555", "#eee"))
    parts = [f'<section class="card {status}">']
    parts.append('<div class="card-head">')
    parts.append(f'<h2>{_esc(it.get("restaurant_name") or it.get("restaurant_id"))}</h2>')
    parts.append(f'<span class="badge" style="color:{color};background:{bg}">{label}</span>')
    parts.append("</div>")

    website = it.get("official_website")
    meta = []
    if website:
        meta.append(f'<a href="{_esc(website)}" target="_blank" rel="noopener">{_esc(_host(website))}</a>')
    if it.get("lunch_page_url"):
        lp = it["lunch_page_url"]
        mt = f' ({_esc(it.get("menu_page_type"))})' if it.get("menu_page_type") else ""
        meta.append(f'lunch: <a href="{_esc(lp)}" target="_blank" rel="noopener">{_esc(_host(lp))}</a>{mt}')
    if it.get("scraper_version") is not None:
        rep = f' · repair: {_esc(it.get("repair_status"))}' if it.get("repair_status") else ""
        meta.append(f'scraper v{_esc(it.get("scraper_version"))}{rep}')
    if meta:
        parts.append(f'<div class="meta">{" &nbsp;·&nbsp; ".join(meta)}</div>')

    verdict = it.get("validation_verdict")
    if verdict:
        score = it.get("validation_score")
        pct = f" ({int(round(score * 100))}%)" if isinstance(score, (int, float)) else ""
        vc = _VERDICT_COLOR.get(str(verdict).lower(), "#333")
        parts.append(f'<div class="validation" style="color:{vc}">Validation: {_esc(verdict).upper()}{pct}</div>')
    issues = it.get("validation_issues") or []
    if issues:
        parts.append('<ul class="issues">' + "".join(f"<li>{_esc(i)}</li>" for i in issues) + "</ul>")

    sample = it.get("normalized_summary") or []
    if sample:
        parts.append('<ul class="sample">' + "".join(f"<li>{_esc(s)}</li>" for s in sample) + "</ul>")

    if it.get("recommendation"):
        parts.append(f'<div class="rec">Recommendation: {_esc(it.get("recommendation"))}</div>')

    rid = _esc(it.get("restaurant_id"))
    parts.append(f'<div class="meta detail-link"><a href="/restaurant?id={rid}">Full pipeline details →</a></div>')
    reviewer = _esc(it.get("reviewer") or "")
    parts.append(
        f'<form class="decide" method="post" action="/decide">'
        f'<input type="hidden" name="restaurant_id" value="{rid}">'
        f'<input name="reviewer" placeholder="Your name" value="{reviewer}">'
        f'<input name="notes" placeholder="Notes (optional)">'
        f'<button class="approve" name="decision" value="approve">Approve</button>'
        f'<button class="hold" name="decision" value="hold">Hold</button>'
        f'<button class="reject" name="decision" value="reject">Reject</button>'
        f"</form>"
    )
    if status != "pending" and (it.get("reviewer") or it.get("decided_at")):
        note = f" — {_esc(it.get('notes'))}" if it.get("notes") else ""
        parts.append(f'<div class="decided">Decided by {_esc(it.get("reviewer") or "unknown")} '
                     f'at {_esc(it.get("decided_at") or "")}{note}</div>')
    parts.append("</section>")
    return "".join(parts)


def _page(status_filter: str | None) -> str:
    items = get_queue(CONFIG)["restaurants"]
    counts = {"pending": 0, "approved": 0, "rejected": 0, "on_hold": 0}
    for it in items:
        counts[it.get("status", "pending")] = counts.get(it.get("status", "pending"), 0) + 1
    shown = [it for it in items if not status_filter or it.get("status") == status_filter]

    def chip(key, text):
        active = " active" if status_filter == key or (key == "all" and not status_filter) else ""
        href = "/" if key == "all" else f"/?status={key}"
        return f'<a class="chip{active}" href="{href}">{text}</a>'

    chips = "".join([
        chip("all", f"All {len(items)}"),
        chip("pending", f"Pending {counts['pending']}"),
        chip("approved", f"Approved {counts['approved']}"),
        chip("on_hold", f"On hold {counts['on_hold']}"),
        chip("rejected", f"Rejected {counts['rejected']}"),
    ])
    cards = "".join(_card_html(it) for it in shown) or '<div class="empty">No restaurants in this view.</div>'
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Lunch — Approval Dashboard</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<header><h1>Lunch Approval Dashboard</h1>"
        "<div class='sub'>Review the pipeline evidence and approve, hold, or reject each restaurant.</div>"
        f"{_nav('queue')}</header>"
        f"<div class='chips'>{chips}</div>"
        f"<main>{cards}</main>"
        "<footer>Nothing is auto-approved · decisions are logged · only approved restaurants are activated</footer>"
        "</body></html>"
    )


def _nav(active: str) -> str:
    tabs = [
        ("queue", "Review queue", "/"),
        ("pipeline", "Overview", "/pipeline"),
        ("discovery", "Discovery", "/stage?name=discovery"),
        ("website", "Website", "/stage?name=website"),
        ("research", "Research", "/stage?name=research"),
        ("recipe", "Recipe", "/stage?name=recipe"),
        ("scrape", "Scrape", "/stage?name=scrape"),
        ("normalize", "Normalize", "/stage?name=normalize"),
        ("approval", "Approval", "/stage?name=approval"),
    ]
    out = '<div class="nav">'
    for key, label, href in tabs:
        cls = "tab active" if key == active else "tab"
        out += f'<a class="{cls}" href="{href}">{label}</a>'
    return out + "</div>"


def _load_state(name: str) -> dict:
    if not STATE_DIR:
        return {}
    path = os.path.join(STATE_DIR, f"{name}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _index_stage(stage: dict, key: str = "restaurants", id_field: str = "restaurant_id") -> dict:
    out = {}
    for row in stage.get(key, []) or []:
        rid = str(row.get(id_field) or row.get("scraper_id") or "")
        if rid:
            out[rid] = row
    return out


def _cell(text: str, kind: str, src: str = "") -> str:
    srch = f'<span class="src">{_esc(src)}</span>' if src else ""
    return f'<span class="cell c-{kind}">{_esc(text)}</span>{srch}'


def _pipeline_page() -> str:
    disc = _load_state("discovery")
    di = _index_stage(disc)
    ri = _index_stage(_load_state("research"))
    gi = _index_stage(_load_state("generation"))
    si = _index_stage(_load_state("scraping"))
    ni = _index_stage(_load_state("normalization"))
    approvals = {}
    try:
        approvals = {it["restaurant_id"]: it for it in get_queue(CONFIG)["restaurants"]}
    except Exception:
        pass

    order = [str(r.get("restaurant_id")) for r in disc.get("restaurants", [])]
    for extra in list(ri) + list(ni):
        if extra not in order:
            order.append(extra)

    rows = []
    for rid in order:
        d = di.get(rid, {})
        name = (d.get("name") or ri.get(rid, {}).get("name")
                or ni.get(rid, {}).get("restaurant_name") or rid)

        def dl(anchor, inner):  # deep-dive link to this restaurant's detail section
            return f'<a class="cellwrap" href="/restaurant?id={_esc(rid)}#{anchor}">{inner}</a>'

        disc_cell = dl("s1", _cell(d.get("lunch_status", "—"), "good" if d else "none"))

        site = d.get("official_website")
        if site:
            dom = site.replace("https://", "").replace("http://", "").rstrip("/")
            src = "brave" if d.get("website_source") == "brave_search" else "osm"
            web_cell = (f'<a class="cell c-good" href="{_esc(site)}" target="_blank" '
                        f'rel="noopener">{_esc(dom[:28])}</a><span class="src">{src}</span>')
        else:
            web_cell = _cell("—", "none")

        r = ri.get(rid)
        if r:
            ls = r.get("lunch_status", "unknown")
            kind = {"confirmed": "good", "likely": "warn"}.get(ls, "none")
            res_cell = dl("s2", _cell(ls + (" [pg]" if r.get("lunch_page_url") else ""), kind))
        else:
            res_cell = _cell("—", "none")

        g = gi.get(rid)
        if g:
            st = g.get("status", "")
            kind = {"validated": "good", "generated": "warn", "failed": "bad"}.get(st, "none")
            rec_cell = dl("s3", _cell(f"{st} ({g.get('extracted_day_count', 0)}d)", kind))
        else:
            rec_cell = _cell("—", "none")

        s = si.get(rid)
        if s:
            st = s.get("status", "")
            kind = {"SUCCESS": "good", "PARTIAL": "warn", "NO_DATA": "warn"}.get(st, "bad")
            scr_cell = dl("s4", _cell(st, kind))
        else:
            scr_cell = _cell("—", "none")

        n = ni.get(rid)
        if n:
            st = n.get("status", "")
            kind = {"normalized": "good", "empty": "warn"}.get(st, "none")
            nor_cell = dl("s5", _cell(f"{st} ({n.get('day_count', 0)}d)", kind))
        else:
            nor_cell = _cell("—", "none")

        a = approvals.get(rid)
        if a:
            st = a.get("status", "pending")
            kind = {"approved": "good", "pending": "warn", "on_hold": "warn", "rejected": "bad"}.get(st, "none")
            app_cell = dl("s6", _cell(st, kind))
        else:
            app_cell = _cell("—", "none")

        name_html = f'<a href="/restaurant?id={_esc(rid)}">{_esc(name)}</a>'
        rows.append(
            f"<tr><td class='name'>{name_html}</td>"
            f"<td>{disc_cell}</td><td>{web_cell}</td><td>{res_cell}</td>"
            f"<td>{rec_cell}</td><td>{scr_cell}</td><td>{nor_cell}</td><td>{app_cell}</td></tr>"
        )

    if not rows:
        body = ('<div class="empty">No pipeline state found yet. Run the stepwise pipeline '
                "(pipeline/step.py) to populate this view.</div>")
    else:
        table = (
            '<div class="scroll"><table class="pipe"><thead><tr>'
            "<th>Restaurant</th><th>1 · Discovery</th><th>1b · Website</th><th>2 · Research</th>"
            "<th>3 · Recipe</th><th>4 · Scrape</th><th>5 · Normalize</th><th>6 · Approval</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )
        body = table

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Lunch — Pipeline Overview</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<header><h1>Lunch Pipeline Overview</h1>"
        "<div class='sub'>Each restaurant's journey through every stage · green = good, amber = partial, grey = not reached.</div>"
        f"{_nav('pipeline')}</header>"
        f"<main class='wide'>{body}</main>"
        "<footer>Stage data read live from pipeline/state · approval column from the review store</footer>"
        "</body></html>"
    )


def _days_table(days) -> str:
    days = days or []
    if not days:
        return "<div class='notreached'>—</div>"
    rows = []
    for dm in days:
        label = dm.get("day") or dm.get("date") or dm.get("relative") or "—"
        dishes = dm.get("dishes") or []
        if not dishes:
            rows.append(f"<tr><td>{_esc(label)}</td><td class='notreached'>(no dishes)</td><td>—</td><td></td></tr>")
        for dish in dishes:
            price = f"{dish['price']} SEK" if dish.get("price") is not None else "—"
            rows.append(f"<tr><td>{_esc(label)}</td><td>{_esc(dish.get('dish',''))}</td>"
                        f"<td>{_esc(price)}</td><td>{_esc(dish.get('dietary') or '')}</td></tr>")
            label = ""  # show the day only on its first dish row
    return ("<table class='minitable'><thead><tr><th>Day</th><th>Dish</th><th>Price</th>"
            "<th>Diet</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def _detail_page(rid: str) -> str:
    d = _index_stage(_load_state("discovery")).get(rid, {})
    r = _index_stage(_load_state("research")).get(rid, {})
    g = _index_stage(_load_state("generation")).get(rid, {})
    s = _index_stage(_load_state("scraping")).get(rid, {})
    n = _index_stage(_load_state("normalization")).get(rid, {})
    appr = {}
    try:
        appr = next((it for it in get_queue(CONFIG)["restaurants"] if it["restaurant_id"] == rid), {})
    except Exception:
        pass
    name = d.get("name") or r.get("name") or n.get("restaurant_name") or rid

    def link(url):
        return (f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(url)}</a>'
                if url else "—")

    def kv(k, v):
        return f'<div class="kv"><span class="k">{_esc(k)}</span> {v}</div>'

    def links_list(urls):
        urls = [u for u in (urls or []) if u]
        return ", ".join(link(u) for u in urls) if urls else "—"

    _STAGE_LABELS = {"s1": "1 · Discovery", "s1b": "1b · Website", "s2": "2 · Research",
                     "s3": "3 · Recipe", "s4": "4 · Scrape", "s5": "5 · Normalize", "s6": "6 · Approval"}
    tab_order = []  # (anchor, label, kind) in render order

    def section(anchor, num, title, kind, inner, status=""):
        tab_order.append((anchor, _STAGE_LABELS.get(anchor, title), kind))
        badge = f'<span class="cell c-{kind}">{_esc(status)}</span>' if status else ""
        return (f'<section class="card secpane" id="{anchor}"><div class="sec-head">'
                f'<div class="num">{num}</div><h2>{_esc(title)}</h2>{badge}</div>'
                f'<div class="sec-body">{inner}</div></section>')

    secs = []
    if d:
        inner = (kv("Lunch status", _esc(d.get("lunch_status")))
                 + kv("Address", _esc(d.get("address") or "—"))
                 + kv("Website", link(d.get("official_website")))
                 + kv("Discovery source", _esc(d.get("discovery_source_provider") or "—"))
                 + kv("Source URL", link(d.get("discovery_source_url") or d.get("source_url")))
                 + kv("Evidence", links_list(d.get("evidence_urls"))))
        secs.append(section("s1", "1", "Discovery", "good", inner, d.get("lunch_status", "")))
    else:
        secs.append(section("s1", "1", "Discovery", "none", "<div class='notreached'>No discovery record.</div>"))

    if d.get("website_source") == "brave_search":
        inner = (kv("Source", "Brave web search (fallback)")
                 + kv("Result URL", link(d.get("website_source_url")))
                 + kv("Resolved site", link(d.get("official_website"))))
        secs.append(section("s1b", "1b", "Website resolution", "good", inner, "brave"))
    elif d.get("official_website"):
        secs.append(section("s1b", "1b", "Website resolution", "good",
                            kv("Source", "OpenStreetMap tag") + kv("Site", link(d.get("official_website"))), "osm"))
    else:
        secs.append(section("s1b", "1b", "Website resolution", "none",
                            "<div class='notreached'>No website found.</div>"))

    if r:
        inner = (kv("Lunch status", _esc(r.get("lunch_status")))
                 + kv("Confidence", _esc(r.get("confidence") or "—"))
                 + kv("Menu page type", _esc(r.get("menu_page_type") or "—"))
                 + kv("Lunch page", link(r.get("lunch_page_url")))
                 + kv("Why", _esc(r.get("reason") or "—"))
                 + kv("Fetched URLs", links_list(r.get("fetched_urls")))
                 + (kv("Error", _esc(r.get("error"))) if r.get("error") else ""))
        k = {"confirmed": "good", "likely": "warn"}.get(r.get("lunch_status"), "none")
        secs.append(section("s2", "2", "Research", k, inner, r.get("lunch_status", "")))
    else:
        secs.append(section("s2", "2", "Research", "none",
                            "<div class='notreached'>Not researched (no website, or dropped).</div>"))

    if g:
        tbl = _days_table(g.get("sample_days"))
        inner = (kv("Strategy", _esc(g.get("strategy")))
                 + kv("Status", _esc(g.get("status")))
                 + kv("Weekdays detected", _esc(", ".join(g.get("weekdays_detected") or []) or "—"))
                 + kv("Has prices", "yes" if g.get("has_prices") else "no")
                 + kv("Extracted", f"{g.get('extracted_day_count', 0)} days / {g.get('extracted_dish_count', 0)} dishes")
                 + "<div class='subh'>Dry-run sample</div>" + tbl)
        k = {"validated": "good", "generated": "warn", "failed": "bad"}.get(g.get("status"), "none")
        secs.append(section("s3", "3", "Scraper recipe", k, inner, g.get("status", "")))
    else:
        secs.append(section("s3", "3", "Scraper recipe", "none",
                            "<div class='notreached'>No recipe generated.</div>"))

    if s:
        raw = (s.get("raw_content") or "")[:8000]
        inner = (kv("Status", _esc(s.get("status")))
                 + kv("HTTP", _esc(s.get("http_status") or "—"))
                 + kv("Content type", _esc(s.get("content_type") or "—"))
                 + kv("Final URL", link(s.get("final_url")))
                 + kv("Extraction", _esc(s.get("extraction_status") or "—"))
                 + kv("Attempts", _esc(s.get("attempts")))
                 + (kv("Error", _esc(s.get("error"))) if s.get("error") else "")
                 + "<div class='subh'>Raw extracted content</div>"
                 + (f"<pre class='raw'>{_esc(raw)}</pre>" if raw else "<div class='notreached'>empty</div>"))
        k = {"SUCCESS": "good", "NO_DATA": "warn", "PARTIAL": "warn"}.get(s.get("status"), "bad")
        secs.append(section("s4", "4", "Scraping (raw)", k, inner, s.get("status", "")))
    else:
        secs.append(section("s4", "4", "Scraping (raw)", "none",
                            "<div class='notreached'>Not scraped.</div>"))

    if n:
        inner = (kv("Status", _esc(n.get("status")))
                 + kv("Lunch period", _esc(n.get("lunch_period") or "—"))
                 + kv("Lunch hours", _esc(n.get("lunch_hours") or "—"))
                 + kv("Additional info", _esc("; ".join(n.get("additional_info") or []) or "—"))
                 + kv("Method", _esc(n.get("method") or "—"))
                 + kv("Confidence", _esc(n.get("confidence") or "—"))
                 + "<div class='subh'>Structured menu</div>" + _days_table(n.get("days")))
        k = {"normalized": "good", "empty": "warn"}.get(n.get("status"), "none")
        secs.append(section("s5", "5", "Normalized menu", k, inner, n.get("status", "")))
    else:
        secs.append(section("s5", "5", "Normalized menu", "none",
                            "<div class='notreached'>Not normalized.</div>"))

    if appr:
        inner = (kv("Status", _esc(appr.get("status")))
                 + kv("Recommendation", _esc(appr.get("recommendation") or "—"))
                 + kv("Reviewer", _esc(appr.get("reviewer") or "—"))
                 + kv("Notes", _esc(appr.get("notes") or "—"))
                 + kv("Decided at", _esc(appr.get("decided_at") or "—")))
        k = {"approved": "good", "pending": "warn", "on_hold": "warn", "rejected": "bad"}.get(appr.get("status"), "none")
        secs.append(section("s6", "6", "Approval", k, inner, appr.get("status", "")))
    else:
        secs.append(section("s6", "6", "Approval", "none",
                            "<div class='notreached'>Not in review queue.</div>"))

    tabs = '<div class="dtabs">' + "".join(
        f'<a class="dtab" data-sec="{a}" href="#{a}"><span class="dot c-{k}"></span>{_esc(lbl)}</a>'
        for a, lbl, k in tab_order) + "</div>"

    script = (
        "<script>(function(){"
        "var tabs=document.querySelectorAll('.dtab');"
        "var panes=document.querySelectorAll('.secpane');"
        "function act(id){"
        "panes.forEach(function(p){p.classList.toggle('active',p.id===id);});"
        "tabs.forEach(function(t){t.classList.toggle('active',t.dataset.sec===id);});}"
        "tabs.forEach(function(t){t.addEventListener('click',function(e){e.preventDefault();"
        "history.replaceState(null,'','#'+t.dataset.sec);act(t.dataset.sec);});});"
        "var ids=Array.prototype.map.call(panes,function(p){return p.id;});"
        "var h=location.hash.slice(1);act(ids.indexOf(h)>=0?h:ids[0]);"
        "})();</script>"
    )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(name)} — Pipeline Detail</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<header><h1>{_esc(name)}</h1>"
        "<div class='sub'><a class='back' href='/pipeline'>← back to overview</a> · full pipeline detail</div>"
        f"{_nav('pipeline')}</header>"
        f"<main>{tabs}{''.join(secs)}</main>"
        "<footer>Every stage's full output for this restaurant</footer>"
        f"{script}</body></html>"
    )


def _stage_page(name: str) -> str:
    labels = {"discovery": "Discovery", "website": "Website resolution", "research": "Research",
              "recipe": "Scraper recipe", "scrape": "Scraping (raw)", "normalize": "Normalized menu",
              "approval": "Approval"}
    label = labels.get(name, name)

    def namecell(rid, nm):
        return f'<a href="/restaurant?id={_esc(rid)}">{_esc(nm or rid)}</a>'

    def ext(url, text=None):
        return (f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(text or _host(url))}</a>'
                if url else "—")

    headers, rows = [], []

    if name == "approval":
        try:
            items = get_queue(CONFIG)["restaurants"]
        except Exception:
            items = []
        headers = ["Restaurant", "Status", "Recommendation", "Notes", "Actions"]
        for it in items:
            st = it.get("status", "pending")
            k = {"approved": "good", "pending": "warn", "on_hold": "warn", "rejected": "bad"}.get(st, "none")
            rid = _esc(it.get("restaurant_id"))
            reviewer = _esc(it.get("reviewer") or "")
            form = (
                f'<form class="rowdecide" method="post" action="/decide">'
                f'<input type="hidden" name="restaurant_id" value="{rid}">'
                f'<input name="reviewer" placeholder="You" value="{reviewer}">'
                f'<input name="notes" placeholder="Comment">'
                f'<button class="approve" name="decision" value="approve" title="Approve">✓</button>'
                f'<button class="hold" name="decision" value="hold" title="Hold">⏸</button>'
                f'<button class="reject" name="decision" value="reject" title="Reject">✗</button>'
                f"</form>"
            )
            rows.append([namecell(it.get("restaurant_id"), it.get("restaurant_name")),
                         _cell(st, k), _esc(it.get("recommendation") or "—"),
                         _esc(it.get("notes") or "—"), form])
    else:
        file = {"discovery": "discovery", "website": "discovery", "research": "research",
                "recipe": "generation", "scrape": "scraping", "normalize": "normalization"}[name]
        recs = _load_state(file).get("restaurants", []) or []
        for x in recs:
            rid = str(x.get("restaurant_id") or "")
            nm = x.get("name") or x.get("restaurant_name") or rid
            nc = namecell(rid, nm)
            site = x.get("official_website")
            if name == "discovery":
                headers = ["Restaurant", "Lunch status", "Address", "Website", "Source"]
                src = "brave" if x.get("website_source") == "brave_search" else ("osm" if site else "—")
                rows.append([nc, _cell(x.get("lunch_status", "—"), "good"),
                             _esc(x.get("address") or "—"), ext(site), src])
            elif name == "website":
                headers = ["Restaurant", "Website", "Source", "Found via"]
                src = "brave" if x.get("website_source") == "brave_search" else ("osm" if site else "—")
                wl = ext(site) if site else '<span class="notreached">none found</span>'
                rows.append([nc, wl, src, ext(x.get("website_source_url"), "search result")])
            elif name == "research":
                headers = ["Restaurant", "Lunch status", "Confidence", "Menu type", "Lunch page"]
                ls = x.get("lunch_status", "unknown")
                k = {"confirmed": "good", "likely": "warn"}.get(ls, "none")
                rows.append([nc, _cell(ls, k), _esc(x.get("confidence") or "—"),
                             _esc(x.get("menu_page_type") or "—"), ext(x.get("lunch_page_url"))])
            elif name == "recipe":
                headers = ["Restaurant", "Status", "Strategy", "Days", "Dishes", "Sample"]
                st = x.get("status", "")
                k = {"validated": "good", "generated": "warn", "failed": "bad"}.get(st, "none")
                sd = x.get("sample_days") or []
                sample = ""
                if sd and sd[0].get("dishes"):
                    sample = f"{sd[0].get('day', '')}: {sd[0]['dishes'][0].get('dish', '')[:34]}"
                rows.append([nc, _cell(st, k), _esc(x.get("strategy")), str(x.get("extracted_day_count", 0)),
                             str(x.get("extracted_dish_count", 0)), _esc(sample or "—")])
            elif name == "scrape":
                headers = ["Restaurant", "Status", "HTTP", "Type", "Raw snippet"]
                st = x.get("status", "")
                k = {"SUCCESS": "good", "NO_DATA": "warn", "PARTIAL": "warn"}.get(st, "bad")
                snip = " ".join((x.get("raw_content") or "").split())[:70]
                rows.append([nc, _cell(st, k), _esc(x.get("http_status") or "—"),
                             _esc(x.get("content_type") or "—"), _esc(snip or "—")])
            elif name == "normalize":
                headers = ["Restaurant", "Status", "Hours", "Days", "Dishes", "First dish"]
                st = x.get("status", "")
                k = {"normalized": "good", "empty": "warn"}.get(st, "none")
                days = x.get("days") or []
                first = ""
                if days and days[0].get("dishes"):
                    lbl = days[0].get("day") or days[0].get("date") or ""
                    first = f"{lbl}: {days[0]['dishes'][0].get('dish', '')[:34]}"
                rows.append([nc, _cell(st, k), _esc(x.get("lunch_hours") or "—"),
                             str(x.get("day_count", 0)), str(x.get("item_count", 0)), _esc(first or "—")])

    if not rows:
        body = ('<div class="empty">No data for this stage yet. '
                "Run the step (pipeline/step.py) to populate it.</div>")
    else:
        head = "".join(f"<th>{h}</th>" for h in headers)
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        search = (
            '<div class="searchbar">'
            f'<input id="stageSearch" type="search" placeholder="Search {_esc(label.lower())}… '
            'name, status, text" autocomplete="off" oninput="filterStage()">'
            f'<span id="stageCount" class="count">{len(rows)} restaurants</span>'
            "</div>"
        )
        body = (f'{search}<div class="scroll"><table class="pipe" id="stageTable"><thead><tr>{head}</tr></thead>'
                f"<tbody>{trs}</tbody></table></div>")

    script = (
        "<script>function filterStage(){"
        "var q=document.getElementById('stageSearch').value.toLowerCase().trim();"
        "var rows=document.querySelectorAll('#stageTable tbody tr');var n=0;"
        "rows.forEach(function(r){var show=!q||r.textContent.toLowerCase().indexOf(q)>-1;"
        "r.style.display=show?'':'none';if(show)n++;});"
        "var c=document.getElementById('stageCount');"
        "c.textContent=n+(n===1?' restaurant':' restaurants')+(q?' (filtered)':'');}</script>"
    ) if rows else ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(label)} — Lunch Pipeline</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<header><h1>{_esc(label)}</h1>"
        f"<div class='sub'>All restaurants at the <b>{_esc(label)}</b> stage · click a name for the full detail.</div>"
        f"{_nav(name)}</header>"
        f"<main class='wide'>{body}</main>"
        "<footer>Stage data read live from pipeline/state</footer>"
        f"{script}</body></html>"
    )


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/pipeline":
            try:
                self._send(200, _pipeline_page())
            except Exception as exc:
                self._send(500, f"<pre>{_esc(exc)}</pre>")
            return
        if parsed.path == "/restaurant":
            rid = parse_qs(parsed.query).get("id", [""])[0]
            try:
                self._send(200, _detail_page(rid))
            except Exception as exc:
                self._send(500, f"<pre>{_esc(exc)}</pre>")
            return
        if parsed.path == "/stage":
            name = parse_qs(parsed.query).get("name", ["discovery"])[0]
            try:
                self._send(200, _stage_page(name))
            except Exception as exc:
                self._send(500, f"<pre>{_esc(exc)}</pre>")
            return
        if parsed.path not in ("/", "/index.html"):
            self._send(404, "<h1>Not found</h1>")
            return
        status = parse_qs(parsed.query).get("status", [None])[0]
        try:
            self._send(200, _page(status))
        except Exception as exc:  # never crash the server on a render error
            self._send(500, f"<pre>{_esc(exc)}</pre>")

    def do_POST(self):
        if urlparse(self.path).path != "/decide":
            self._send(404, "<h1>Not found</h1>")
            return
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        rid = (fields.get("restaurant_id") or [""])[0]
        decision = (fields.get("decision") or [""])[0]
        reviewer = (fields.get("reviewer") or [""])[0]
        notes = (fields.get("notes") or [""])[0]
        try:
            record_decision(rid, decision, reviewer=reviewer, notes=notes, config=CONFIG)
        except ApprovalError:
            pass  # ignore invalid submissions; just re-render
        self.send_response(303)
        self.send_header("Location", self.headers.get("Referer") or "/")
        self.end_headers()

    def log_message(self, *args):  # quieter console
        return


def _demo_sources():
    return {
        "discovery": {"restaurants": [
            {"restaurant_id": "gowri", "name": "Gowri", "city": "Göteborg", "official_website": "https://gowrirestaurang.se"},
            {"restaurant_id": "manfreds", "name": "Manfred's Brasserie", "city": "Göteborg", "official_website": "https://manfreds.com"},
            {"restaurant_id": "pizzalacasa", "name": "Pizza La Casa", "city": "Göteborg", "official_website": "https://pizzalacasa.se"}]},
        "research": {"restaurants": [
            {"restaurant_id": "gowri", "lunch_page_url": "https://gowrirestaurang.se/lunch", "menu_page_type": "html"},
            {"restaurant_id": "manfreds", "lunch_page_url": "https://manfreds.com", "menu_page_type": "html"}]},
        "scraping": {"restaurants": [
            {"restaurant_id": "gowri", "status": "SUCCESS", "scraper_version": 4},
            {"restaurant_id": "manfreds", "status": "SUCCESS", "scraper_version": 1},
            {"restaurant_id": "pizzalacasa", "status": "SCRAPE_FAILED", "scraper_version": 2}]},
        "normalization": {"restaurants": [
            {"restaurant_id": "gowri", "restaurant_name": "Gowri", "status": "normalized",
             "days": [{"day": "Måndag", "dishes": [{"dish": "Chicken curry", "price": 120}]},
                      {"day": "Tisdag", "dishes": [{"dish": "Fish masala", "price": 129}]}]},
            {"restaurant_id": "manfreds", "restaurant_name": "Manfred's Brasserie", "status": "normalized",
             "days": [{"day": "Måndag", "dishes": [{"dish": "Kalvschnitzel", "price": 145}]}]}]},
        "validation": {"restaurants": [
            {"restaurant_id": "gowri", "restaurant_name": "Gowri", "verdict": "partial", "score": 0.75,
             "missing_days": ["Onsdag"], "price_mismatches": 1},
            {"restaurant_id": "manfreds", "restaurant_name": "Manfred's Brasserie", "verdict": "pass", "score": 1.0,
             "missing_days": [], "price_mismatches": 0}]},
        "repair": {"scrapers": [
            {"scraper_id": "gowri", "diagnosis": "wrong_content", "status": "repaired", "new_version": 4},
            {"scraper_id": "pizzalacasa", "diagnosis": "selector_no_match", "status": "no_fix_found", "new_version": 2}]},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Admin dashboard for human-approval.")
    parser.add_argument("--db", default="approval.db", help="SQLite approval store path")
    parser.add_argument("--seed", help="Build the queue from an aggregated sources JSON")
    parser.add_argument("--demo", action="store_true", help="Seed demo data and serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--state", help="Folder with pipeline stage JSON (default: <db dir>/state)")
    args = parser.parse_args(argv)

    global STATE_DIR
    CONFIG.db_path = args.db
    STATE_DIR = args.state or os.path.join(os.path.dirname(os.path.abspath(args.db)), "state")
    if args.demo:
        build_review_queue(_demo_sources(), config=CONFIG)
    elif args.seed:
        with open(args.seed, "r", encoding="utf-8") as f:
            build_review_queue(json.load(f), config=CONFIG)
    else:
        # Ensure the store exists even if empty.
        get_queue(CONFIG)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Approval dashboard running at {url}  (db: {args.db})")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
