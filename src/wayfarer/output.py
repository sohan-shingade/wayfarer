"""Persist a planning run to disk as files (the saveable trip items) plus a
self-contained HTML viewer with a map.

Idempotency: the run directory name is derived from a hash of the structured
brief, so re-running the SAME scenario writes to the SAME directory and overwrites
its contents instead of piling up timestamped duplicates. Combined with the
persistent provider cache (same cached flights/hotels within TTL), an identical
request reproduces the same files.

Layout (per run):
  runs/<month>_<vibe>_<pax>pax_<hash>/
    run.json                  brief + metadata
    summary.md                ranked index of all options
    plan-01-<dest>.json       machine-readable Plan
    plan-01-<dest>.md         human itinerary
    index.html                visual viewer (cards + Leaflet map)

This module is pure output: it never calls the LLM or providers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Brief, Plan
from .text import scenario_id, slugify


def _scenario_dirname(brief: Brief) -> str:
    canonical = json.dumps({
        "pax": brief.pax,
        "budget_total": brief.budget_total,
        "origins": sorted(brief.origins or [brief.origin_iata]),
        "month": brief.month,
        "nights": brief.nights,
        "vibe": sorted(brief.vibe),
        "long_haul_ok": brief.long_haul_ok,
        "hard_ceiling": brief.hard_ceiling,
    }, sort_keys=True)
    vibe = slugify("-".join(brief.vibe) or "trip", 24)
    return f"{brief.month}_{vibe}_{brief.pax}pax_{scenario_id(canonical)}"


def _plan_md(i: int, plan: Plan) -> str:
    b = plan.budget
    lines = [
        f"# {i}. {plan.destination}",
        "",
        f"**Status:** {plan.status}  ",
        f"**Dates:** {plan.out_date} → {plan.back_date}  ",
        f"**From:** {plan.origin or '?'}",
        "",
        "## Budget",
        "",
        "| Item | Cost |",
        "| --- | ---: |",
        f"| Flights | ${b.flights:,.0f} |",
        f"| Lodging | ${b.lodging:,.0f} |",
        f"| Per-diem | ${b.per_diem:,.0f} |",
        f"| Buffer | ${b.buffer:,.0f} |",
        f"| **Total** | **${b.total:,.0f}** |",
        "",
        "## Flight",
        "",
        f"Party total: **${plan.flight.price_total:,.0f}**  ",
    ]
    if plan.flight.book_url:
        lines.append(f"[Book / view flights]({plan.flight.book_url})  ")
    for label, legs in (("Outbound", plan.flight.legs_out), ("Return", plan.flight.legs_back)):
        if legs:
            lines.append(f"\n*{label}:*")
            for leg in legs:
                lines.append(
                    f"- {leg.carrier}{leg.flight_number} "
                    f"{leg.depart_airport}→{leg.arrive_airport} "
                    f"{leg.depart_dt} → {leg.arrive_dt}"
                )
    h = plan.hotel
    lines += [
        "",
        "## Hotel",
        "",
        f"**{h.name}** — ${h.nightly_rate:,.0f}/night × {h.nights} = ${h.total:,.0f} all-in",
    ]
    if h.book_url:
        lines.append(f"[Book hotel]({h.book_url})")
    lines += ["", "## Itinerary", ""]
    for d in plan.itinerary:
        lines.append(f"### Day {d.day}: {d.title}")
        lines.append("")
        lines.append(d.notes)
        lines.append("")
    if plan.critic_notes:
        lines += ["## Reviewer notes", "", plan.critic_notes, ""]
    lines += ["---", "", plan.summary, ""]
    return "\n".join(lines)


def _summary_md(brief: Brief, plans: list[Plan]) -> str:
    lines = [
        "# Trip options",
        "",
        f"**{brief.pax} travelers** · budget **${brief.budget_total:,.0f}** · "
        f"**{brief.nights} nights** in **{brief.month}** · "
        f"from **{', '.join(brief.origins or [brief.origin_iata])}**  ",
        f"Vibe: {', '.join(brief.vibe) or '—'}",
        "",
        "| # | Destination | From | Dates | Total | Deal | Status |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for i, p in enumerate(plans, 1):
        slug = slugify(p.destination)
        deal = "🔥" if p.is_deal else ""
        lines.append(
            f"| {i} | [{p.destination}](plan-{i:02d}-{slug}.md) | {p.origin or '?'} | "
            f"{p.out_date}→{p.back_date} | ${p.budget.total:,.0f} | {deal} | {p.status} |"
        )
    lines += ["", "Open `index.html` for the visual map view.", ""]
    return "\n".join(lines)


def write_run(plans: list[Plan], brief: Brief, out_root: str | Path = "runs") -> Path:
    run_dir = Path(out_root) / _scenario_dirname(brief)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Idempotent: clear prior generated files so a re-run with fewer plans doesn't
    # leave stale ones behind.
    for old in run_dir.glob("plan-*"):
        old.unlink()
    for name in ("summary.md", "index.html", "run.json"):
        p = run_dir / name
        if p.exists():
            p.unlink()

    (run_dir / "run.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief.model_dump(),
        "plan_count": len(plans),
    }, indent=2), encoding="utf-8")

    for i, plan in enumerate(plans, 1):
        slug = slugify(plan.destination)
        (run_dir / f"plan-{i:02d}-{slug}.json").write_text(
            plan.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / f"plan-{i:02d}-{slug}.md").write_text(
            _plan_md(i, plan), encoding="utf-8")
        # Per-candidate activity viewer: walk the itinerary stop-by-stop on a map.
        (run_dir / f"plan-{i:02d}-{slug}.html").write_text(
            _activity_viewer_html(i, plan), encoding="utf-8")

    (run_dir / "summary.md").write_text(_summary_md(brief, plans), encoding="utf-8")
    (run_dir / "index.html").write_text(_viewer_html(brief, plans), encoding="utf-8")
    return run_dir


def _viewer_html(brief: Brief, plans: list[Plan]) -> str:
    out = []
    for i, p in enumerate(plans, 1):
        d = p.model_dump()
        d["activity_url"] = f"plan-{i:02d}-{slugify(p.destination)}.html"
        out.append(d)
    data = {"brief": brief.model_dump(), "plans": out}
    payload = json.dumps(data).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__DATA__", payload)


def _activity_viewer_html(i: int, plan: Plan) -> str:
    """Self-contained page that walks one trip's itinerary stop-by-stop on a map:
    numbered markers in visit order, a route line connecting them, and a
    Prev/Next stepper that flies the map to each activity."""
    stops = []
    for d in plan.itinerary:
        for s in (d.stops or []):
            stops.append({
                "day": d.day, "day_title": d.title,
                "name": s.name, "note": s.note, "lat": s.lat, "lng": s.lng,
                "start": s.start, "end": s.end,
            })
    def _legs(legs):
        return [{"carrier": L.carrier, "flight_number": L.flight_number,
                 "from": L.depart_airport, "to": L.arrive_airport,
                 "dep": L.depart_dt, "arr": L.arrive_dt} for L in legs]
    h = plan.hotel
    data = {
        "title": f"{i}. {plan.destination}",
        "origin": plan.origin, "out_date": plan.out_date, "back_date": plan.back_date,
        "summary": plan.summary, "critic_notes": plan.critic_notes,
        "hotel": {"name": h.name, "lat": h.lat, "lng": h.lng, "nightly": h.nightly_rate,
                  "nights": h.nights, "total": h.total, "book_url": h.book_url},
        "flight": {"price": plan.flight.price_total, "book_url": plan.flight.book_url,
                   "out": _legs(plan.flight.legs_out), "back": _legs(plan.flight.legs_back)},
        "budget": plan.budget.model_dump(),
        "stops": stops,
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return _ACTIVITY_TEMPLATE.replace("__DATA__", payload)


_ACTIVITY_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wayfarer · activity map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  :root { --bg:#0d1117; --panel:#161b22; --line:#27303b; --ink:#e6edf3; --mut:#8b949e; --accent:#3fb950; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--ink); }
  header { padding:16px 24px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:18px; }
  header .meta { color:var(--mut); font-size:13px; }
  header a { color:#58a6ff; font-size:13px; text-decoration:none; }
  .ctrls { display:flex; gap:8px; align-items:center; }
  .ctrls button { background:var(--panel); color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:6px 12px; cursor:pointer; font-size:14px; }
  .ctrls button:hover { border-color:var(--accent); }
  .ctrls .pos { color:var(--mut); font-size:13px; min-width:64px; text-align:center; }
  .wrap { display:grid; grid-template-columns:minmax(320px,420px) 1fr; height:calc(100vh - 62px); }
  #list { overflow-y:auto; padding:12px; }
  #map { height:100%; background:#0a0e14; }
  .logi { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:10px; }
  .logi h2 { margin:0 0 8px; font-size:16px; }
  .logi .sub { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.5px; margin:12px 0 4px; }
  .bars { display:flex; height:9px; border-radius:5px; overflow:hidden; margin:6px 0; }
  .bars span { display:block; }
  .b-flights{background:#388bfd}.b-lodging{background:#a371f7}.b-per_diem{background:#3fb950}.b-buffer{background:#484f58}
  table.cost { width:100%; border-collapse:collapse; font-size:13px; }
  table.cost td { padding:3px 0; color:var(--mut); }
  table.cost td.v { text-align:right; color:var(--ink); font-variant-numeric:tabular-nums; }
  table.cost tr.tot td { border-top:1px solid var(--line); padding-top:6px; color:var(--ink); font-weight:600; font-size:15px; }
  .leg { font-size:13px; color:var(--mut); margin:2px 0; font-variant-numeric:tabular-nums; }
  .leg b { color:var(--ink); }
  .logi .links { display:flex; gap:14px; font-size:13px; margin-top:8px; }
  .logi a { color:#58a6ff; text-decoration:none; }
  .crit { color:var(--warn); font-size:12px; margin-top:8px; }
  .dayhdr { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.6px; margin:14px 6px 6px; }
  .stop { background:var(--panel); border:1px solid var(--line); border-left:3px solid var(--line); border-radius:10px; padding:10px 12px; margin-bottom:8px; cursor:pointer; display:flex; gap:10px; transition:border-color .15s; }
  .stop:hover { border-color:var(--accent); }
  .stop.active { border-color:var(--accent); border-left-color:var(--accent); background:#11261a; }
  .stop .n { flex:0 0 26px; height:26px; border-radius:50%; background:#1f6feb; color:#fff; font-size:13px; font-weight:600; display:flex; align-items:center; justify-content:center; }
  .stop.active .n { background:var(--accent); }
  .stop h3 { margin:0; font-size:15px; }
  .stop p { margin:2px 0 0; color:var(--mut); font-size:13px; }
  .stop .time { display:inline-block; margin:2px 0 0; font-size:12px; color:var(--accent); font-variant-numeric:tabular-nums; }
  .stop .body { flex:1; }
  .pin { background:#1f6feb; color:#fff; border:2px solid #fff; border-radius:50% 50% 50% 0; width:26px; height:26px; transform:rotate(-45deg); display:flex; align-items:center; justify-content:center; box-shadow:0 1px 4px rgba(0,0,0,.5); }
  .pin b { transform:rotate(45deg); font-size:12px; }
  .pin.active { background:var(--accent); }
  .pin.hotel { background:#a371f7; border-radius:6px; }
  @media (max-width:820px){ .wrap{grid-template-columns:1fr; height:auto;} #map{height:50vh;} }
</style>
</head>
<body>
<header>
  <div><h1 id="title"></h1><div class="meta" id="meta"></div></div>
  <div class="ctrls">
    <button id="prev">‹ Prev</button><span class="pos" id="pos"></span><button id="next">Next ›</button>
    <a href="index.html">↩ all trips</a>
  </div>
</header>
<div class="wrap"><div id="list"></div><div id="map"></div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const DATA = __DATA__;
const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const sched = s => s.start && s.end ? `${s.start} – ${s.end}` : (s.start || s.end || "");
const ttime = iso => { if(!iso) return ""; const m=String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if(!m) return iso; const MO=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  let h=+m[4], ap=h<12?"AM":"PM"; h=h%12||12; return `${MO[+m[2]-1]} ${+m[3]} ${h}:${m[5]} ${ap}`; };
document.getElementById("title").textContent = DATA.title;
document.getElementById("meta").textContent =
  [DATA.origin?("from "+DATA.origin):"", (DATA.out_date&&DATA.back_date)?`${DATA.out_date} → ${DATA.back_date}`:"", `${DATA.stops.length} stops`].filter(Boolean).join(" · ");

const map = L.map("map", { scrollWheelZoom:true });
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  { attribution:'© OpenStreetMap, © CARTO', maxZoom:19 }).addTo(map);

const icon = (label, cls) => L.divIcon({ className:"", html:`<div class="pin ${cls}"><b>${label}</b></div>`, iconSize:[26,26], iconAnchor:[13,26], popupAnchor:[0,-24] });
const list = document.getElementById("list"), pts = [], markers = [];
let cur = 0, lastDay = null;
const fmt = n => "$" + Math.round(n).toLocaleString();

// ---- logistics + cost breakdown card ----
(function(){
  const bd = DATA.budget, F = DATA.flight, H = DATA.hotel;
  const parts = ["flights","lodging","per_diem","buffer"], labels = {flights:"Flights",lodging:"Lodging",per_diem:"Food / per-diem",buffer:"Car + buffer"};
  const tot = Math.max(1, parts.reduce((a,k)=>a+(bd[k]||0),0));
  const segs = parts.map(k=>`<span class="b-${k}" style="width:${(bd[k]/tot)*100}%"></span>`).join("");
  const rows = parts.map(k=>`<tr><td><span style="color:var(--ink)">${labels[k]}</span></td><td class="v">${fmt(bd[k]||0)}</td></tr>`).join("");
  const legHtml = (legs)=>legs.map(l=>`<div class="leg"><b>${esc(l.carrier)}${esc(l.flight_number)}</b> ${esc(l.from)}→${esc(l.to)} · ${esc(ttime(l.dep))} → ${esc(ttime(l.arr))}</div>`).join("") || `<div class="leg">—</div>`;
  const fl = F.book_url?`<a href="${F.book_url}" target="_blank" rel="noopener">flights ↗</a>`:"";
  const hl = H.book_url?`<a href="${H.book_url}" target="_blank" rel="noopener">hotel ↗</a>`:"";
  const el = document.createElement("div"); el.className="logi";
  el.innerHTML = `
    <h2>Logistics & cost</h2>
    <div class="bars">${segs}</div>
    <table class="cost">${rows}<tr class="tot"><td>Total</td><td class="v">${fmt(bd.total)}</td></tr></table>
    <div class="sub">✈ Flight · ${fmt(F.price)} party total</div>
    <div><b style="font-size:13px">Out</b></div>${legHtml(F.out)}
    <div style="margin-top:4px"><b style="font-size:13px">Back</b></div>${legHtml(F.back)}
    <div class="sub">🛏 Hotel</div>
    <div class="leg"><b>${esc(H.name)}</b> · ${fmt(H.nightly)}/nt × ${H.nights} = ${fmt(H.total)}</div>
    <div class="links">${fl}${hl}</div>
    ${DATA.summary?`<div class="leg" style="margin-top:8px">${esc(DATA.summary)}</div>`:""}
    ${DATA.critic_notes?`<div class="crit">⚠ ${esc(DATA.critic_notes)}</div>`:""}`;
  list.appendChild(el);
})();

DATA.stops.forEach((s, i) => {
  if (s.day !== lastDay) {
    const h = document.createElement("div"); h.className = "dayhdr";
    h.textContent = `Day ${s.day} · ${s.day_title||""}`; list.appendChild(h); lastDay = s.day;
  }
  const el = document.createElement("div"); el.className = "stop"; el.id = "stop-"+i;
  const tspan = sched(s) ? `<span class="time">🕑 ${esc(sched(s))}</span><br>` : "";
  el.innerHTML = `<div class="n">${i+1}</div><div class="body"><h3>${esc(s.name)}</h3>${tspan}${s.note?`<p>${esc(s.note)}</p>`:""}</div>`;
  el.addEventListener("click", () => go(i)); list.appendChild(el);
  const m = L.marker([s.lat, s.lng], { icon: icon(i+1, "") }).addTo(map)
    .bindPopup(`<b>${i+1}. ${esc(s.name)}</b><br>Day ${s.day}${sched(s)?" · "+esc(sched(s)):""}${s.note?"<br>"+esc(s.note):""}`);
  m.on("click", () => go(i)); markers.push(m); pts.push([s.lat, s.lng]);
});

if (typeof DATA.hotel.lat === "number" && typeof DATA.hotel.lng === "number")
  L.marker([DATA.hotel.lat, DATA.hotel.lng], { icon: icon("🛏", "hotel") }).addTo(map)
    .bindPopup(`<b>🛏 ${esc(DATA.hotel.name)}</b><br>your base`);

if (pts.length > 1) L.polyline(pts, { color:"#1f6feb", weight:2.5, opacity:.6, dashArray:"6 6" }).addTo(map);
if (pts.length) map.fitBounds(pts, { padding:[60,60], maxZoom:13 }); else map.setView([20,0],2);

function go(i){
  if (i<0 || i>=DATA.stops.length) return;
  cur = i;
  markers.forEach((m,j)=>m.setIcon(icon(j+1, j===i?"active":"")));
  document.querySelectorAll(".stop").forEach(c=>c.classList.remove("active"));
  const c = document.getElementById("stop-"+i);
  if (c){ c.classList.add("active"); c.scrollIntoView({behavior:"smooth", block:"nearest"}); }
  markers[i].openPopup();
  map.flyTo(pts[i], Math.max(map.getZoom(), 12), { duration:.6 });
  document.getElementById("pos").textContent = `${i+1} / ${DATA.stops.length}`;
}
document.getElementById("prev").onclick = ()=>go(cur-1);
document.getElementById("next").onclick = ()=>go(cur+1);
document.addEventListener("keydown", e=>{ if(e.key==="ArrowLeft")go(cur-1); if(e.key==="ArrowRight")go(cur+1); });
if (DATA.stops.length) go(0);
</script>
</body>
</html>
"""


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wayfarer · trip options</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  :root { --bg:#0d1117; --panel:#161b22; --line:#27303b; --ink:#e6edf3; --mut:#8b949e; --accent:#3fb950; --warn:#d29922; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--ink); }
  header { padding:20px 24px; border-bottom:1px solid var(--line); }
  header h1 { margin:0 0 4px; font-size:20px; letter-spacing:.3px; }
  header .meta { color:var(--mut); font-size:13px; }
  .wrap { display:grid; grid-template-columns:minmax(360px,1fr) 1.1fr; gap:0; height:calc(100vh - 70px); }
  #list { overflow-y:auto; padding:16px; }
  #map { height:100%; background:#0a0e14; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:14px; transition:border-color .15s; }
  .card:hover, .card.active { border-color:var(--accent); }
  .card h2 { margin:0 0 6px; font-size:17px; }
  .row { display:flex; flex-wrap:wrap; gap:10px; align-items:baseline; color:var(--mut); font-size:13px; margin-bottom:10px; }
  .total { color:var(--ink); font-weight:600; font-size:16px; }
  .pill { font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); }
  .pill.ok { color:var(--accent); border-color:var(--accent); }
  .pill.flagged, .pill.over_budget { color:var(--warn); border-color:var(--warn); }
  .pill.deal { color:#ff7b72; border-color:#ff7b72; }
  .bars { display:flex; height:8px; border-radius:4px; overflow:hidden; margin:8px 0 12px; }
  .bars span { display:block; }
  .b-flights{background:#388bfd}.b-lodging{background:#a371f7}.b-per_diem{background:#3fb950}.b-buffer{background:#484f58}
  .legend { display:flex; gap:12px; flex-wrap:wrap; font-size:11px; color:var(--mut); margin-bottom:10px; }
  .legend i { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:4px; vertical-align:middle; }
  .summary { color:var(--mut); font-size:13px; margin:6px 0 10px; }
  details { border-top:1px solid var(--line); padding-top:8px; }
  details summary { cursor:pointer; color:var(--mut); font-size:13px; }
  .day { margin:8px 0; }
  .day b { color:var(--ink); }
  .day p { margin:2px 0 0; color:var(--mut); font-size:13px; }
  a { color:#58a6ff; }
  .links { display:flex; gap:14px; font-size:13px; margin-top:6px; }
  @media (max-width:820px){ .wrap{grid-template-columns:1fr; height:auto;} #map{height:340px;} }
</style>
</head>
<body>
<header>
  <h1>wayfarer · trip options</h1>
  <div class="meta" id="meta"></div>
</header>
<div class="wrap">
  <div id="list"></div>
  <div id="map"></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const DATA = __DATA__;
const fmt = n => "$" + Math.round(n).toLocaleString();
const b = DATA.brief;
document.getElementById("meta").textContent =
  `${b.pax} travelers · ${fmt(b.budget_total)} · ${b.nights} nights · ${b.month} · from ${(b.origins||[b.origin_iata]).join(", ")} · ${(b.vibe||[]).join(", ")}`;

const map = L.map("map", { scrollWheelZoom:true });
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution:'© OpenStreetMap, © CARTO', maxZoom:19
}).addTo(map);

const list = document.getElementById("list");
const markers = [], bounds = [];

DATA.plans.forEach((p, i) => {
  const bd = p.budget, parts = ["flights","lodging","per_diem","buffer"];
  const card = document.createElement("div");
  card.className = "card"; card.id = "card-"+i;
  const segs = parts.map(k => `<span class="b-${k}" style="width:${(bd[k]/bd_total(bd))*100}%"></span>`).join("");
  const days = (p.itinerary||[]).map(d => `<div class="day"><b>Day ${d.day}: ${esc(d.title)}</b><p>${esc(d.notes)}</p></div>`).join("");
  const flightLink = p.flight.book_url ? `<a href="${p.flight.book_url}" target="_blank" rel="noopener">flights ↗</a>` : "";
  const hotelLink = p.hotel.book_url ? `<a href="${p.hotel.book_url}" target="_blank" rel="noopener">hotel ↗</a>` : "";
  const stopCount = (p.itinerary||[]).reduce((n,d)=>n+((d.stops||[]).length),0);
  const actLink = (p.activity_url && stopCount) ? `<a href="${p.activity_url}">🗺 activity map (${stopCount}) ↗</a>` : "";
  card.innerHTML = `
    <h2>${i+1}. ${esc(p.destination)} <span class="pill ${p.status}">${p.status}</span>${p.is_deal ? ' <span class="pill deal">🔥 deal</span>' : ''}</h2>
    <div class="row"><span class="total">${fmt(bd.total)}</span>
      <span>from ${esc(p.origin||"?")}</span><span>${p.out_date} → ${p.back_date}</span></div>
    <div class="bars">${segs}</div>
    <div class="legend">
      <span><i class="b-flights"></i>flights ${fmt(bd.flights)}</span>
      <span><i class="b-lodging"></i>lodging ${fmt(bd.lodging)}</span>
      <span><i class="b-per_diem"></i>per-diem ${fmt(bd.per_diem)}</span>
      <span><i class="b-buffer"></i>buffer ${fmt(bd.buffer)}</span>
    </div>
    <div class="summary">${esc(p.summary||"")}</div>
    <div><b>${esc(p.hotel.name)}</b> · ${fmt(p.hotel.nightly_rate)}/nt × ${p.hotel.nights}</div>
    <div class="links">${flightLink}${hotelLink}${actLink}</div>
    <details><summary>${(p.itinerary||[]).length}-day itinerary</summary>${days}</details>`;
  card.addEventListener("click", () => { if (markers[i]) markers[i].openPopup(); focusCard(i); });
  list.appendChild(card);

  const lat = p.hotel.lat, lng = p.hotel.lng;
  if (typeof lat === "number" && typeof lng === "number") {
    const m = L.marker([lat, lng]).addTo(map)
      .bindPopup(`<b>${i+1}. ${esc(p.destination)}</b><br>${fmt(bd.total)} · ${esc(p.hotel.name)}`);
    m.on("click", () => focusCard(i));
    markers[i] = m; bounds.push([lat, lng]);
  }
});

function bd_total(bd){ return Math.max(1, bd.flights+bd.lodging+bd.per_diem+bd.buffer); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function focusCard(i){ document.querySelectorAll(".card").forEach(c=>c.classList.remove("active"));
  const c=document.getElementById("card-"+i); if(c){ c.classList.add("active"); c.scrollIntoView({behavior:"smooth",block:"nearest"}); } }

if (bounds.length) map.fitBounds(bounds, { padding:[50,50], maxZoom:6 });
else map.setView([20, 0], 2);
</script>
</body>
</html>
"""
