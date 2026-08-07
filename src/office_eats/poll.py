"""Team lunch polls: shortlist -> poll options, and the poll as text or a Slack Block Kit message with vote buttons."""
from __future__ import annotations

import html

from .models import osm_link
from .recommend import Result
from .slack import esc
from .store import Store

VOTE_ACTION = "office_eats_vote"


def create_from_result(store: Store, r: Result, title: str | None = None) -> str:
    options = [{"id": s.venue.id, "name": s.venue.name, "url": osm_link(s.venue), "walk_min": round(s.venue.walk_min, 1),
                "blurb": s.blurb or "; ".join(s.reasons)} for s in r.items]
    return store.create_poll(title or f"Where should we eat near {r.place.name}?", options)


def _ordered(poll: dict, rows: list) -> list[tuple[int, dict, list[str]]]:
    """Tally rows back in ballot order (1..n), so buttons don't jump around as votes come in."""
    votes = {o["id"]: v for o, v in rows}
    return [(i, o, votes[o["id"]]) for i, o in enumerate(poll["options"])]


def to_text(store: Store, poll_id: str) -> str:
    poll, rows = store.tally(poll_id)
    lines = [f"{poll['title']}  (poll {poll_id}{', closed' if poll['closed'] else ''})"]
    for i, o, voters in _ordered(poll, rows):
        lines.append(f"{i + 1}. {o['name']}  [{len(voters)}]  {o['walk_min']:.0f} min walk" + (f"  - {', '.join(voters)}" if voters else ""))
    top = rows[0]
    if top[1] and (len(rows) == 1 or len(top[1]) > len(rows[1][1])):
        lines.append(f"Leading: {top[0]['name']}")
    return "\n".join(lines)


def to_slack(store: Store, poll_id: str) -> dict:
    poll, rows = store.tally(poll_id)
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": poll["title"][:150]}}]
    for i, o, voters in _ordered(poll, rows):
        section = {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{i + 1}. <{o['url']}|{esc(o['name'])}>*  ·  {o['walk_min']:.0f} min walk  ·  *{len(voters)}* vote{'s' * (len(voters) != 1)}\n"
            f"{esc(o['blurb'])}")[:3000]}}
        if not poll["closed"]:
            section["accessory"] = {"type": "button", "text": {"type": "plain_text", "text": "Vote"},
                                    "action_id": f"{VOTE_ACTION}_{i}", "value": f"{poll_id}:{i}"}
        blocks.append(section)
        if voters:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": esc(", ".join(voters))[:2000]}]})
    status = "Poll closed." if poll["closed"] else "One vote each; click another option to change yours."
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"{status} · Data © OpenStreetMap contributors, ODbL"}]})
    return {"text": poll["title"], "blocks": blocks[:50]}


def parse_vote_value(value: str) -> tuple[str, int]:
    poll_id, _, choice = value.rpartition(":")
    if not poll_id or not choice.isdigit():
        raise ValueError(f"bad vote value {value!r}")
    return poll_id, int(choice)


def to_html(store: Store, poll_id: str, message: str = "") -> str:
    """A plain voting page for teams without Slack: one form, no JavaScript, works on a phone."""
    e = html.escape
    poll, rows = store.tally(poll_id)
    items = []
    for i, o, voters in _ordered(poll, rows):
        radio = "" if poll["closed"] else f'<input type="radio" name="choice" value="{i}" id="o{i}" required> '
        who = f'<br><small>{e(", ".join(voters))}</small>' if voters else ""
        items.append(f'<li><label for="o{i}">{radio}<strong>{e(o["name"])}</strong> · {o["walk_min"]:.0f} min walk · '
                     f'{len(voters)} vote{"s" * (len(voters) != 1)}</label> <a href="{e(o["url"])}">map</a>'
                     f'<br><small>{e(o["blurb"])}</small>{who}</li>')
    form = ("<p><strong>Poll closed.</strong></p>" if poll["closed"] else
            '<p><label for="voter">Your name</label><br><input id="voter" name="voter" maxlength="80" required autocomplete="name"></p>'
            "<p><button>Vote</button> <small>One vote each; voting again changes yours.</small></p>")
    note = f'<p role="status"><strong>{e(message)}</strong></p>' if message else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(poll["title"])}</title>
<style>
:root{{color-scheme:light dark}}body{{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}}
ol{{padding-left:1.2rem}}li{{margin:.8rem 0}}small{{opacity:.75}}input[name=voter]{{font:inherit;padding:.4rem;width:100%;max-width:20rem}}
button{{font:inherit;padding:.4rem 1.2rem}}
</style></head><body>
<h1>{e(poll["title"])}</h1>{note}
<form method="post" action="/poll/{e(poll_id)}"><ol>
{chr(10).join(items)}
</ol>{form}</form>
<p><small>Data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>, ODbL 1.0.</small></p>
</body></html>
"""
