"""A temporary cloud filesystem must never be advertised as a permanent case store."""

from types import SimpleNamespace

import pytest

from case_workspace import WorkspaceError
from watchlist_store import WatchlistError


def test_session_only_blocks_case_storage_even_if_persistence_was_accidentally_enabled(monkeypatch, tmp_path):
    import workspace_ui

    path = tmp_path / "must-not-open.db"
    monkeypatch.setattr(
        workspace_ui.st,
        "secrets",
        {
            "deployment": {"storage_mode": "session_only"},
            "workspace": {"enabled": True, "database_path": str(path)},
        },
    )
    with pytest.raises(WorkspaceError, match="Piloto gratuito"):
        workspace_ui.configured_workspace()
    assert not path.exists()


def test_session_only_blocks_sqlite_watchlists_and_paper_journals(monkeypatch, tmp_path):
    import technical_ui

    path = tmp_path / "must-not-open.db"
    monkeypatch.setattr(
        technical_ui.st,
        "secrets",
        {
            "deployment": {"storage_mode": "session_only"},
            "technical_watchlist": {"database_path": str(path), "backend": "sqlite"},
        },
    )
    monkeypatch.setattr(
        technical_ui.st, "user", SimpleNamespace(to_dict=lambda: {"iss": "test", "sub": "test"})
    )
    monkeypatch.setattr(technical_ui, "authorized", lambda *_: True)
    with pytest.raises(WatchlistError, match="almacenamiento externo"):
        technical_ui.configured_watchlist()
    assert not path.exists()


def test_session_only_can_use_the_existing_external_watchlist_backend(monkeypatch):
    import technical_ui

    expected = object()
    monkeypatch.setattr(
        technical_ui.st,
        "secrets",
        {
            "deployment": {"storage_mode": "session_only"},
            "technical_watchlist": {
                "backend": "supabase",
                "url": "https://example.invalid",
                "secret_key": "fake",
            },
        },
    )
    monkeypatch.setattr(
        technical_ui.st, "user", SimpleNamespace(to_dict=lambda: {"iss": "test", "sub": "test"})
    )
    monkeypatch.setattr(technical_ui, "authorized", lambda *_: True)
    monkeypatch.setattr(technical_ui, "SupabaseWatchlistStore", lambda *_args, **_kwargs: expected)
    store, issuer, subject = technical_ui.configured_watchlist()
    assert store is expected and (issuer, subject) == ("test", "test")
