import pytest

from office_eats.store import Store, StoreError

OPTS = [{"id": "node/1", "name": "Taqueria"}, {"id": "node/2", "name": "Pho"}, {"id": "node/3", "name": "Deli"}]


@pytest.fixture
def store():
    return Store(":memory:")


def test_votes_are_one_per_person_and_tallied(store):
    pid = store.create_poll("Lunch Friday", OPTS)
    store.vote(pid, "ana", 1)
    store.vote(pid, "bo", 1)
    store.vote(pid, "cy", 0)
    store.vote(pid, "cy", 1)  # changed their mind
    poll, rows = store.tally(pid)
    assert poll["title"] == "Lunch Friday"
    assert [(o["name"], v) for o, v in rows] == [("Pho", ["ana", "bo", "cy"]), ("Taqueria", []), ("Deli", [])]


def test_validation(store):
    pid = store.create_poll("x", OPTS)
    with pytest.raises(StoreError, match="1-3"):
        store.vote(pid, "ana", 3)
    with pytest.raises(StoreError, match="voter"):
        store.vote(pid, "  ", 0)
    with pytest.raises(StoreError, match="no poll"):
        store.vote("nope", "ana", 0)
    with pytest.raises(StoreError, match="2-10"):
        store.create_poll("x", OPTS[:1])
    store.close_poll(pid)
    with pytest.raises(StoreError, match="closed"):
        store.vote(pid, "ana", 0)


def test_persists_on_disk(tmp_path):
    path = tmp_path / "d.sqlite3"
    pid = Store(path).create_poll("x", OPTS)
    Store(path).vote(pid, "ana", 2)
    assert Store(path).tally(pid)[1][0][1] == ["ana"]


def test_env_paths_expand_home(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "HOME": str(tmp_path), "OFFICE_EATS_DB": "~/db.sqlite3", "OFFICE_EATS_CACHE": "~/cache.sqlite3"}
    out = subprocess.run([sys.executable, "-c", "from office_eats import cache, store; print(store.DEFAULT_PATH); print(cache.DEFAULT_PATH)"],
                         env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == [str(tmp_path / "db.sqlite3"), str(tmp_path / "cache.sqlite3")]
