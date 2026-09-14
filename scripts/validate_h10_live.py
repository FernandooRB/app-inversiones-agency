"""Recalculate the 2024 AAPL/MSFT FX sensitivity without storing Yahoo prices."""

import json
from datetime import date
from pathlib import Path

import numpy as np

from fx_comparison import compare_series, fixed_metrics, internal_missing_dates, read_reference
from portfolio_core import (
    annualized_moments,
    calculate_returns,
    download_adjusted_prices,
    optimize_portfolio,
)


def main() -> None:
    start, end = date(2024, 1, 1), date(2024, 6, 30)
    prices = download_adjusted_prices(("AAPL", "MSFT"), start, end).prices
    yahoo = download_adjusted_prices(("USDMXN=X",), start, end).prices["USDMXN=X"]
    reference = read_reference(
        (Path(__file__).resolve().parents[1] / "docs/fx_reference_fed_h10_2024h1.csv").read_bytes()
    )
    table, baseline, alternative = compare_series(prices, yahoo, reference)
    omitted = internal_missing_dates(prices, table.index)
    summary = {
        "source": "Federal Reserve H.10 vs Yahoo Finance, USD/MXN",
        "period_requested": [start.isoformat(), end.isoformat()],
        "asset_price_dates": len(prices),
        "common_dates": len(table),
        "internal_omitted_dates": [item.date().isoformat() for item in omitted],
        "fx_difference_mean_relative": float(table["Diferencia relativa"].mean()),
        "fx_difference_max_absolute_relative": float(table["Diferencia relativa"].abs().max()),
        "fx_difference_max_absolute_date": table["Diferencia relativa"].abs().idxmax().date().isoformat(),
        "fx_difference_above_one_percent_count": int((table["Diferencia relativa"].abs() > 0.01).sum()),
    }
    if not len(omitted) and len(table) >= 60:
        weights = np.array([0.3, 0.7])
        for name, values in (("yahoo", baseline), ("h10", alternative)):
            summary[name] = fixed_metrics(values, weights, 0.03, 0.95, 5)
            mean, covariance = annualized_moments(calculate_returns(values))
            optimum = optimize_portfolio(mean, covariance, 0.03, max_weight=0.7)
            summary[name]["optimized_weights"] = dict(
                zip(values.columns, optimum.weights.tolist(), strict=True)
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
