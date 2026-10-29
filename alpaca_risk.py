"""Explicit Paper trial budgets and prospective exit plans; expected stop loss is not guaranteed."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from alpaca_order_models import decimal_value, limit_inputs
from alpaca_paper import AlpacaPaperError
from alpaca_trial_store import exit_plans, latest, stored_fills


def settings_payload(capital, max_loss, max_position, max_order_loss, cost_rate, *, started_at=None):
    values = {
        key: decimal_value(value)
        for key, value in {
            "capital": capital,
            "max_loss": max_loss,
            "max_position": max_position,
            "max_order_loss": max_order_loss,
            "cost_rate": cost_rate,
        }.items()
    }
    if (
        any(values[key] <= 0 for key in values if key != "cost_rate")
        or not 0 <= values["cost_rate"] <= Decimal("0.1")
        or values["max_position"] > values["capital"]
        or values["max_loss"] > values["capital"]
        or values["max_order_loss"] > values["max_loss"]
    ):
        raise AlpacaPaperError(
            "Configura montos positivos: posición y pérdida total ≤ capital; "
            "pérdida por orden ≤ pérdida total; costos entre 0 % y 10 %."
        )
    stamp = datetime.fromisoformat(started_at) if started_at else datetime.now(UTC)
    if stamp.tzinfo is None:
        raise AlpacaPaperError("La fecha de inicio de la prueba necesita zona horaria.")
    return {
        "version": 1,
        **{key: str(value) for key, value in values.items()},
        "started_at": stamp.isoformat(),
    }


def plan_payload(symbol, reference, stop, target, review_on, reason, *, now=None):
    symbol, _, _, _ = limit_inputs(symbol, "buy", 1, "1")
    reference = decimal_value(reference)
    stop, target = decimal_value(stop), decimal_value(target)
    today = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York")).date()
    try:
        review = date.fromisoformat(str(review_on))
    except ValueError:
        raise AlpacaPaperError("La revisión del plan necesita una fecha válida.") from None
    if (
        not 0 < stop < reference < target
        or review < today
        or not isinstance(reason, str)
        or not 3 <= len(reason.strip()) <= 1000
    ):
        raise AlpacaPaperError("El plan necesita stop < referencia < objetivo, motivo y revisión desde hoy.")
    return {
        "version": 1,
        "symbol": symbol,
        "reference": str(reference),
        "stop": str(stop),
        "target": str(target),
        "review_on": review.isoformat(),
        "reason": reason.strip(),
        "protection": "reference_only",
    }


def loss_to_stop(price, stop, quantity, cost):
    return max(Decimal(0), price * (1 + cost) - stop * (1 - cost)) * quantity


def usable_plan(plans, symbol, now):
    plan = plans.get(symbol)
    if plan is None or date.fromisoformat(plan.payload["review_on"]) < now.astimezone(
        ZoneInfo("America/New_York")
    ).date():
        raise AlpacaPaperError(f"{symbol}: guarda o revisa su plan de salida en Control de la prueba.")
    return plan


def build_trial_context(client, trial_store, order_store, issuer, subject, draft, *, now=None):
    from alpaca_fill_results import fill_results
    from alpaca_orders import order_states

    read_started = now or datetime.now(UTC)
    snapshot = client.fetch_snapshot()
    if snapshot.account.id != draft.account_id:
        raise AlpacaPaperError("La cuenta cambió al comprobar los límites de la prueba.")
    events = trial_store.load(issuer, subject, draft.account_id)
    settings = latest(events, "settings")
    if settings is None:
        raise AlpacaPaperError("Configura los límites en Control de la prueba antes de preparar otra compra.")
    cfg = settings.payload
    validated = settings_payload(
        *(cfg[key] for key in ("capital", "max_loss", "max_position", "max_order_loss", "cost_rate")),
        started_at=cfg["started_at"],
    )
    cfg = validated
    plans = exit_plans(events)
    plan = usable_plan(plans, draft.symbol, read_started)
    stop = decimal_value(plan.payload["stop"])
    if not stop < draft.limit_price < decimal_value(plan.payload["target"]):
        raise AlpacaPaperError(
            "El límite de compra debe quedar entre el stop y el objetivo del plan vigente."
        )
    states = order_states(order_store.load(issuer, subject, draft.account_id))
    cost = decimal_value(cfg["cost_rate"])
    stored_fills(events)  # An incomplete persisted download must be repaired before expanding the trial.
    fills = client.fetch_fills(min(s.draft.prepared_at for s in states) - timedelta(days=1)) if states else []
    _, issues, flows = fill_results(states, snapshot, fills, cost_rate=cost)
    if issues:
        raise AlpacaPaperError("Actualiza resultados y concilia las ejecuciones antes de ampliar la prueba.")
    started = datetime.fromisoformat(cfg["started_at"])
    closed = sum(
        (flow["net_profit"] for flow in flows if flow["side"] == "sell" and flow["timestamp"] >= started),
        Decimal(0),
    )
    base_risk, base_cost, symbol_cost = max(Decimal(0), -closed), Decimal(0), Decimal(0)
    for position in snapshot.positions:
        if position.side != "long" or position.current_price is None:
            raise AlpacaPaperError("La prueba requiere posiciones largas con un precio confirmado.")
        active = usable_plan(plans, position.symbol, read_started)
        if not decimal_value(active.payload["stop"]) < position.current_price < decimal_value(
            active.payload["target"]
        ):
            raise AlpacaPaperError(f"{position.symbol}: el precio alcanzó un nivel del plan; "
                                   "revisa la salida antes de ampliar la prueba.")
        price = max(position.entry_price, position.current_price)
        exposure = position.quantity * price * (1 + cost)
        base_cost += exposure
        base_risk += loss_to_stop(price, decimal_value(active.payload["stop"]), position.quantity, cost)
        if position.symbol == draft.symbol:
            symbol_cost += exposure
    open_orders = client.fetch_open_orders()
    for order in open_orders:
        if order["side"] != "buy":
            continue
        if order["limit"] is None or order["quantity"] is None:
            raise AlpacaPaperError(
                "Hay una compra pendiente sin precio/cantidad acotados; espera su resolución."
            )
        active = usable_plan(plans, order["symbol"], read_started)
        if not decimal_value(active.payload["stop"]) < order["limit"] < decimal_value(
            active.payload["target"]
        ):
            raise AlpacaPaperError("Una compra pendiente quedó fuera de su plan; revísala antes de ampliar.")
        # Reserve the whole pending order: positions and order reads are not an atomic broker snapshot.
        exposure = order["quantity"] * order["limit"] * (1 + cost)
        base_cost += exposure
        base_risk += loss_to_stop(
            order["limit"], decimal_value(active.payload["stop"]), order["quantity"], cost
        )
        if order["symbol"] == draft.symbol:
            symbol_cost += exposure
    known_ids = {s.receipt["id"] for s in states if s.receipt}
    seen = [o["id"] for o in open_orders if o["id"] in known_ids]
    if len(seen) > 50:
        raise AlpacaPaperError("La prueba admite hasta 50 órdenes propias pendientes para comprobar límites.")
    order_cost = draft.limit_price * draft.quantity * (1 + cost)
    order_loss = loss_to_stop(draft.limit_price, stop, Decimal(draft.quantity), cost)
    limits = {
        key: decimal_value(cfg[key]) for key in ("capital", "max_loss", "max_position", "max_order_loss")
    }
    unit_loss = loss_to_stop(draft.limit_price, stop, Decimal(1), cost)
    available = min(
        (limits["capital"] - base_cost) / (draft.limit_price * (1 + cost)),
        (limits["max_position"] - symbol_cost) / (draft.limit_price * (1 + cost)),
        (limits["max_loss"] - base_risk) / unit_loss,
        limits["max_order_loss"] / unit_loss,
    )
    context = {
        "version": 1,
        "settings_key": settings.key,
        "plan_key": plan.key,
        "settings": cfg,
        "plan": plan.payload,
        "read_started_at": read_started.isoformat(),
        "base_cost": str(base_cost),
        "base_risk": str(base_risk),
        "symbol_cost": str(symbol_cost),
        "order_cost": str(order_cost),
        "order_loss": str(order_loss),
        "seen_order_ids": seen,
        "max_quantity": max(0, min(10000, int(available.to_integral_value(rounding=ROUND_FLOOR)))),
    }
    check_claim(context, Decimal(0), Decimal(0), Decimal(0))
    return json.dumps(context, sort_keys=True, ensure_ascii=False)


def check_claim(context, extra_cost, extra_risk, extra_symbol):
    cfg = context["settings"]
    if decimal_value(context["base_cost"]) + extra_cost + decimal_value(
        context["order_cost"]
    ) > decimal_value(cfg["capital"]) or decimal_value(context["symbol_cost"]) + extra_symbol + decimal_value(
        context["order_cost"]
    ) > decimal_value(cfg["max_position"]):
        raise AlpacaPaperError("La compra supera el capital de la prueba o el límite por acción.")
    if decimal_value(context["base_risk"]) + extra_risk + decimal_value(
        context["order_loss"]
    ) > decimal_value(cfg["max_loss"]) or decimal_value(context["order_loss"]) > decimal_value(
        cfg["max_order_loss"]
    ):
        raise AlpacaPaperError(
            "La pérdida prevista al stop supera el presupuesto de la prueba o de esta orden."
        )


def extra_reservations(states, context, symbol):
    from alpaca_orders import TERMINAL

    cost = risk = by_symbol = Decimal(0)
    cutoff = datetime.fromisoformat(context["read_started_at"])
    for state in states:
        if (
            state.latest.kind == "rejected"
            or state.receipt
            and state.receipt["id"] in context["seen_order_ids"]
            or state.status in TERMINAL
            and state.latest.recorded_at <= cutoff
        ):
            continue
        if not state.draft.trial_json:
            raise AlpacaPaperError("Hay un intento previo sin límites y sin conciliar. Actualiza resultados.")
        other = json.loads(state.draft.trial_json)
        cost += decimal_value(other["order_cost"])
        risk += decimal_value(other["order_loss"])
        if state.draft.symbol == symbol:
            by_symbol += decimal_value(other["order_cost"])
    return cost, risk, by_symbol


def validate_trial_context(row, draft):
    try:
        cfg = row["settings"]
        clean = settings_payload(
            *(cfg[key] for key in ("capital", "max_loss", "max_position", "max_order_loss", "cost_rate")),
            started_at=cfg["started_at"],
        )
        plan = row["plan"]
        if (
            row["version"] != 1
            or clean != cfg
            or plan["symbol"] != draft.symbol
            or not decimal_value(plan["stop"]) < draft.limit_price < decimal_value(plan["target"])
            or len(row["seen_order_ids"]) > 50
            or any(str(UUID(value)) != value for value in row["seen_order_ids"])
        ):
            raise ValueError
        stamp = datetime.fromisoformat(row["read_started_at"])
        if stamp.tzinfo is None or not 0 <= (stamp - draft.prepared_at).total_seconds() <= 300:
            raise ValueError
        for key in ("base_cost", "base_risk", "symbol_cost"):
            if decimal_value(row[key]) < 0:
                raise ValueError
        if decimal_value(row["order_cost"]) != draft.limit_price * draft.quantity * (
            1 + decimal_value(cfg["cost_rate"])
        ) or decimal_value(row["order_loss"]) != loss_to_stop(
            draft.limit_price,
            decimal_value(plan["stop"]),
            Decimal(draft.quantity),
            decimal_value(cfg["cost_rate"]),
        ):
            raise ValueError
        if not all(isinstance(row[key], str) for key in ("settings_key", "plan_key")):
            raise ValueError
        return json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AlpacaPaperError("El presupuesto guardado de la propuesta contiene datos inválidos.") from None
