import time

from office_eats.cache import Cache
from office_eats.http import Http


def test_cache_hit_skips_network(monkeypatch):
    http = Http(cache=Cache(":memory:"))
    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": 1}'

    def fake_urlopen(req, timeout):
        calls.append(req.get_header("User-agent"))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert http.fetch("https://example.com/a") == {"ok": 1}
    assert http.fetch("https://example.com/a") == {"ok": 1}
    assert len(calls) == 1 and calls[0].startswith("office-eats/")


def test_rate_limit_spaces_calls(monkeypatch):
    http = Http(min_interval={"h.test": 0.2})
    t0 = time.monotonic()
    http._wait("h.test")
    http._wait("h.test")
    assert time.monotonic() - t0 >= 0.19


def test_json_body_and_auth_not_in_cache_key(monkeypatch):
    http = Http(cache=Cache(":memory:"))
    seen = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"[]"

    def fake_urlopen(req, timeout):
        seen.append((req.data, req.get_header("Content-type")))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    http.fetch("https://api.test/x", json_body={"a": 1}, headers={"Authorization": "Bearer one"})
    http.fetch("https://api.test/x", json_body={"a": 1}, headers={"Authorization": "Bearer two"})
    assert seen == [(b'{"a": 1}', "application/json")]


def test_retries_busy_server_then_succeeds(monkeypatch):
    import urllib.error
    http = Http(backoff=0.01, default_interval=0)
    attempts = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def flaky(req, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    assert http.fetch("https://overpass.test/x") == {"ok": True} and len(attempts) == 3


def test_does_not_retry_client_errors(monkeypatch):
    import urllib.error

    import pytest

    from office_eats.http import HttpError
    http = Http(backoff=0.01, default_interval=0)
    attempts = []

    def bad(req, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", bad)
    with pytest.raises(HttpError) as e:
        http.fetch("https://overpass.test/x")
    assert e.value.status == 400 and len(attempts) == 1
