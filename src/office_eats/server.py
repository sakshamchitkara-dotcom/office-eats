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
from .poll import to_slack as poll_to_slack
from .scoring import PROFILES
from .slack import post_webhook, to_slack
from .store import Store, StoreError
from .tz import parse_when

USAGE = ("Usage: `/eats [lunch|dinner|catering|coffee] [diet:vegan,halal] [party:8] [at:fri 19:00] "
         "[walk:10] <address or lat,lon>`")
MAX_BODY = 16 * 1024


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
        if sep and k.lower() in ("diet", "party", "at", "walk", "n") and v:
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
    return Query(" ".join(rest), use_case=use_case, diets=parse_diets(opts.get("diet")),
                 party=int(opts.get("party", 0)), at=at,
                 max_walk=float(opts["walk"]) if "walk" in opts else None, limit=min(int(opts.get("n", 5)), 10))


def make_handler(secret: str | None, http: Http, worker=threading.Thread, store: Store | None = None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in ("/slack/command", "/slack/interact"):
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            body = self.rfile.read(length)
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


def serve(host: str = "127.0.0.1", port: int = 8080, insecure: bool = False) -> None:
    secret = os.environ.get("SLACK_SIGNING_SECRET")
    if not secret and not insecure:
        raise SystemExit("SLACK_SIGNING_SECRET is required (use --insecure only for local testing)")
    handler = make_handler(None if insecure else secret, Http(cache=Cache()), store=Store())
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"office-eats: listening on http://{host}:{port} (/slack/command, /slack/interact)", file=sys.stderr)
    httpd.serve_forever()
