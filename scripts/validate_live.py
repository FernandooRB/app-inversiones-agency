"""Manual live integration check. Exit 2 means unavailable data, never a pass."""

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from currencies import convert_prices, download_fx
from portfolio_core import (
    PortfolioError,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    download_adjusted_prices,
    optimize_portfolio,
    validate_weights,
)


def main():
    start, end = date(2024, 1, 1), date(2024, 6, 30)
    quotes = {"AAPL": "USD", "MSFT": "USD"}
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "source": "Yahoo Finance / yfinance",
        "base_currency": "MXN",
        "quotes": quotes,
        "start": str(start),
        "end": str(end),
    }
    try:
        data = download_adjusted_prices(tuple(quotes), start, end)
        if data.rejected_tickers:
            raise PortfolioError("Missing requested assets")
        rates = download_fx(quotes, "MXN", start, end)
        prices = convert_prices(data.prices, quotes, "MXN", rates)
        returns = calculate_returns(prices)
        mean, covariance = annualized_moments(returns)
        result = optimize_portfolio(mean, covariance, 0.04, max_weight=0.7)
        validate_weights(result.weights, 2, 0.7)
        risk = calculate_risk_metrics(returns, result.weights)
        evidence.update(
            status="passed",
            observations=len(returns),
            prices_sha256=hashlib.sha256(prices.to_csv().encode()).hexdigest(),
            weights=result.weights.tolist(),
            historical_var=risk.historical_var,
            effective_start=str(prices.index[0]),
            effective_end=str(prices.index[-1]),
        )
        code = 0
    except PortfolioError as exc:
        evidence.update(status="blocked", reason=str(exc))
        code = 2
    print(json.dumps(evidence, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
