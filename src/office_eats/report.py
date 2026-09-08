"""Render a Result as a terminal table, Markdown, HTML or JSON."""
from __future__ import annotations

import html
import json

from .models import osm_link
from .recommend import Result
from .scoring import PROFILES

OPEN = {True: "yes", False: "no", None: "?"}


def safe_url(url: str | None) -> str | None:
    """Only ever link http(s): OSM tags are user-editable and could hold javascript: URLs."""
    if url and url.strip().lower().startswith(("http://", "https://")):
        return url.strip()
    return None


def _price(v) -> str:
    """'$$' when the price came from a provider/tag/brand, '~$$' when it is only a heuristic guess."""
    if not v.price_level:
        return "?"
    return ("~" if v.price_source == "guess" else "") + "$" * v.price_level


def _row(i: int, s) -> list[str]:
    v = s.venue
    return [str(i), f"{s.score:.0f}", v.name, v.kind, ", ".join(v.cuisine[:2]) or "-", f"{v.walk_min:.0f}m",
            _price(v), "/".join(sorted(v.diets)) or "-", OPEN[v.open_now]]


HEAD = ["#", "Score", "Name", "Kind", "Cuisine", "Walk", "$", "Diet", "Open"]


def _title(r: Result) -> str:
    return f"{PROFILES[r.query.use_case].label} near {r.place.name}"


def table(r: Result) -> str:
    rows = [HEAD] + [_row(i, s) for i, s in enumerate(r.items, 1)]
    rows = [[c if len(c) <= 32 else c[:31] + "…" for c in row] for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEAD))]
    fmt = lambda row: "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip()  # noqa: E731
    lines = [_title(r), f"{r.place.address or f'{r.place.lat:.5f},{r.place.lon:.5f}'}  ({r.candidates} candidates, walk: {r.walk_source})", "",
             fmt(rows[0]), fmt(["-" * w for w in widths])] + [fmt(row) for row in rows[1:]]
    if not r.items:
        lines.append("(no matches: try a larger radius or fewer constraints)")
    return "\n".join(lines)


def markdown(r: Result) -> str:
    out = [f"# {_title(r)}", "", f"Office: {r.place.address or r.place.name} "
           f"([map](https://www.openstreetmap.org/?mlat={r.place.lat:.6f}&mlon={r.place.lon:.6f}#map=17/{r.place.lat:.6f}/{r.place.lon:.6f}))",
           f"Candidates considered: {r.candidates}. Blurbs: {r.blurb_source}. Walking times: {r.walk_source}.", ""]
    if r.query.diets:
        out.insert(3, f"Dietary filter: {', '.join(sorted(r.query.diets))}")
    if r.query.when:
        out.insert(3, f"Visit time: {r.query.when:%a %Y-%m-%d %H:%M} ({r.timezone or 'local time'})")
    for i, s in enumerate(r.items, 1):
        v = s.venue
        md_name = v.name.replace("[", "\\[").replace("]", "\\]")
        out.append(f"## {i}. {md_name} ({s.score:.0f}/100)")
        out.append(f"- {v.kind}, {', '.join(v.cuisine) or 'cuisine unknown'}, {_price(v)}, "
                   f"{v.walk_min:.0f} min walk ({v.distance_m:.0f} m)")
        if wc := v.tags.get("wheelchair"):
            out.append(f"- Wheelchair access (OSM): {wc}")
        if v.opening_hours:
            out.append(f"- Hours: `{v.opening_hours}` (open for the visit: {OPEN[v.open_now]})")
        links = [f"[OpenStreetMap]({osm_link(v)})"]
        if site := safe_url(v.website):
            links.append(f"[website](<{site}>)")
        if menu := safe_url(v.menu_url):
            links.append(f"[menu](<{menu}>)")
        out.append("- " + " · ".join(links))
        out.append(f"- Why: {s.blurb or '; '.join(s.reasons)}")
        out.append("")
    out.append("Prices marked ~ are guesses from cuisine and venue type. Data © OpenStreetMap contributors, ODbL 1.0.")
    return "\n".join(out)


