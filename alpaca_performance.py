"""Separate prospective entries from manual tests, with price/cost comparison on completed daily bars."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from alpaca_paper import AlpacaPaperError


def cohort_summary(rows):
    results = []
    for qualified, name in ((True, "Entradas con señal previa"), (False, "Pruebas manuales/técnicas")):
        selected = [r for r in rows if r["Clasificación"].startswith("Coincide") == qualified]
        closed = [r for r in selected if r["Cerrada"]]
        winners = sum(r["Neto cerrado estimado · USD"] > 0 for r in closed)
        results.append(
            {
                "Grupo": name,
                "Entradas": len(selected),
                "Cerradas": len(closed),
                "Abiertas o pendientes": len(selected) - len(closed),
                "Ganadoras · %": 100 * winners / len(closed) if closed else None,
                "Neto cerrado estimado · USD": sum(
                    (r["Neto cerrado estimado · USD"] for r in closed), Decimal(0)
                )
                if closed
                else None,
            }
        )
    return results


def compare_to_hold(rows, flows, symbol, bars, settings_key, cost_rate):
    """Use the same captured asset budget and initial entry quantity for both alternatives."""
    selected = [
        r
        for r in rows
        if r["Símbolo"] == symbol
        and r["Clasificación"].startswith("Coincide")
        and r["Presupuesto de origen"] == settings_key
    ]
    if not selected or bars.empty or "Close" not in bars:
        raise AlpacaPaperError(
            "Todavía no hay entradas de estrategia y cierres diarios para esta comparación."
        )
    capital = selected[0]["Capital de referencia · USD"]
    if capital is None or capital <= 0 or any(r["Capital de referencia · USD"] != capital for r in selected):
        raise AlpacaPaperError(
            "La comparación necesita un único presupuesto capturado antes de las entradas."
        )
    ids = {r["ID de entrada"] for r in selected}
    trades = sorted((f for f in flows if f["entry_id"] in ids), key=lambda f: f["timestamp"])
    if not trades:
        raise AlpacaPaperError("No hay ejecuciones de estrategia conciliadas para este periodo.")
    zone = ZoneInfo("America/New_York")
    start = trades[0]["timestamp"].astimezone(zone).date()
    if bars.index[0].date() > start:
        raise AlpacaPaperError("El historial no cubre la primera entrada de la comparación.")
    days = bars[bars.index.date >= start]
    if days.empty:
        raise AlpacaPaperError("La primera entrada todavía no tiene una sesión diaria terminada.")
    first_id = trades[0]["entry_id"]
    first_buys = [f for f in trades if f["entry_id"] == first_id and f["side"] == "buy"]
    cash = bh_cash = capital
    qty = bh_qty = Decimal(0)
    pending = list(trades)
    points = []
    cost = Decimal(str(cost_rate))
    for index, bar in days.iterrows():
        day = index.date()
        while pending and pending[0]["timestamp"].astimezone(zone).date() <= day:
            flow = pending.pop(0)
            cash += flow["net_cash"]
            qty += flow["quantity"] if flow["side"] == "buy" else -flow["quantity"]
            if flow in first_buys:
                bh_cash += flow["net_cash"]
                bh_qty += flow["quantity"]
        if cash < Decimal("-0.01") or bh_cash < Decimal("-0.01") or qty < 0:
            raise AlpacaPaperError("El presupuesto no cubre los flujos; no se genera una curva parcial.")
        price = Decimal(str(bar["Close"]))
        if not price.is_finite() or price <= 0:
            raise AlpacaPaperError("Faltan cierres válidos para comparar el rendimiento.")
        points.append(
            {
                "Sesión": datetime.combine(day, datetime.min.time()),
                "Estrategia · USD": float(cash + qty * price * (1 - cost)),
                "Mantener primera entrada · USD": float(bh_cash + bh_qty * price * (1 - cost)),
            }
        )
    frame = pd.DataFrame(points).set_index("Sesión")
    peak = frame["Estrategia · USD"].cummax().clip(lower=float(capital))
    drawdown = ((frame["Estrategia · USD"] / peak) - 1).min()
    return frame, {
        "capital": capital,
        "max_drawdown": float(drawdown),
        "strategy_return": frame.iloc[-1, 0] / float(capital) - 1,
        "hold_return": frame.iloc[-1, 1] / float(capital) - 1,
        "as_of": days.index[-1].date(),
    }
