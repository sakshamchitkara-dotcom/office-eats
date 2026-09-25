"""Find menu links on a restaurant's own website, honouring robots.txt (RFC 9309)."""
from __future__ import annotations

import urllib.parse
import urllib.robotparser
from html.parser import HTMLParser

from .http import Http, HttpError, user_agent
from .models import Venue

MENU_WORDS = ("menu", "carta", "speisekarte", "order")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def robots_allows(url: str, http: Http) -> bool:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        text = http.fetch(robots_url, parse_json=False, ttl=86400)
    except HttpError as e:
        # RFC 9309: 4xx means no restrictions; unreachable/5xx means assume full disallow.
        return e.status is not None and 400 <= e.status < 500
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp.can_fetch(user_agent(), url)


def find_menu_link(html: str, base: str) -> str | None:
    p = _Links()
    p.feed(html)
    best = None
    for href, text in p.links:
        hay = f"{href} {text}".lower()
        if href.startswith(("mailto:", "tel:", "javascript:")) or not any(w in hay for w in MENU_WORDS):
            continue
        link = urllib.parse.urljoin(base, href)
        if "menu" in hay:  # prefer an explicit menu over a generic "order" link
            return link
        best = best or link
    return best


def add_menu_links(venues: list[Venue], http: Http, limit: int = 5) -> None:
    """Best effort: only the first `limit` venues with a website and no known menu link."""
    todo = [v for v in venues if v.website and not v.menu_url][:limit]
    for v in todo:
        url = v.website if "://" in v.website else f"https://{v.website}"
        if urllib.parse.urlsplit(url).scheme not in ("http", "https") or not robots_allows(url, http):
            continue
        try:
            html = http.fetch(url, parse_json=False, ttl=7 * 86400)
        except HttpError:
            continue
        v.menu_url = find_menu_link(html, url)
