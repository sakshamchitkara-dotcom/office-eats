"""Slack endpoints: POST /slack/command (e.g. `/eats dinner party:6 diet:vegan 415 Mission St, SF`)
and POST /slack/interact (Interactivity Request URL: vote buttons on polls).

Slack wants an answer within 3 s, and Overpass can be slower, so we ack immediately and
post the real answer to the request's response_url from a worker thread.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cache import Cache
from .cli import parse_diets
from .http import Http
from .recommend import Query, recommend
from .poll import VOTE_ACTION, parse_vote_value
from .poll import to_html as poll_to_html
from .poll import to_slack as poll_to_slack
from .scoring import PROFILES
from .slack import post_webhook, to_slack
from .store import Store, StoreError
from .routing import ENGINES as ROUTING_ENGINES
from .tz import office_tz, parse_when

USAGE = ("Usage: `/eats [lunch|dinner|catering|coffee] [diet:vegan,halal] [party:8] [at:fri_19:00] "
         "[walk:10] [route:osrm] [tz:Europe/London] <address or lat,lon>`")
MAX_BODY = 16 * 1024
POLL_PATH = re.compile(r"^/poll/([0-9a-f]{8})$")


def verify(secret: str, timestamp: str, body: bytes, signature: str, now: float | None = None) -> bool:
    try:
        if abs((now or time.time()) - int(timestamp)) > 300:  # replay protection
            return False
    except ValueError:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_command(text: str) -> Query:
    words, opts, rest = text.split(), {}, []
    for w in words:
        k, sep, v = w.partition(":")
        if sep and k.lower() in ("diet", "party", "at", "walk", "n", "route", "tz") and v:
            opts[k.lower()] = v
        else:
            rest.append(w)
    use_case = "lunch"
    if rest and rest[0].lower() in PROFILES:
        use_case = rest.pop(0).lower()
    if not rest:
        raise ValueError(USAGE)
    at = opts["at"].replace("_", " ") if "at" in opts else None
    parse_when(at)  # fail fast on a bad time; the office's local clock is applied later in recommend()
    route = opts.get("route", "none")
    if route not in ROUTING_ENGINES:
        raise ValueError(f"route must be one of {', '.join(ROUTING_ENGINES)}")
    if "tz" in opts:
        office_tz(0, 0, override=opts["tz"])  # validates the name
    party, n = _number(opts, "party", int, 0, 200), _number(opts, "n", int, 1, 10)
    walk = _number(opts, "walk", float, 1, 60)
    return Query(" ".join(rest), use_case=use_case, diets=parse_diets(opts.get("diet")),
                 party=party or 0, at=at, routing=route, tz=opts.get("tz"), max_walk=walk, limit=n or 5)


def _number(opts: dict, key: str, kind: type, lo: float, hi: float):
    """A numeric option within [lo, hi], or None when absent; anything else is a readable error."""
    if key not in opts:
        return None
    try:
        value = kind(opts[key])
    except ValueError:
        value = None
    if value is None or not lo <= value <= hi:
        raise ValueError(f"{key}: must be a number from {lo:g} to {hi:g}, got {opts[key]!r}")
    return value


def make_handler(secret: str | None, http: Http, worker=threading.Thread, store: Store | None = None, slack: bool = True):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, code: int, page: str, headers: dict | None = None) -> None:
            body = page.encode()
            self.send_response(code)
            for k, v in {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)),
                         "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
                         "X-Frame-Options": "DENY",
                         # same-origin, not no-referrer: with no-referrer browsers send "Origin: null" on the vote form.
                         "Referrer-Policy": "same-origin", **(headers or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/healthz":
                return self._send(200, {"ok": True})
            if (m := POLL_PATH.match(path)) and store is not None:
                try:
                    return self._send_html(200, poll_to_html(store, m[1], "Vote counted." if query == "voted=1" else ""))
                except StoreError:
                    pass
            self._send(404, {"error": "not found"})

        def _web_vote(self, poll_id: str, body: bytes) -> None:
            """Form POST from the voting page. No Slack signature here, so refuse cross-site posts instead."""
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
                return self._send(403, {"error": "cross-site vote refused"})
            form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8", "replace")).items()}
            try:
                if not form.get("choice", "").isdigit():
                    raise StoreError("pick one of the options")
                store.vote(poll_id, form.get("voter", ""), int(form["choice"]))
            except StoreError as e:
                try:
                    return self._send_html(400, poll_to_html(store, poll_id, f"Vote not counted: {e}"))
                except StoreError:
                    return self._send(404, {"error": "not found"})
            # Post/Redirect/Get, so a reload doesn't resubmit the form.
            self._send_html(303, "", {"Location": f"/poll/{poll_id}?voted=1"})

        def do_POST(self):
            poll_match = POLL_PATH.match(self.path) if store is not None else None
            if not (slack and self.path in ("/slack/command", "/slack/interact")) and not poll_match:
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            body = self.rfile.read(length)
            if poll_match:
                return self._web_vote(poll_match[1], body)
            if secret is not None and not verify(secret, self.headers.get("X-Slack-Request-Timestamp", ""), body,
                                                 self.headers.get("X-Slack-Signature", "")):
                return self._send(401, {"error": "bad signature"})
            form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()}
            if self.path == "/slack/interact":
                return self._interact(form)
            try:
                q = parse_command(form.get("text", ""))
            except ValueError as e:
                return self._send(200, {"response_type": "ephemeral", "text": str(e)})
            worker(target=self._answer, args=(q, form.get("response_url", "")), daemon=True).start()
            self._send(200, {"response_type": "ephemeral", "text": f"Looking for {PROFILES[q.use_case].label.lower()} spots near {q.location}…"})

        def _answer(self, q: Query, response_url: str) -> None:
            try:
                payload = {"response_type": "in_channel", **to_slack(recommend(q, http))}
            except Exception as e:  # report every failure back to the user instead of dying silently
                payload = {"response_type": "ephemeral", "text": f"Sorry, that failed: {e}"}
            try:
                post_webhook(payload, response_url)
            except Exception as e:
                print(f"office-eats: could not reply to Slack: {e}", file=sys.stderr)

        def _interact(self, form: dict) -> None:
            """Vote button click: record it, then redraw the poll in place via response_url."""
            try:
                payload = json.loads(form.get("payload", "{}"))
                action = next(a for a in payload.get("actions", []) if a.get("action_id", "").startswith(VOTE_ACTION))
                poll_id, choice = parse_vote_value(action["value"])
                user = payload.get("user") or {}
                voter = user.get("username") or user.get("name") or user["id"]
            except (ValueError, KeyError, StopIteration, TypeError):
                return self._send(400, {"error": "unsupported interaction"})
            if store is None:
                return self._send(503, {"error": "polls are not enabled"})
            try:
                store.vote(poll_id, voter, choice)
                reply = {"replace_original": True, **poll_to_slack(store, poll_id)}
            except StoreError as e:
                reply = {"response_type": "ephemeral", "replace_original": False, "text": f"Vote not counted: {e}"}
            self._send(200, {})  # Slack only needs a fast 200; the redraw goes to response_url
            worker(target=self._reply, args=(reply, payload.get("response_url", "")), daemon=True).start()

        def _reply(self, payload: dict, response_url: str) -> None:
            try:
                post_webhook(payload, response_url)
            except Exception as e:
                print(f"office-eats: could not reply to Slack: {e}", file=sys.stderr)

        def log_message(self, fmt, *args):
            sys.stderr.write("office-eats: " + fmt % args + "\n")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8080, insecure: bool = False, web_only: bool = False) -> None:
    secret = os.environ.get("SLACK_SIGNING_SECRET")
    if not secret and not insecure and not web_only:
        raise SystemExit("SLACK_SIGNING_SECRET is required (use --web-only for voting pages without Slack, "
                         "or --insecure only for local testing)")
    handler = make_handler(None if insecure else secret, Http(cache=Cache()), store=Store(), slack=not web_only)
    httpd = ThreadingHTTPServer((host, port), handler)
    routes = "/poll/<id>" if web_only else "/slack/command, /slack/interact, /poll/<id>"
    print(f"office-eats: listening on http://{host}:{port} ({routes})", file=sys.stderr)
    httpd.serve_forever()
