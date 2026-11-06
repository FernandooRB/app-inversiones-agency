"""Cash-flow-aware historical performance. No inference of flows from NAV changes."""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from portfolio_core import PortfolioError


@dataclass(frozen=True)
class Flow:
    day: date
    amount: float  # positive contribution to account, negative withdrawal
    timing: str = "UNKNOWN"


def xirr(cashflows: list[tuple[date, float]]) -> dict:
    """365-day money-weighted return; ambiguous sign patterns require review."""
    amounts = (
        pd.Series(
            [float(value) for _, value in cashflows], index=pd.to_datetime([day for day, _ in cashflows])
        )
        .groupby(level=0)
        .sum()
        .sort_index()
    )
    amounts = amounts[amounts != 0]
    if len(amounts) < 2 or not np.isfinite(amounts).all() or not (amounts.min() < 0 < amounts.max()):
        return {"value": None, "status": "FLUJOS_INSUFICIENTES"}
    signs = np.sign(amounts.to_numpy())
    if np.count_nonzero(signs[1:] != signs[:-1]) != 1:
        return {"value": None, "status": "MULTIPLES_RAICES_POSIBLES"}
    years = (amounts.index - amounts.index[0]).days.to_numpy() / 365.0
    if years[-1] == 0:
        return {"value": None, "status": "PERIODO_INSUFICIENTE"}
    values = amounts.to_numpy() / np.max(np.abs(amounts.to_numpy()))

    def scaled_npv(log_rate):
        powers = -years * log_rate
        return float(np.dot(values, np.exp(powers - powers.max())))

    try:
        root = brentq(scaled_npv, -20, 20, xtol=1e-12)
    except ValueError:
        return {"value": None, "status": "SIN_RAIZ_EN_RANGO"}
    return {"value": float(np.expm1(root)), "status": "CALCULADA"}


def performance(valuations: pd.Series, flows: list[Flow]) -> dict:
    """TWR links boundary-adjusted subperiods; missing flow-date values block TWR.

    A BOD flow requires the previous calendar day's closing value. An EOD flow
    requires that day's post-flow closing value. Unknown timing blocks TWR,
    while dated flows can still support XIRR. This is not a GIPS compliance claim.
    """
    nav = valuations.copy()
    try:
        nav.index = pd.to_datetime(nav.index)
        nav = nav.astype(float).sort_index()
    except (ValueError, TypeError) as exc:
        raise PortfolioError("Las valuaciones deben tener fecha e importe numérico.") from exc
    if len(nav) < 2 or nav.index.has_duplicates or not np.isfinite(nav).all() or (nav <= 0).any():
        raise PortfolioError("Se requieren cierres positivos, finitos y sin fechas duplicadas.")
    if any(moment.time().isoformat() != "00:00:00" for moment in nav.index):
        raise PortfolioError("Usa fechas de cierre sin hora en las valuaciones.")
    first, last = nav.index[0].date(), nav.index[-1].date()
    if any(
        not isinstance(flow.day, date)
        or not np.isfinite(flow.amount)
        or flow.timing not in {"BOD", "EOD", "UNKNOWN"}
        for flow in flows
    ):
        raise PortfolioError("Hay flujos con fecha, importe o momento inválidos.")
    if any(flow.day <= first or flow.day > last for flow in flows):
        raise PortfolioError("Los flujos deben ser posteriores al cierre inicial y hasta el cierre final.")
    mw = xirr(
        [(first, -float(nav.iloc[0])), *[(f.day, -f.amount) for f in flows], (last, float(nav.iloc[-1]))]
    )
    known_days = {moment.date() for moment in nav.index}
    missing = [
        flow
        for flow in flows
        if flow.timing == "UNKNOWN"
        or flow.day not in known_days
        or (flow.timing == "BOD" and flow.day - timedelta(days=1) not in known_days)
    ]
    twr = None
    if not missing:
        linked = 1.0
        for index in range(1, len(nav)):
            day = nav.index[index].date()
            start = sum(f.amount for f in flows if f.day == day and f.timing == "BOD")
            end = sum(f.amount for f in flows if f.day == day and f.timing == "EOD")
            denominator = float(nav.iloc[index - 1]) + start
            numerator = float(nav.iloc[index]) - end
            if denominator <= 0 or numerator < 0:
                raise PortfolioError(
                    "Los flujos no son compatibles con una valuación positiva del subperiodo."
                )
            linked *= numerator / denominator
        twr = linked - 1
    net_flow = sum(flow.amount for flow in flows)
    return {
        "twr": twr,
        "twr_status": "CALCULADA" if twr is not None else "FALTAN_VALUACIONES_O_MOMENTO",
        "xirr": mw["value"],
        "xirr_status": mw["status"],
        "net_flow": net_flow,
        "gain": float(nav.iloc[-1] - nav.iloc[0] - net_flow),
        "days": (last - first).days,
    }
