"""Meaningful, deduplicated in-app observations; no background messaging or trading."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from alpaca_trial_store import exit_plans, latest, stable_key
from technical_analysis import BUY, SELL, STRATEGY_VERSION, UNAVAILABLE


def observation(history, snapshot):
    return {
        "symbol": snapshot.symbol,
        "session": str(snapshot.as_of or ""),
        "signal": snapshot.signal,
        "reason": snapshot.reason,
        "fetched_at": history.fetched_at.isoformat(),
        "strategy_version": STRATEGY_VERSION,
        "currency": history.currency,
    }


def observation_key(row):
    return stable_key(
        "observation", "|".join(row[k] for k in ("symbol", "session", "signal", "strategy_version"))
    )


def active_alerts(snapshot, events, observations, *, now=None):
    now = now or datetime.now(UTC)
    day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    results = []

    def add(kind, symbol, token, message, severity="Atención"):
        results.append(
            {
                "key": stable_key("alert", f"{kind}|{symbol}|{token}"),
                "kind": kind,
                "symbol": symbol,
                "message": message,
                "severity": severity,
            }
        )

    if now - snapshot.fetched_at > timedelta(minutes=15):
        add("stale_account", "Cuenta", day, "La cuenta tiene más de 15 minutos sin actualizar.")
    settings = latest(events, "settings")
    plans = exit_plans(events)
    exposure = Decimal(0)
    for position in snapshot.positions:
        if position.current_price is None:
            add(
                "missing_price",
                position.symbol,
                day,
                "Falta un precio confirmado para valorar esta posición.",
            )
            continue
        mark = position.current_price
        exposure += max(position.entry_price, mark) * position.quantity
        plan = plans.get(position.symbol)
        if plan is None:
            add("missing_plan", position.symbol, day, "La posición necesita un plan de salida guardado.")
            continue
        value = plan.payload
        if mark <= Decimal(value["stop"]):
            add(
                "stop",
                position.symbol,
                plan.key + day,
                f"Precio {mark:,.2f} USD: alcanzó o quedó por debajo del stop de referencia "
                f"{Decimal(value['stop']):,.2f} USD. Revisa la posición.",
                "Revisar ahora",
            )
        if mark >= Decimal(value["target"]):
            add(
                "target",
                position.symbol,
                plan.key + day,
                f"Precio {mark:,.2f} USD: alcanzó el objetivo de referencia "
                f"{Decimal(value['target']):,.2f} USD. Revisa la posición.",
            )
        if day > value["review_on"]:
            add(
                "review",
                position.symbol,
                plan.key + day,
                f"Venció la revisión prevista para {value['review_on']}.",
            )
        if settings and max(position.entry_price, mark) * position.quantity > Decimal(
            settings.payload["max_position"]
        ):
            add(
                "position_limit",
                position.symbol,
                settings.key + day,
                "La exposición consultada supera el límite configurado por acción.",
                "Revisar ahora",
            )
    if settings and exposure > Decimal(settings.payload["capital"]):
        add(
            "capital",
            "Cuenta",
            settings.key + day,
            "Las posiciones consultadas superan el capital asignado a la prueba.",
            "Revisar ahora",
        )
    for current in observations:
        symbol = current["symbol"]
        if current["signal"] == UNAVAILABLE:
            add("data", symbol, day, current["reason"])
            continue
        if now - datetime.fromisoformat(current["fetched_at"]) > timedelta(hours=1):
            add(
                "stale_signal",
                symbol,
                day,
                "La consulta de la señal tiene más de una hora; actualiza sus datos.",
            )
        key = observation_key(current)
        previous = next(
            (
                e.payload
                for e in reversed(events)
                if e.kind == "observation" and e.payload["symbol"] == symbol and e.key != key
            ),
            None,
        )
        if previous and previous["signal"] != current["signal"]:
            add(
                "signal_change",
                symbol,
                key,
                f"La lectura pasó de {previous['signal']} a {current['signal']} · "
                f"sesión {current['session']}.",
            )
        elif previous is None and current["signal"] in (BUY, SELL):
            add("signal", symbol, key, f"Señal {current['signal']} · sesión {current['session']}.")
    return results
