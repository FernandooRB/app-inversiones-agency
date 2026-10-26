import json
from datetime import UTC, datetime

import pytest

from watchlist_backup import export_watchlist, import_watchlist
from watchlist_store import WatchlistError, WatchlistStore


def test_export_restore_is_owner_free_and_does_not_touch_other_user(tmp_path):
    store = WatchlistStore(tmp_path / "watchlists.db")
    store.save("issuer", "alice", ["AAPL", "MSFT"])
    store.save("issuer", "bob", ["KO"])
    data = export_watchlist(store.load("issuer", "alice"), now=datetime(2026, 10, 26, tzinfo=UTC))
    assert b"alice" not in data and b"issuer" not in data
    store.save("issuer", "alice", [])
    store.save("issuer", "alice", import_watchlist(data))
    assert store.load("issuer", "alice") == ["AAPL", "MSFT"]
    assert store.load("issuer", "bob") == ["KO"]


@pytest.mark.parametrize("change", [
    {"version": 2},
    {"symbols": ["AAPL", "AAPL"]},
    {"symbols": ["aapl"]},
    {"symbols": ["AAPL"] * 26},
    {"exported_at": "2026-10-26"},
])
def test_import_rejects_bad_backup(change):
    payload = json.loads(export_watchlist(["AAPL"]))
    payload.update(change)
    with pytest.raises(WatchlistError):
        import_watchlist(json.dumps(payload).encode())


def test_import_rejects_oversized_or_extra_fields():
    with pytest.raises(WatchlistError, match="8 KB"):
        import_watchlist(b"x" * 8193)
    payload = json.loads(export_watchlist([]))
    payload["secret"] = "should not be accepted"
    with pytest.raises(WatchlistError, match="formato"):
        import_watchlist(json.dumps(payload).encode())
