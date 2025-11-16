import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


class FakeHttp:
    """Serves recorded fixtures by URL substring; fails loudly on anything unexpected."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def fetch(self, url, *, data=None, headers=None, ttl=0, parse_json=True):
        self.calls.append((url, data))
        for needle, payload in self.routes.items():
            if needle in url:
                return payload(url, data) if callable(payload) else payload
        raise AssertionError(f"unexpected network call: {url}")


@pytest.fixture
def fake_http():
    return FakeHttp
