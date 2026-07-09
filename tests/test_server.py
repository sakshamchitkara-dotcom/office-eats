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
from office_eats.store import Store

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
    q = server.parse_command("lunch route:osrm tz:Europe/London at:fri_12:30 1 Canada Square, London")
    assert (q.routing, q.tz, q.at, q.location) == ("osrm", "Europe/London", "fri 12:30", "1 Canada Square, London")
    with pytest.raises(ValueError, match="unknown diet"):
        server.parse_command("diet:paleo 1,1")
    with pytest.raises(ValueError, match="route must be"):
        server.parse_command("route:google 1,1")
    with pytest.raises(ValueError, match="unknown time zone"):
        server.parse_command("tz:Nowhere/Land 1,1")
    for bad in ("party:abc", "party:-2", "n:0", "walk:nan", "walk:inf"):
        with pytest.raises(ValueError, match=f"^{bad.split(':')[0]}: must be a number"):
            server.parse_command(f"{bad} 1,1")
    assert server.parse_command("1,1").limit == 5 and server.parse_command("n:3 1,1").limit == 3


@pytest.fixture
def running(fake_http, monkeypatch):
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    posted = []
    monkeypatch.setattr(server, "post_webhook", lambda payload, url: posted.append((url, payload)))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class Inline:  # run the background job synchronously so the test is deterministic
        def __init__(self, target, args, daemon): self.t, self.a = target, args
        def start(self): self.t(*self.a)

    store = Store(":memory:")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(SECRET, http, worker=Inline, store=store))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", posted, store
    httpd.shutdown()


def post(base, body: bytes, headers, path="/slack/command"):
    req = urllib.request.Request(base + path, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_rejects_bad_signature(running):
    base, posted, _ = running
    status, _ = post(base, b"text=lunch+1,1", {"X-Slack-Request-Timestamp": str(int(time.time())), "X-Slack-Signature": "v0=bad"})
    assert status == 401 and posted == []


def test_signed_command_acks_then_replies(running):
    base, posted, _ = running
    body = urllib.parse.urlencode({"text": "coffee 345 Park Ave, San Jose", "response_url": "https://hooks.slack.com/commands/X"}).encode()
    ts = int(time.time())
    status, ack = post(base, body, {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)})
    assert status == 200 and ack["text"].startswith("Looking for coffee meeting spots")
    url, payload = posted[0]
    assert url == "https://hooks.slack.com/commands/X" and payload["response_type"] == "in_channel"
    assert payload["text"].startswith("Coffee meeting near")


def click(base, poll_id, choice, user="ana"):
    payload = {"type": "block_actions", "user": {"id": "U1", "username": user}, "response_url": "https://hooks.slack.com/actions/X",
               "actions": [{"action_id": f"office_eats_vote_{choice}", "value": f"{poll_id}:{choice}"}]}
    body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
    ts = int(time.time())
    return post(base, body, {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)}, "/slack/interact")


def test_vote_button_records_vote_and_redraws_poll(running):
    base, posted, store = running
    opts = [{"id": f"node/{i}", "name": f"P{i}", "url": "https://www.openstreetmap.org/node/1", "walk_min": 2, "blurb": ""}
            for i in range(2)]
    pid = store.create_poll("Lunch?", opts)
    assert click(base, pid, 1) == (200, {})
    assert store.tally(pid)[1][0] == (opts[1], ["ana"])
    url, reply = posted[-1]
    assert url == "https://hooks.slack.com/actions/X" and reply["replace_original"] is True and "*1* vote" in json.dumps(reply)
    store.close_poll(pid)
    click(base, pid, 0, "bo")
    assert "Vote not counted: this poll is closed" in posted[-1][1]["text"]


def test_interact_rejects_unsigned_and_junk(running):
    base, posted, _ = running
    body = urllib.parse.urlencode({"payload": "{}"}).encode()
    assert post(base, body, {"X-Slack-Request-Timestamp": "1", "X-Slack-Signature": "v0=x"}, "/slack/interact")[0] == 401
    ts = int(time.time())
    assert post(base, body, {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)}, "/slack/interact")[0] == 400
    assert posted == []


def test_bad_diet_gets_a_usage_reply_not_a_crash(running):
    base, posted, _ = running
    body = urllib.parse.urlencode({"text": "diet:paleo 1,1", "response_url": "https://hooks.slack.com/commands/X"}).encode()
    ts = int(time.time())
    status, ack = post(base, body, {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sign(body, ts)})
    assert status == 200 and "unknown diet" in ack["text"] and posted == []
