"""Cross-source diagnostics for historical technical signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from technical_analysis import (
    MarketHistory,
    TechnicalError,
    calculate_indicators,
    completed_bars,
    historical_signals,
    signal_conditions,
)


@dataclass(frozen=True)
class SourceAudit:
    symbol: str
    left_source: str
    right_source: str
    currency: str
    left_latest: str
    right_latest: str
    compared_sessions: int
    signal_disagreements: int
    condition_disagreements: int
    max_close_gap_pct: float
    max_volume_gap_pct: float
    left_latest_signal: str
    right_latest_signal: str
    last_close_gap_pct: float | None
    last_volume_gap_pct: float | None
    reasons_to_review: tuple[str, ...]


def _signal_name(signals: pd.DataFrame) -> str:
    last = signals.iloc[-1]
    return "Compra" if last.Buy else "Venta / revisar reducción" if last.Sell else "Esperar"


def compare_market_histories(
    left: MarketHistory, right: MarketHistory, *, now: datetime | None = None,
    max_sessions: int = 504,
) -> SourceAudit:
    """Compare identical sessions after each source has the full signal warmup.

    This reports discrepancies; it never silently substitutes a second feed in production.
    """
    if left.symbol != right.symbol:
        raise TechnicalError("Las fuentes deben corresponder al mismo símbolo.")
    if not left.currency or left.currency != right.currency:
        raise TechnicalError("Las fuentes deben declarar la misma moneda.")
    if type(max_sessions) is not int or max_sessions < 1:
        raise TechnicalError("El número de sesiones a comparar debe ser positivo.")
    now = now or datetime.now(UTC)
    left_bars = completed_bars(left, now)
    right_bars = completed_bars(right, now)
    if len(left_bars) < 252 or len(right_bars) < 252:
        raise TechnicalError("Cada fuente necesita al menos 252 sesiones válidas.")
    left_indicators = calculate_indicators(left_bars)
    right_indicators = calculate_indicators(right_bars)
    left_signals = historical_signals(left_indicators)
    right_signals = historical_signals(right_indicators)
    left_buy, left_sell = signal_conditions(left_indicators)
    right_buy, right_sell = signal_conditions(right_indicators)
    common = left_bars.index.intersection(right_bars.index)
    # A date common to both sources is comparable only after both have 252 bars.
    left_positions = left_bars.index.get_indexer(common)
    right_positions = right_bars.index.get_indexer(common)
    common = common[(left_positions >= 251) & (right_positions >= 251)][-max_sessions:]
    if len(common) < 20:
        raise TechnicalError("Las fuentes no comparten suficientes sesiones evaluables.")
    left_values = left_bars.loc[common]
    right_values = right_bars.loc[common]
    close_gap = (left_values.Close - right_values.Close).abs() / right_values.Close
    volume_gap = (left_values.Volume - right_values.Volume).abs() / right_values.Volume
    signal_diff = left_signals.loc[common].ne(right_signals.loc[common]).any(axis=1)
    condition_diff = 0
    for lhs, rhs in ((left_buy, right_buy), (left_sell, right_sell)):
        condition_diff += int(lhs.loc[common].ne(rhs.loc[common]).to_numpy().sum())
    reasons = []
    if left_bars.index[-1] != right_bars.index[-1]:
        reasons.append("Las fuentes terminan en sesiones distintas.")
    if signal_diff.any():
        reasons.append(f"Hay {int(signal_diff.sum())} sesiones con señales distintas.")
    if condition_diff:
        reasons.append(f"Hay {condition_diff} condiciones con resultados distintos.")
    if not np.isfinite(close_gap.to_numpy()).all() or not np.isfinite(volume_gap.to_numpy()).all():
        raise TechnicalError("El contraste produjo diferencias no finitas.")
    same_latest = left_bars.index[-1] == right_bars.index[-1]
    return SourceAudit(
        left.symbol, left.source, right.source, left.currency,
        str(left_bars.index[-1].date()), str(right_bars.index[-1].date()),
        len(common), int(signal_diff.sum()), condition_diff,
        float(close_gap.max() * 100), float(volume_gap.max() * 100),
        _signal_name(left_signals), _signal_name(right_signals),
        float(close_gap.iloc[-1] * 100) if same_latest else None,
        float(volume_gap.iloc[-1] * 100) if same_latest else None,
        tuple(reasons),
    )
