"""Explicit one-time implementation cost estimates for target allocations."""

from dataclasses import dataclass
from datetime import date

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
class OrderCostRule:
    """Documented transaction terms for one asset and direction in an analysis."""

    asset: str
    operation: str  # Compra, Venta or Ambas
    product: str
    market: str
    valid_from: date
    valid_until: date | None
    consulted_on: date
    tariff_kind: str  # PUBLICA, CONTRACTUAL or NEGOCIADA_CLIENTE
    source: str
    assumptions: ImplementationCostAssumptions


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


def _order_rule_lookup(
    tickers: tuple[str, ...], rules: tuple[OrderCostRule, ...], as_of: date,
) -> dict[tuple[str, str], OrderCostRule]:
    """Validate all declared rules and map each covered buy/sell direction exactly once."""
    lookup = {}
    for rule in rules:
        if not isinstance(rule, OrderCostRule):
            raise PortfolioError("Las reglas por orden deben ser perfiles válidos.")
        if (
            rule.asset not in tickers or not isinstance(rule.operation, str)
            or rule.operation not in {"Compra", "Venta", "Ambas"}
        ):
            raise PortfolioError("La regla debe identificar un activo y una operación válidos.")
        if (
            not isinstance(rule.tariff_kind, str)
            or rule.tariff_kind not in {"PUBLICA", "CONTRACTUAL", "NEGOCIADA_CLIENTE"}
        ):
            raise PortfolioError("El tipo de tarifa de la regla por orden no es válido.")
        for label, value in (
            ("Producto", rule.product), ("Mercado", rule.market), ("Fuente", rule.source),
        ):
            if (
                not isinstance(value, str) or not value.strip() or len(value) > 300
                or value.lstrip()[0] in "=+-@"
                or any(ord(char) < 32 for char in value)
            ):
                raise PortfolioError(f"{label} de la regla por orden no es válido.")
        if (
            type(rule.valid_from) is not date
            or (rule.valid_until is not None and type(rule.valid_until) is not date)
            or (rule.valid_until is not None and rule.valid_until < rule.valid_from)
            or type(rule.consulted_on) is not date
        ):
            raise PortfolioError("La vigencia de la regla por orden no es válida.")
        if rule.consulted_on > date.today() or rule.consulted_on > as_of:
            raise PortfolioError("La fuente de la regla se consultó después de la fecha del análisis.")
        if as_of < rule.valid_from or (rule.valid_until is not None and as_of > rule.valid_until):
            raise PortfolioError("Una regla por orden no está vigente en la fecha del análisis.")
        if not isinstance(rule.assumptions, ImplementationCostAssumptions):
            raise PortfolioError("Los costos de la regla por orden no son válidos.")
        _validate_assumptions(rule.assumptions)
        if rule.assumptions.annual_fixed_cost or rule.assumptions.annual_management_rate:
            raise PortfolioError(
                "Los costos anuales se declaran una sola vez, fuera de las reglas por orden."
            )
        operations = ("Compra", "Venta") if rule.operation == "Ambas" else (rule.operation,)
        for operation in operations:
            key = (rule.asset, operation)
            if key in lookup:
                raise PortfolioError("Hay reglas por orden duplicadas o superpuestas.")
            lookup[key] = rule
    return lookup


def estimate_implementation_cost(
    tickers: tuple[str, ...],
    target_weights,
    portfolio_value: float,
    assumptions: ImplementationCostAssumptions,
    *,
    alternative_name: str,
    current_weights=None,
    order_rules: tuple[OrderCostRule, ...] | None = None,
    as_of: date | None = None,
) -> ImplementationCostEstimate:
    """Estimate explicit costs per buy/sell order without changing target weights.

    If current weights are omitted, the starting point is cash and the entire target
    notional is purchased. Costs are additional to the target trade notionals; this is
    not a self-financing execution or a tax calculation.

    If order_rules is supplied, every nonzero order must have exactly one applicable,
    currently valid rule. The global assumptions then provide only recurring costs;
    transactional fields are ignored rather than used as an implicit fallback.
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
    if order_rules is not None and any((
        assumptions.commission_bps, assumptions.market_cost_bps,
        assumptions.vat_rate, assumptions.minimum_commission,
    )):
        raise PortfolioError(
            "Con reglas por orden, los costos transaccionales generales deben ser cero."
        )
    if as_of is not None and type(as_of) is not date:
        raise PortfolioError("La fecha del análisis de costos no es válida.")
    rules = (
        _order_rule_lookup(tickers, tuple(order_rules), as_of or date.today())
        if order_rules is not None else None
    )
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
        operation = "Compra" if delta > 0 else "Venta"
        rule = None
        if rules is not None:
            rule = rules.get((ticker, operation))
            if rule is None:
                raise PortfolioError(
                    f"Falta una regla de costo para {ticker} ({operation.lower()})."
                )
        transaction_assumptions = rule.assumptions if rule is not None else assumptions
        commission = max(
            notional * transaction_assumptions.commission_bps / 10_000,
            transaction_assumptions.minimum_commission,
        )
        vat = commission * transaction_assumptions.vat_rate
        market_cost = notional * transaction_assumptions.market_cost_bps / 10_000
        row = {
            "Activo": ticker,
            "Operación": operation,
            "Nominal": notional,
            "Comisión": commission,
            "IVA": vat,
            "Costo de mercado": market_cost,
            "Costo total": commission + vat + market_cost,
        }
        if rule is not None:
            row.update({
                "Producto": rule.product,
                "Mercado": rule.market,
                "Fuente tarifa": rule.source,
                "Tipo tarifa": rule.tariff_kind,
                "Vigente desde": rule.valid_from.isoformat(),
                "Vigente hasta": rule.valid_until.isoformat() if rule.valid_until else "",
                "Fecha consulta": rule.consulted_on.isoformat(),
                "Comisión aplicada (pb)": transaction_assumptions.commission_bps,
            })
        rows.append(row)
    columns = [
        "Activo", "Operación", "Nominal", "Comisión", "IVA",
        "Costo de mercado", "Costo total",
    ]
    if rules is not None:
        columns.extend((
            "Producto", "Mercado", "Fuente tarifa", "Tipo tarifa", "Vigente desde",
            "Vigente hasta", "Fecha consulta", "Comisión aplicada (pb)",
        ))
    detail = pd.DataFrame(rows, columns=columns)
    buys = float(sum(row["Nominal"] for row in rows if row["Operación"] == "Compra"))
    sells = float(sum(row["Nominal"] for row in rows if row["Operación"] == "Venta"))
    commission = float(detail["Comisión"].sum()) if not detail.empty else 0.0
    vat = float(detail["IVA"].sum()) if not detail.empty else 0.0
    market_cost = float(detail["Costo de mercado"].sum()) if not detail.empty else 0.0
    return ImplementationCostEstimate(
        alternative_name.strip(), starting_point, detail, buys, sells,
        commission, vat, market_cost, commission + vat + market_cost,
    )
