import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from conftest import load
from office_eats import server

SECRET = "s3cret"


def sign(body: bytes, ts: int):
    return "v0=" + hmac.new(SECRET.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()


def test_verify():
    body, ts = b"text=hi", int(time.time())
    assert server.verify(SECRET, str(ts), body, sign(body, ts))
    assert not server.verify(SECRET, str(ts), body + b"x", sign(body, ts))
    assert not server.verify(SECRET, str(ts - 600), body, sign(body, ts - 600))  # replay
    assert not server.verify(SECRET, "abc", body, sign(body, ts))


def test_parse_command():
    q = server.parse_command("dinner party:6 diet:vegan,halal walk:12 415 Mission St, SF")
    assert (q.use_case, q.party, q.diets, q.max_walk, q.location) == ("dinner", 6, {"vegan", "halal"}, 12.0, "415 Mission St, SF")
    assert server.parse_command("37.33,-121.89").use_case == "lunch"
    with pytest.raises(ValueError, match="Usage"):
        server.parse_command("coffee")


@pytest.fixture
def running(fake_http, monkeypatch):
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    posted = []
    monkeypatch.setattr(server, "post_webhook", lambda payload, url: posted.append((url, payload)))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Inline:  # run the background job synchronously so the test is deterministic
        def __init__(self, target, args, daemon): self.t, self.a = target, args
        def start(self): self.t(*self.a)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(SECRET, http, worker=Inline))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", posted
    httpd.shutdown()


def post(base, body: bytes, headers):
    req = urllib.request.Request(base + "/slack/command", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_rejects_bad_signature(running):
    base, posted = running
    status, _ = post(base, b"text=lunch+1,1", {"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad"})
    assert status == 401 and posted == []


def test_signed_command_acks_then_replies(running):
    base, posted = running
    body = urllib.parse.urlencode({"text": "coffee 345 Park Ave, San Jose", "response_url": "https://hooks.slack.com/commands/X"}).encode()
    ts = int(time.time())
    status, ack = post(base, body, {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)})
    assert status == 200 and ack["text"].startswith("Looking for coffee meeting spots")
    url, payload = posted[0]
    assert url == "https://hooks.slack.com/commands/X" and payload["response_type"] == "in_channel"
    assert payload["text"].startswith("Coffee meeting near")
