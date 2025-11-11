from office_eats.cache import Cache


def test_roundtrip_and_expiry(tmp_path):
    c = Cache(tmp_path / "c.sqlite3")
    k = Cache.key("geocode", "1 Main St")
    assert c.get(k) is None
    c.set(k, {"lat": 1.5}, ttl=60)
    assert c.get(k) == {"lat": 1.5}
    c.set(k, {"lat": 2}, ttl=-1)
    assert c.get(k) is None
    assert c.clear() == 1


def test_key_is_order_insensitive_for_dicts():
    assert Cache.key({"a": 1, "b": 2}) == Cache.key({"b": 2, "a": 1})
