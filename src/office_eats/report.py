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


def _price(level: int | None) -> str:
    return "$" * level if level else "?"


def _row(i: int, s) -> list[str]:
    v = s.venue
    return [str(i), f"{s.score:.0f}", v.name, v.kind, ", ".join(v.cuisine[:2]) or "-", f"{v.walk_min:.0f}m",
            _price(v.price_level), "/".join(sorted(v.diets)) or "-", OPEN[v.open_now]]


HEAD = ["#", "Score", "Name", "Kind", "Cuisine", "Walk", "$", "Diet", "Open"]


def _title(r: Result) -> str:
    return f"{PROFILES[r.query.use_case].label} near {r.place.name}"


def table(r: Result) -> str:
    rows = [HEAD] + [_row(i, s) for i, s in enumerate(r.items, 1)]
    rows = [[c if len(c) <= 32 else c[:31] + "…" for c in row] for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(len(HEAD))]
    fmt = lambda row: "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip()  # noqa: E731
    lines = [_title(r), f"{r.place.address or f'{r.place.lat:.5f},{r.place.lon:.5f}'}  ({r.candidates} candidates)", "",
             fmt(rows[0]), fmt(["-" * w for w in widths])] + [fmt(row) for row in rows[1:]]
    if not r.items:
        lines.append("(no matches: try a larger radius or fewer constraints)")
    return "\n".join(lines)


def markdown(r: Result) -> str:
    out = [f"# {_title(r)}", "", f"Office: {r.place.address or r.place.name} "
           f"([map](https://www.openstreetmap.org/?mlat={r.place.lat:.6f}&mlon={r.place.lon:.6f}#map=17/{r.place.lat:.6f}/{r.place.lon:.6f}))",
           f"Candidates considered: {r.candidates}. Blurbs: {r.blurb_source}.", ""]
    if r.query.diets:
        out.insert(3, f"Dietary filter: {', '.join(sorted(r.query.diets))}")
    for i, s in enumerate(r.items, 1):
        v = s.venue
        md_name = v.name.replace("[", "\\[").replace("]", "\\]")
        out.append(f"## {i}. {md_name} ({s.score:.0f}/100)")
        out.append(f"- {v.kind}, {', '.join(v.cuisine) or 'cuisine unknown'}, {_price(v.price_level)}, "
                   f"{v.walk_min:.0f} min walk ({v.distance_m:.0f} m)")
        if v.opening_hours:
            out.append(f"- Hours: `{v.opening_hours}` (open at requested time: {OPEN[v.open_now]})")
        links = [f"[OpenStreetMap]({osm_link(v)})"]
        if site := safe_url(v.website):
            links.append(f"[website](<{site}>)")
        if menu := safe_url(v.menu_url):
            links.append(f"[menu](<{menu}>)")
        out.append("- " + " · ".join(links))
        out.append(f"- Why: {s.blurb or '; '.join(s.reasons)}")
        out.append("")
    out.append("Data © OpenStreetMap contributors, ODbL 1.0.")
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
            f"<td>{e(', '.join(v.cuisine[:3]) or v.kind)}</td><td>{v.walk_min:.0f} min</td><td>{_price(v.price_level)}</td>"
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
<p>{e(r.place.address or r.place.name)} · {r.candidates} candidates · blurbs: {e(r.blurb_source)}</p>
<table><thead><tr><th>#</th><th>Score</th><th>Place</th><th>Cuisine</th><th>Walk</th><th>$</th><th>Diet</th><th>Open</th><th>Links</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table>
<p><small>Data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, ODbL 1.0.</small></p>
</body></html>
"""


def to_json(r: Result) -> str:
    return json.dumps(r.to_dict(), indent=2, ensure_ascii=False)


FORMATS = {"table": table, "md": markdown, "html": to_html, "json": to_json}
