"""Explicit one-time implementation cost estimates for target allocations."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError, validate_weights


@dataclass(frozen=True)
class ImplementationCostAssumptions:
    commission_bps: float = 0.0
    market_cost_bps: float = 0.0
    vat_rate: float = 0.0
    minimum_commission: float = 0.0
    annual_fixed_cost: float = 0.0
    annual_management_rate: float = 0.0

    def annual_recurring_cost(self, portfolio_value: float) -> float:
        """Return the all-in annual recurring cost declared by the user."""
        _validate_assumptions(self)
        if not np.isfinite(portfolio_value) or portfolio_value < 0:
            raise PortfolioError("El capital para estimar costos no puede ser negativo.")
        return self.annual_fixed_cost + portfolio_value * self.annual_management_rate


@dataclass(frozen=True)
class ImplementationCostEstimate:
    alternative_name: str
    starting_point: str
    detail: pd.DataFrame
    buy_notional: float
    sell_notional: float
    commission: float
    vat: float
    market_cost: float
    total_cost: float

    @property
    def traded_notional(self) -> float:
        return self.buy_notional + self.sell_notional


def _validate_assumptions(assumptions: ImplementationCostAssumptions) -> None:
    values = (
        assumptions.commission_bps,
        assumptions.market_cost_bps,
        assumptions.vat_rate,
        assumptions.minimum_commission,
        assumptions.annual_fixed_cost,
        assumptions.annual_management_rate,
    )
    if not np.isfinite(values).all():
        raise PortfolioError("Los supuestos de costo deben ser finitos.")
    if not 0 <= assumptions.commission_bps <= 500:
        raise PortfolioError("La comisión debe estar entre 0 y 500 puntos base.")
    if not 0 <= assumptions.market_cost_bps <= 500:
        raise PortfolioError("El costo de mercado debe estar entre 0 y 500 puntos base.")
    if not 0 <= assumptions.vat_rate <= 1:
        raise PortfolioError("El IVA sobre comisiones debe estar entre 0% y 100%.")
    if not 0 <= assumptions.minimum_commission <= 100_000:
        raise PortfolioError("La comisión mínima debe estar entre 0 y 100,000.")
    if not 0 <= assumptions.annual_fixed_cost <= 1_000_000:
        raise PortfolioError("El costo fijo anual debe estar entre 0 y 1,000,000.")
    if not 0 <= assumptions.annual_management_rate <= 0.20:
        raise PortfolioError("La administración anual debe estar entre 0% y 20%.")


def estimate_implementation_cost(
    tickers: tuple[str, ...],
    target_weights,
    portfolio_value: float,
    assumptions: ImplementationCostAssumptions,
    *,
    alternative_name: str,
    current_weights=None,
) -> ImplementationCostEstimate:
    """Estimate explicit costs per buy/sell order without changing target weights.

    If current weights are omitted, the starting point is cash and the entire target
    notional is purchased. Costs are additional to the target trade notionals; this is
    not a self-financing execution or a tax calculation.
    """
    if (
        not tickers or len(set(tickers)) != len(tickers)
        or any(
            not isinstance(ticker, str) or not ticker.strip()
            or any(ord(char) < 32 for char in ticker)
            for ticker in tickers
        )
    ):
        raise PortfolioError("Los activos para estimar costos deben ser etiquetas válidas y únicas.")
    if not np.isfinite(portfolio_value) or portfolio_value < 0:
        raise PortfolioError("El capital para estimar costos no puede ser negativo.")
    if (
        not isinstance(alternative_name, str) or not alternative_name.strip()
        or len(alternative_name) > 80
        or any(ord(char) < 32 for char in alternative_name)
    ):
        raise PortfolioError("La alternativa de costos requiere un nombre.")
    _validate_assumptions(assumptions)
    target = validate_weights(target_weights, len(tickers))
    if current_weights is None:
        current = np.zeros(len(tickers), dtype=float)
        starting_point = "Efectivo"
    else:
        current = validate_weights(current_weights, len(tickers))
        starting_point = "Cartera actual"

    deltas = (target - current) * portfolio_value
    rows = []
    for ticker, delta in zip(tickers, deltas, strict=True):
        notional = abs(float(delta))
        if notional <= max(portfolio_value, 1.0) * 1e-10:
            continue
        commission = max(
            notional * assumptions.commission_bps / 10_000,
            assumptions.minimum_commission,
        )
        vat = commission * assumptions.vat_rate
        market_cost = notional * assumptions.market_cost_bps / 10_000
        rows.append({
            "Activo": ticker,
            "Operación": "Compra" if delta > 0 else "Venta",
            "Nominal": notional,
            "Comisión": commission,
            "IVA": vat,
            "Costo de mercado": market_cost,
            "Costo total": commission + vat + market_cost,
        })
    detail = pd.DataFrame(rows, columns=[
        "Activo", "Operación", "Nominal", "Comisión", "IVA",
        "Costo de mercado", "Costo total",
    ])
    buys = float(sum(row["Nominal"] for row in rows if row["Operación"] == "Compra"))
    sells = float(sum(row["Nominal"] for row in rows if row["Operación"] == "Venta"))
    commission = float(detail["Comisión"].sum()) if not detail.empty else 0.0
    vat = float(detail["IVA"].sum()) if not detail.empty else 0.0
    market_cost = float(detail["Costo de mercado"].sum()) if not detail.empty else 0.0
    return ImplementationCostEstimate(
        alternative_name.strip(), starting_point, detail, buys, sells,
        commission, vat, market_cost, commission + vat + market_cost,
    )
