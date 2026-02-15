import json

import pytest

from office_eats import slack
from office_eats.models import Place, Venue
from office_eats.recommend import Query, Result
from office_eats.scoring import Scored


def result(n=2):
    items = [Scored(Venue(f"node/{i}", f"<!channel> Cafe & Co {i}", 0, 0, website="https://c.test", walk_min=3),
                    70, ["close"], blurb="Nice <b>.") for i in range(n)]
    return Result(Query("0,0", use_case="coffee", diets={"vegan"}), Place("HQ", 0, 0), items, 10)


def test_blocks_escape_untrusted_text():
    p = slack.to_slack(result())
    assert p["text"] == "Coffee meeting near HQ"
    body = json.dumps(p)
    assert "<!channel>" not in body and "&lt;!channel&gt; Cafe &amp; Co 0" in body
    assert "<https://www.openstreetmap.org/node/0|map>" in body and "<https://c.test|site>" in body
    assert "diet: vegan" in body


def test_block_cap():
    assert len(slack.to_slack(result(60))["blocks"]) == 50


def test_webhook_url_validated():
    with pytest.raises(ValueError):
        slack.post_webhook({}, "http://evil.test/hook")


def test_webhook_posts_json(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"

    def fake(req, timeout):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake)
    slack.post_webhook({"text": "hi"}, "https://hooks.slack.com/services/T/B/X")
    assert seen == {"url": "https://hooks.slack.com/services/T/B/X", "body": {"text": "hi"}}
