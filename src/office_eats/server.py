"""Slack slash-command endpoint: POST /slack/command, e.g. `/eats dinner party:6 diet:vegan 415 Mission St, SF`.

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
from .cli import parse_diets, parse_when
from .http import Http
from .recommend import Query, recommend
from .scoring import PROFILES
from .slack import post_webhook, to_slack

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
    return Query(" ".join(rest), use_case=use_case, diets=parse_diets(opts.get("diet")),
                 party=int(opts.get("party", 0)), when=parse_when(opts["at"].replace("_", " ")) if "at" in opts else None,
                 max_walk=float(opts["walk"]) if "walk" in opts else None, limit=min(int(opts.get("n", 5)), 10))


def make_handler(secret: str | None, http: Http, worker=threading.Thread):
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
            if self.path != "/slack/command":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"error": "too large"})
            body = self.rfile.read(length)
            if secret is not None and not verify(secret, self.headers.get("X-Slack-Request-Timestamp", ""), body,
                                                 self.headers.get("X-Slack-Signature", "")):
                return self._send(401, {"error": "bad signature"})
            form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()}
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

        def log_message(self, fmt, *args):
            sys.stderr.write("office-eats: " + fmt % args + "\n")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8080, insecure: bool = False) -> None:
    secret = os.environ.get("SLACK_SIGNING_SECRET")
    if not secret and not insecure:
        raise SystemExit("SLACK_SIGNING_SECRET is required (use --insecure only for local testing)")
    httpd = ThreadingHTTPServer((host, port), make_handler(None if insecure else secret, Http(cache=Cache())))
    print(f"office-eats: listening on http://{host}:{port}/slack/command", file=sys.stderr)
    httpd.serve_forever()
