"""Heuristic review flags for raw daily quote-currency price series."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError

JUMP_THRESHOLD = 0.30
UNCHANGED_SESSIONS = 5


@dataclass(frozen=True)
class PriceQualityIssue:
    ticker: str
    kind: str
    first_date: str
    last_date: str
    detail: str


def assess_price_quality(prices: pd.DataFrame) -> tuple[PriceQualityIssue, ...]:
    """Flag large adjacent moves and runs of exactly equal closing prices.

    These thresholds are operational prompts; neither condition proves bad data.
    Use raw prices before FX conversion so the issuer's quote is reviewed separately.
    """
    if (
        prices.empty or prices.columns.has_duplicates or prices.index.has_duplicates
        or not isinstance(prices.index, pd.DatetimeIndex)
        or not prices.index.is_monotonic_increasing
        or not np.isfinite(prices.to_numpy(dtype=float)).all()
        or (prices <= 0).any().any()
    ):
        raise PortfolioError("No se pueden revisar precios inválidos o fechas desordenadas.")

    issues = []
    for ticker in prices.columns:
        series = prices[ticker]
        returns = series.pct_change(fill_method=None)
        for day, change in returns.items():
            if pd.notna(change) and abs(change) >= JUMP_THRESHOLD:
                previous = series.index[series.index.get_loc(day) - 1]
                issues.append(PriceQualityIssue(
                    str(ticker), "Salto de precio", previous.date().isoformat(),
                    day.date().isoformat(), f"{change:+.2%}",
                ))

        unchanged = series.diff().eq(0).to_numpy()
        run_start = None
        for position in range(1, len(unchanged) + 1):
            equal = position < len(unchanged) and unchanged[position]
            if equal and run_start is None:
                run_start = position
            if not equal and run_start is not None:
                count = position - run_start
                if count >= UNCHANGED_SESSIONS:
                    issues.append(PriceQualityIssue(
                        str(ticker), "Cierre sin cambio",
                        series.index[run_start - 1].date().isoformat(),
                        series.index[position - 1].date().isoformat(),
                        f"{count} sesiones consecutivas sin variación",
                    ))
                run_start = None
    return tuple(sorted(issues, key=lambda issue: (issue.ticker, issue.first_date, issue.kind)))
