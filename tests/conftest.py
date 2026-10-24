"""Synthetic market fixtures; no provider access or real account documents."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from technical_analysis import MarketHistory


@pytest.fixture
def technical_bars():
    rng = np.random.default_rng(19)
    days = np.arange(1_100)
    close = 100 + days * 0.035 + 2 * np.sin(days / 7) + rng.normal(0, 0.45, len(days))
    opening = np.r_[close[0], close[:-1]]
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    return pd.DataFrame({
        "Open": opening, "High": np.maximum(opening, close) + 0.3,
        "Low": np.minimum(opening, close) - 0.3, "Close": close,
        "Volume": np.where(days % 7 == 0, 3_000.0, 1_000.0),
        "Adj Close": close * 0.95, "Dividends": 0.0, "Stock Splits": 0.0,
    }, index=pd.bdate_range(end=yesterday, periods=len(days)))


@pytest.fixture
def technical_history(technical_bars):
    return MarketHistory("AAPL", technical_bars, "USD", "NASDAQ", "America/New_York", datetime.now(UTC))