def to_html(r: Result) -> str:
    e = html.escape
    rows = []
    for i, s in enumerate(r.items, 1):
        v = s.venue
        links = [f'<a href="{e(osm_link(v))}">map</a>']
        if site := safe_url(v.website):
            links.append(f'<a href="{e(site)}" rel="nofollow">site</a>')
        if menu := safe_url(v.menu_url):
            links.append(f'<a href="{e(menu)}" rel="nofollow">menu</a>')
        rows.append(
            f"<tr><td>{i}</td><td>{s.score:.0f}</td><td><strong>{e(v.name)}</strong><br><small>{e(s.blurb or '; '.join(s.reasons))}</small></td>"
            f"<td>{e(', '.join(v.cuisine[:3]) or v.kind)}</td><td>{v.walk_min:.0f} min</td><td>{_price(v)}</td>"
            f"<td>{e('/'.join(sorted(v.diets)) or '-')}</td><td>{OPEN[v.open_now]}</td><td>{' · '.join(links)}</td></tr>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(_title(r))}</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 1rem;color:#1d1d1f;background:#fff}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:.5rem;border-bottom:1px solid #ddd;vertical-align:top}}
small{{color:#555}}a{{color:#0b57d0}}
@media (prefers-color-scheme:dark){{body{{background:#161617;color:#eee}}small{{color:#aaa}}td,th{{border-color:#333}}a{{color:#8ab4f8}}}}
</style></head><body>
<h1>{e(_title(r))}</h1>
<p>{e(r.place.address or r.place.name)} · {r.candidates} candidates · blurbs: {e(r.blurb_source)} · walking: {e(r.walk_source)}</p>
<table><thead><tr><th>#</th><th>Score</th><th>Place</th><th>Cuisine</th><th>Walk</th><th>$</th><th>Diet</th><th>Open</th><th>Links</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table>
<p><small>Data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, ODbL 1.0.</small></p>
</body></html>
"""


LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist/leaflet"
LEAFLET_SRI = {"css": "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=", "js": "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="}


def to_map(r: Result) -> str:
    """One HTML file: Leaflet from a CDN (pinned + SRI), OSM tiles with attribution, numbered markers."""
    e = html.escape
    data = {"office": {"name": r.place.name, "lat": r.place.lat, "lon": r.place.lon},
            "venues": [{"n": i, "name": s.venue.name, "lat": s.venue.lat, "lon": s.venue.lon, "score": round(s.score),
                        "walk": round(s.venue.walk_min), "price": _price(s.venue), "why": s.blurb or "; ".join(s.reasons),
                        "osm": osm_link(s.venue), "site": safe_url(s.venue.website)} for i, s in enumerate(r.items, 1)]}
    # Venue names are crowd-sourced: "</" is escaped so no name can close the script tag, and the page
    # builds popups with textContent, never innerHTML.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(_title(r))}</title>
<link rel="stylesheet" href="{LEAFLET}.css" integrity="{LEAFLET_SRI['css']}" crossorigin="">
<script src="{LEAFLET}.js" integrity="{LEAFLET_SRI['js']}" crossorigin=""></script>
<style>
html,body{{height:100%;margin:0;font:14px/1.4 system-ui,sans-serif}}#map{{height:calc(100% - 3rem)}}
header{{height:3rem;display:flex;align-items:center;padding:0 1rem;gap:.75rem;background:#fff;color:#1d1d1f;border-bottom:1px solid #ddd}}
header h1{{font-size:1rem;margin:0}}.pin{{background:#0b57d0;color:#fff;border-radius:50%;text-align:center;font-weight:600;line-height:24px}}
.pin.office{{background:#c5221f}}
@media (prefers-color-scheme:dark){{header{{background:#161617;color:#eee;border-color:#333}}}}
</style></head><body>
<header><h1>{e(_title(r))}</h1><small>{len(r.items)} picks · walking: {e(r.walk_source)}</small></header>
<div id="map"></div>
<script>
const data = {blob};
const map = L.map("map");
L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}}).addTo(map);
const icon = (text, cls) => L.divIcon({{className: "pin " + cls, html: text, iconSize: [24, 24]}});
function popup(v) {{
  const div = document.createElement("div");
  const add = (tag, text) => {{ const el = document.createElement(tag); el.textContent = text; div.appendChild(el); return el; }};
  add("strong", v.n ? v.n + ". " + v.name : v.name);
  if (v.n) {{
    add("div", v.score + "/100 · " + v.walk + " min walk · " + v.price);
    add("div", v.why);
    const links = add("div", "");
    for (const [label, url] of [["OpenStreetMap", v.osm], ["website", v.site]]) {{
      if (!url) continue;
      const a = document.createElement("a"); a.href = url; a.textContent = label; a.rel = "nofollow noopener"; a.target = "_blank";
      links.append(links.childNodes.length ? " · " : "", a);
    }}
  }}
  return div;
}}
const points = [[data.office.lat, data.office.lon]];
L.marker(points[0], {{icon: icon("★", "office"), title: data.office.name}}).bindPopup(popup(data.office)).addTo(map);
for (const v of data.venues) {{
  L.marker([v.lat, v.lon], {{icon: icon(String(v.n), ""), title: v.name}}).bindPopup(popup(v)).addTo(map);
  points.push([v.lat, v.lon]);
}}
map.fitBounds(points, {{padding: [30, 30], maxZoom: 17}});
</script>
</body></html>
"""


def to_json(r: Result) -> str:
    return json.dumps(r.to_dict(), indent=2, ensure_ascii=False)


FORMATS = {"table": table, "md": markdown, "html": to_html, "json": to_json, "map": to_map}
