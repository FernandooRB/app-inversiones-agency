"""Cash-flow-aware historical performance. No inference of flows from NAV changes."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from portfolio_core import PortfolioError


@dataclass(frozen=True)
class Flow:
    day: date
    amount: float  # positive contribution to account, negative withdrawal
    timing: str = "UNKNOWN"


def valuation_requirements(start: date, end: date, flows: list[Flow], *, available_dates=()) -> dict:
    """Calendar coverage for this engine's TWR convention, not approval of NAV or flows.

    Amounts, currencies and FX are not assessed here. UNKNOWN timing never becomes
    BOD/EOD merely because a convenient closing value is available.
    """
    if any(not isinstance(day, date) or isinstance(day, datetime) for day in (start, end)) or start >= end:
        raise PortfolioError("El calendario requiere dos fechas de cierre distintas y ordenadas, sin hora.")
    if any(
        not isinstance(flow, Flow)
        or not isinstance(flow.day, date)
        or isinstance(flow.day, datetime)
        or flow.timing not in {"BOD", "EOD", "UNKNOWN"}
        for flow in flows
    ):
        raise PortfolioError("Hay flujos con fecha o momento inválidos.")
    if any(flow.day <= start or flow.day > end for flow in flows):
        raise PortfolioError("Los flujos deben ser posteriores al cierre inicial y hasta el cierre final.")
    known = set()
    try:
        for value in available_dates:
            if not isinstance(value, (str, date, np.datetime64)):
                raise ValueError
            parsed = pd.Timestamp(value)
            if pd.isna(parsed) or parsed.tzinfo is not None or parsed != parsed.normalize():
                raise ValueError
            known.add(parsed.date())
    except (ValueError, TypeError, OverflowError) as exc:
        raise PortfolioError("Las fechas disponibles deben ser cierres sin hora ni zona horaria.") from exc
    planned = {}

    def add(day, reason, *, required=True):
        row = planned.setdefault(day, {"required": False, "reasons": set()})
        row["required"] |= required
        row["reasons"].add(reason)

    add(start, "Cierre inicial")
    add(end, "Cierre final")
    for flow in flows:
        add(flow.day, "Cierre en fecha de flujo")
        if flow.timing == "BOD":
            add(flow.day - timedelta(days=1), "Cierre anterior a flujo BOD")
        elif flow.timing == "UNKNOWN":
            add(flow.day - timedelta(days=1), "Necesario si el flujo se confirma BOD", required=False)
    rows = [
        {
            "date": day.isoformat(),
            "required": row["required"],
            "available": day in known,
            "reasons": sorted(row["reasons"]),
        }
        for day, row in sorted(planned.items())
    ]
    unknown = sum(flow.timing == "UNKNOWN" for flow in flows)
    missing = [row["date"] for row in rows if row["required"] and not row["available"]]
    conditional = [row["date"] for row in rows if not row["required"] and not row["available"]]
    return {
        "schema": 1,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
        "unknown_flow_count": unknown,
        "unknown_flow_dates": sorted({f.day.isoformat() for f in flows if f.timing == "UNKNOWN"}),
        "missing_required_dates": missing,
        "missing_conditional_dates": conditional,
        "twr_coverage_ready": not missing and not unknown,
    }


def normalize_valuations(valuations: pd.Series) -> pd.Series:
    """Validate closing NAV without filling dates or shifting time zones."""
    if not isinstance(valuations, pd.Series):
        raise PortfolioError("Las valuaciones deben ser una serie de cierres fechados.")
    nav = valuations.copy()
    try:
        nav.index = pd.to_datetime(nav.index)
        nav = nav.astype(float).sort_index()
    except (ValueError, TypeError, OverflowError) as exc:
        raise PortfolioError("Las valuaciones deben tener fecha e importe numérico.") from exc
    if (
        len(nav) < 2
        or nav.index.has_duplicates
        or nav.index.hasnans
        or not np.isfinite(nav).all()
        or (nav <= 0).any()
    ):
        raise PortfolioError("Se requieren cierres positivos, finitos y sin fechas vacías o duplicadas.")
    if nav.index.tz is not None or not nav.index.equals(nav.index.normalize()):
        raise PortfolioError("Usa fechas de cierre sin hora ni zona horaria en las valuaciones.")
    return nav


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
    nav = normalize_valuations(valuations)
    first, last = nav.index[0].date(), nav.index[-1].date()
    requirements = valuation_requirements(first, last, flows, available_dates=nav.index)
    if any(not np.isfinite(flow.amount) for flow in flows):
        raise PortfolioError("Hay flujos con fecha, importe o momento inválidos.")
    mw = xirr(
        [(first, -float(nav.iloc[0])), *[(f.day, -f.amount) for f in flows], (last, float(nav.iloc[-1]))]
    )
    twr = None
    if requirements["twr_coverage_ready"]:
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
        "valuation_requirements": requirements,
    }
