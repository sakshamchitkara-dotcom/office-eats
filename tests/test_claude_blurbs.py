import json
from types import SimpleNamespace

import pytest

from office_eats.blurbs import MODEL, claude_shortlist
from office_eats.models import Venue
from office_eats.scoring import Scored


class FakeClient:
    def __init__(self, picks, stop="end_turn"):
        self.picks, self.stop, self.kwargs = picks, stop, None
        self.messages = self

    def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(stop_reason=self.stop,
                               content=[SimpleNamespace(type="text", text=json.dumps({"picks": self.picks}))])


def items():
    return [Scored(Venue(f"node/{i}", f"V{i}", 0, 0, cuisine=["thai"]), 90 - i, ["close"]) for i in range(4)]


def test_shortlist_validates_ids_and_trims():
    c = FakeClient([{"id": "node/2", "blurb": "Great  pad thai spot."}, {"id": "evil/9", "blurb": "x"},
                    {"id": "node/2", "blurb": "dup"}, {"id": "node/0", "blurb": "Closest."}])
    out = claude_shortlist(items(), {"use_case": "lunch"}, 2, client=c)
    assert [s.venue.id for s in out] == ["node/2", "node/0"] and out[0].blurb == "Great pad thai spot."
    assert c.kwargs["model"] == MODEL == "claude-opus-5-5"
    assert c.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in c.kwargs and "tool_choice" not in c.kwargs


def test_refusal_or_empty_raises():
    with pytest.raises(RuntimeError):
        claude_shortlist(items(), {}, 2, client=FakeClient([], stop="refusal"))
    with pytest.raises(RuntimeError):
        claude_shortlist(items(), {}, 2, client=FakeClient([{"id": "nope", "blurb": "x"}]))
