"""A fresh consultation must clear stale-data alerts without rewriting the first observation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from alpaca_order_fakes import ACCOUNT_ID, FakePaper
from streamlit.testing.v1 import AppTest
from test_alpaca_signal_results import snapshot_for

import alpaca_trial_ui
from alpaca_alerts import active_alerts, observation, observation_key, observation_record_key
from alpaca_trial_store import SQLiteTrialStore
from technical_analysis import BUY, WAIT, analyze_history


def test_refresh_same_signal_keeps_both_consultations_and_clears_stale_alert(
    monkeypatch, tmp_path, technical_history,
):
    now = datetime.now(UTC)
    history = replace(technical_history, symbol="SIM", fetched_at=now)
    old_history = replace(history, fetched_at=now - timedelta(hours=2))
    row = observation(old_history, analyze_history(old_history))
    watchlist_path = tmp_path / "watchlist.db"
    store = SQLiteTrialStore(watchlist_path.with_suffix(".alpaca-orders.db"))
    original = store.append("issuer", "alice", ACCOUNT_ID, "observation", row, key=observation_key(row))
    server = FakePaper(now)
    monkeypatch.setattr(alpaca_trial_ui, "_test_client", server.client, raising=False)
    monkeypatch.setattr(alpaca_trial_ui, "_test_history", lambda _: history, raising=False)
    app = AppTest.from_string(
        "from pathlib import Path\n"
        "import alpaca_trial_ui as ui\n"
        "from watchlist_store import WatchlistStore\n"
        "client = ui._test_client\n"
        "ui.render_trial_controls("
        f"WatchlistStore(Path({str(watchlist_path)!r})), 'issuer', 'alice', client.fetch_snapshot(), "
        "client_loader=lambda: client, expected_signature=client.configuration_signature, "
        "symbols=['SIM'], history_loader=ui._test_history)\n",
        default_timeout=60,
    ).run()
    assert not app.exception
    app.button(key="technical_alpaca_order_alert_refresh").click().run()
    assert not app.exception and not app.error
    consultations = [e for e in store.load("issuer", "alice", ACCOUNT_ID) if e.kind == "observation"]
    assert consultations[-1].payload["fetched_at"] == now.isoformat()
    assert consultations[0] == original
    assert len(consultations) == 2
    alerts = active_alerts(server.client.fetch_snapshot(), consultations,
                          [consultations[-1].payload], now=now)
    assert "stale_signal" not in {a["kind"] for a in alerts}
    # The same cached provider response must not add another consultation or send an order.
    app.button(key="technical_alpaca_order_alert_refresh").click().run()
    assert not app.exception
    assert len([e for e in store.load("issuer", "alice", ACCOUNT_ID) if e.kind == "observation"]) == 2
    assert not server.posts


def test_signal_change_uses_logical_signal_not_consultation_id(tmp_path):
    now = datetime.now(UTC)
    store = SQLiteTrialStore(tmp_path / "observations.db")
    old = {"symbol": "SIM", "session": str(now.date()), "signal": WAIT, "reason": "Prior",
           "fetched_at": (now - timedelta(minutes=20)).isoformat(),
           "strategy_version": "tendencias-confirmadas-v1", "currency": "USD"}
    store.append("issuer", "alice", ACCOUNT_ID, "observation", old, key=observation_key(old))
    fresh = {**old, "signal": BUY, "reason": "Confirmed", "fetched_at": now.isoformat()}
    store.append("issuer", "alice", ACCOUNT_ID, "observation", fresh,
                 key=observation_record_key(fresh))
    snapshot = replace(snapshot_for([], 0), fetched_at=now)
    events = store.load("issuer", "alice", ACCOUNT_ID)
    first = active_alerts(snapshot, events, [fresh], now=now)
    assert [a["kind"] for a in first] == ["signal_change"]
    refreshed = {**fresh, "fetched_at": (now + timedelta(minutes=1)).isoformat()}
    store.append("issuer", "alice", ACCOUNT_ID, "observation", refreshed,
                 key=observation_record_key(refreshed))
    again = active_alerts(snapshot, store.load("issuer", "alice", ACCOUNT_ID), [refreshed], now=now)
    assert [a["key"] for a in again] == [a["key"] for a in first]
