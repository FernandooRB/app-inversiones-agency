"""Local visual QA with synthetic data only; never a production entrypoint."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import technical_ui  # noqa: E402
from technical_analysis import (  # noqa: E402
    MarketHistory,
    TechnicalSnapshot,
    calculate_indicators,
    historical_signals,
)
from watchlist_store import WatchlistStore, identity_key  # noqa: E402
from workspace_presentation import render_shell  # noqa: E402

st.set_page_config(page_title="SIG | Vista previa sintética", layout="wide")
render_shell(("Seguimiento",))
st.info("Vista previa local · series e identidad sintéticas · no son cotizaciones ni una cuenta real.")


def synthetic_history(symbol: str, buy: bool = False) -> MarketHistory:
    if symbol not in {"SIM-ALFA", "SIM-BETA"}:
        raise ValueError("Only the named synthetic instruments have demonstration prices.")
    rng = np.random.default_rng(19)
    days = np.arange(1_100)
    close = 100 + days * 0.035 + 2 * np.sin(days / 7) + rng.normal(0, 0.45, len(days))
    opening = np.r_[close[0], close[:-1]]
    bars = pd.DataFrame({
        "Open": opening, "High": np.maximum(opening, close) + 0.3,
        "Low": np.minimum(opening, close) - 0.3, "Close": close,
        "Volume": np.where(days % 7 == 0, 3_000.0, 1_000.0),
        "Adj Close": close * 0.95, "Dividends": 0.0, "Stock Splits": 0.0,
    }, index=pd.bdate_range("2022-01-01", periods=len(days)))
    if buy:
        signals = historical_signals(calculate_indicators(bars))
        last_buy = np.flatnonzero(signals.Buy.to_numpy())[-1]
        bars = bars.iloc[:last_buy + 1].copy()
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    bars.index = pd.bdate_range(end=yesterday, periods=len(bars))
    return MarketHistory(symbol, bars, "USD", "Mercado ficticio", "America/New_York",
                         datetime.now(UTC), source="Datos sintéticos de revisión visual")


def preview_history(symbol: str, _refresh: str) -> MarketHistory | TechnicalSnapshot:
    if symbol == "SIM-ERROR":
        return TechnicalSnapshot(symbol, "No evaluable", "Fallo sintético del proveedor.")
    if symbol not in {"SIM-ALFA", "SIM-BETA"}:
        return TechnicalSnapshot(
            symbol, "No evaluable", "Esta vista simulada sólo ofrece datos de SIM-ALFA y SIM-BETA. "
            "Consulta las acciones reales en la aplicación con sesión autorizada.",
        )
    return synthetic_history(symbol, buy=symbol == "SIM-ALFA")


store = WatchlistStore(ROOT / "tmp" / "private" / "technical-preview.db")
# A saved empty list is intentional; only seed a database which has never been created.
if not store.path.exists():
    store.save("synthetic-preview", "synthetic-user", ["SIM-ALFA", "SIM-BETA", "SIM-ERROR"])
symbols = store.load("synthetic-preview", "synthetic-user")
if "_technical_owner" not in st.session_state:
    st.session_state.update({
        "_technical_owner": identity_key("synthetic-preview", "synthetic-user"),
        "_technical_symbols": symbols, "_technical_draft": ", ".join(symbols),
        "_optimizer_tickers": "SIM-ALFA, SIM-BETA",
        "_technical_histories": {
            symbol: preview_history(symbol, "initial") for symbol in symbols
        },
        "_technical_refresh_id": "synthetic-preview",
        "_technical_updated": datetime.now(UTC).isoformat(timespec="seconds"),
    })
technical_ui.render_technical(
    watchlist_factory=lambda: (store, "synthetic-preview", "synthetic-user"),
    history_loader=preview_history,
)
