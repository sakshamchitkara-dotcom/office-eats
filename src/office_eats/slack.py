"""Slack Block Kit formatting, incoming-webhook posting."""
from __future__ import annotations

import json
import os
import urllib.request

from .http import user_agent
from .models import osm_link
from .recommend import Result
from .report import safe_url
from .scoring import PROFILES


def esc(text: str) -> str:
    """Slack mrkdwn escaping (venue names are untrusted and could contain <!channel>)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_slack(r: Result) -> dict:
    title = f"{PROFILES[r.query.use_case].label} near {r.place.name}"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": esc(
            f"{r.candidates} candidates · blurbs: {r.blurb_source}"
            + (f" · diet: {', '.join(sorted(r.query.diets))}" if r.query.diets else ""))}]},
    ]
    for i, s in enumerate(r.items, 1):
        v = s.venue
        links = [f"<{osm_link(v)}|map>"]
        if site := safe_url(v.website):
            links.append(f"<{site}|site>")
        if menu := safe_url(v.menu_url):
            links.append(f"<{menu}|menu>")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*{i}. {esc(v.name)}*  ·  {s.score:.0f}/100  ·  {v.walk_min:.0f} min walk\n"
            f"{esc(s.blurb or '; '.join(s.reasons))}\n{' · '.join(links)}")[:3000]}})
    if not r.items:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No matches. Try a bigger radius or fewer filters._"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Data © OpenStreetMap contributors, ODbL"}]})
    return {"text": title, "blocks": blocks[:50]}  # Slack caps messages at 50 blocks


def post_webhook(payload: dict, url: str | None = None) -> None:
    url = url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url.startswith("https://hooks.slack.com/"):
        raise ValueError("SLACK_WEBHOOK_URL must be an https://hooks.slack.com/ URL")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": user_agent()})
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()
