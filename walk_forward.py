"""Calendar-scheduled, out-of-sample portfolio research backtest."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtesting import run_holdout_backtest
from covariance_calibration import select_diagonal_shrinkage
from portfolio_core import (
    AllocationGroup,
    annualized_moments,
    feasible_reference_weights,
    optimize_portfolio,
)


@dataclass(frozen=True)
class WalkForwardBacktest:
    training_end: pd.Timestamp
    evaluation_start: pd.Timestamp
    evaluation_end: pd.Timestamp
    cadence_months: int
    summary: pd.DataFrame
    equity_curves: pd.DataFrame
    allocation_history: pd.DataFrame


def run_walk_forward_backtest(
    returns: pd.DataFrame,
    *,
    training_fraction: float = 0.70,
    cadence_months: int = 3,
    risk_free_rate: float = 0.0,
    max_weight: float = 1.0,
    current_weights: np.ndarray | None = None,
    trading_cost_bps: float = 0.0,
    covariance_shrinkage: float | str = 0.0,
    allocation_groups: tuple[AllocationGroup, ...] = (),
) -> WalkForwardBacktest:
    """Re-estimate using prior observations only; trade before each review day's return.

    The split is fixed before evaluation. Reviews are scheduled from the first
    evaluation date in calendar months, then executed on the next observed date.
    Estimation expands from the first observation through the day before trading.
    """
    if cadence_months not in (3, 6, 12):
        from portfolio_core import PortfolioError

        raise PortfolioError("La revisión debe ser cada 3, 6 o 12 meses.")

    holdout = run_holdout_backtest(
        returns, training_fraction=training_fraction,
        risk_free_rate=risk_free_rate, max_weight=max_weight,
        current_weights=current_weights, trading_cost_bps=trading_cost_bps,
        covariance_shrinkage=covariance_shrinkage,
        allocation_groups=allocation_groups,
    )
    training_count = holdout.training_observations
    evaluation = returns.iloc[training_count:]
    baseline = (
        holdout.allocations["Cartera actual"].to_numpy()
        if current_weights is not None else None
    )
    reference_name = "Referencia simple factible" if allocation_groups else "Pesos iguales"
    names = ["Máximo Sharpe", "Mínima volatilidad", reference_name]
    if baseline is not None:
        names.append("Cartera actual sin rebalanceo")
    holdings = {name: np.zeros(returns.shape[1]) for name in names}
    curves = {name: [1.0] for name in names}
    paid = {name: 0.0 for name in names}
    turnover_total = {name: 0.0 for name in names}
    records = []
    next_review = evaluation.index[0] + pd.DateOffset(months=cadence_months)
    review_count = 0

    for position, (day, daily_returns) in enumerate(evaluation.iterrows()):
        initial = position == 0
        review = initial or day >= next_review
        if review:
            history = returns.iloc[:training_count + position]
            shrinkage = (
                select_diagonal_shrinkage(history).intensity
                if covariance_shrinkage == "cv" else covariance_shrinkage
            )
            mean, covariance = annualized_moments(
                history, covariance_shrinkage=shrinkage
            )
            targets = {
                "Máximo Sharpe": optimize_portfolio(
                    mean, covariance, risk_free_rate, "max_sharpe", max_weight,
                    allocation_groups,
                ).weights,
                "Mínima volatilidad": optimize_portfolio(
                    mean, covariance, risk_free_rate, "min_volatility", max_weight,
                    allocation_groups,
                ).weights,
                reference_name: feasible_reference_weights(
                    returns.shape[1], max_weight, allocation_groups
                ),
            }
            if initial and baseline is not None:
                targets["Cartera actual sin rebalanceo"] = baseline
            for name, target in targets.items():
                value = float(holdings[name].sum()) if not initial else 1.0
                before = baseline if initial else holdings[name] / value
                turnover = (
                    0.5 * float(np.abs(target - before).sum())
                    if before is not None else 0.0
                )
                cost_fraction = turnover * trading_cost_bps / 10_000
                paid[name] += value * cost_fraction
                turnover_total[name] += turnover
                holdings[name] = value * (1 - cost_fraction) * target
                records.append({
                    "Escenario": name, "Fecha de revisión": day,
                    "Estimación hasta": history.index[-1],
                    "Observaciones de estimación": len(history),
                    "Contracción de covarianza": shrinkage,
                    "Rotación": turnover,
                    "Costo sobre capital en fecha": cost_fraction,
                    **dict(zip(returns.columns, target, strict=True)),
                })
            if not initial:
                review_count += 1
                # Keep the planned calendar schedule rather than drifting with
                # weekends or holidays on the actual execution date.
                while day >= next_review:
                    next_review += pd.DateOffset(months=cadence_months)
        for name in names:
            holdings[name] *= 1 + daily_returns.to_numpy()
            curves[name].append(float(holdings[name].sum()))

    index = pd.DatetimeIndex([holdout.training_end, *evaluation.index])
    equity = pd.DataFrame(curves, index=index)
    days = (evaluation.index[-1] - holdout.training_end).days
    rows = {}
    for name in names:
        curve = equity[name]
        daily = curve.pct_change().dropna()
        volatility = float(daily.std(ddof=1) * np.sqrt(252))
        rows[name] = {
            "Retorno total neto": float(curve.iloc[-1] - 1),
            "Retorno anualizado neto": float(curve.iloc[-1] ** (365.25 / days) - 1),
            "Volatilidad anualizada": volatility,
            "Sharpe realizado": (
                float((daily.mean() * 252 - risk_free_rate) / volatility)
                if volatility > 1e-12 else float("nan")
            ),
            "Máxima caída": float((curve / curve.cummax() - 1).min()),
            "Revisiones posteriores": review_count if name != "Cartera actual sin rebalanceo" else 0,
            "Rotación acumulada": turnover_total[name],
            "Costo pagado sobre capital inicial": paid[name],
        }
    return WalkForwardBacktest(
        holdout.training_end, evaluation.index[0], evaluation.index[-1],
        cadence_months,
        pd.DataFrame.from_dict(rows, orient="index").rename_axis("Escenario"),
        equity,
        pd.DataFrame.from_records(records).set_index(["Fecha de revisión", "Escenario"]),
    )
