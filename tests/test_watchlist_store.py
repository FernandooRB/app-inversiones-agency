import sqlite3
from pathlib import Path

import pytest

from watchlist_store import WatchlistError, WatchlistStore, identity_key


def test_list_survives_reopen_and_is_isolated_by_full_oidc_identity(tmp_path):
    path = tmp_path / "private" / "watchlists.db"
    store = WatchlistStore(path)
    store.save("issuer-a", "subject-a", "aapl, MSFT, AAPL")
    store.save("issuer-b", "subject-a", ["GOOG"])
    store.save("issuer-a", "subject-b", ["TSLA"])
    reopened = WatchlistStore(path)
    assert reopened.load("issuer-a", "subject-a") == ["AAPL", "MSFT"]
    assert reopened.load("issuer-b", "subject-a") == ["GOOG"]
    assert reopened.load("issuer-a", "subject-b") == ["TSLA"]
    assert reopened.load("issuer-c", "subject-a") == []
    store.save("issuer-a", "subject-a", [])
    assert reopened.load("issuer-a", "subject-a") == []
    assert reopened.load("issuer-b", "subject-a") == ["GOOG"]


def test_list_limits_and_invalid_ticker_do_not_overwrite_saved_list(tmp_path):
    store = WatchlistStore(tmp_path / "lists.db")
    store.save("issuer", "subject", ["AAPL"])
    for symbols in ([f"T{i}" for i in range(26)], ["AAPL; DROP TABLE technical_watchlists"]):
        with pytest.raises(WatchlistError):
            store.save("issuer", "subject", symbols)
    assert store.load("issuer", "subject") == ["AAPL"]


def test_identity_is_unambiguous_and_database_path_is_absolute():
    assert identity_key("a", "bc") != identity_key("ab", "c")
    with pytest.raises(WatchlistError):
        identity_key("", "subject")
    with pytest.raises(WatchlistError):
        WatchlistStore(Path("relative.db"))


def test_corrupt_saved_list_and_storage_failure_are_safe(tmp_path):
    path = tmp_path / "lists.db"
    store = WatchlistStore(path)
    store.save("issuer", "subject", ["AAPL"])
    with sqlite3.connect(path) as db:
        db.execute("UPDATE technical_watchlists SET symbols = ?", ('{"not": "a list"}',))
    with pytest.raises(WatchlistError, match="formato"):
        store.load("issuer", "subject")
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WatchlistError, match="guardar"):
        WatchlistStore(blocked / "lists.db").save("issuer", "subject", ["AAPL"])
