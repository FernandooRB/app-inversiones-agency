"""Two-phase manual Paper execution: fresh checks, durable claim, one POST, reconciliation."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from alpaca_order_models import LimitDraft, decimal_value, limit_inputs, new_draft, validate_receipt
from alpaca_order_store import OrderAlreadyRecorded, OrderEvent
from alpaca_paper import AlpacaPaperError, PaperOrderRejected

TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}


@dataclass(frozen=True)
class OrderState:
    draft: LimitDraft
    intent: OrderEvent
    latest: OrderEvent

    @property
    def unresolved(self):
        return self.latest.kind in ("intent", "unknown")

    @property
    def receipt(self):
        return self.latest.payload if self.latest.kind in ("accepted", "observed") else None

    @property
    def status(self):
        if self.receipt:
            return self.receipt["status"]
        return "solicitud_rechazada" if self.latest.kind == "rejected" else "sin_confirmar"


def order_states(events: list[OrderEvent]) -> list[OrderState]:
    states = {}
    for event in sorted(events, key=lambda item: item.sequence):
        key = event.client_order_id
        if event.kind == "intent":
            if key in states:
                raise AlpacaPaperError("El registro contiene un intento Paper duplicado.")
            draft = LimitDraft.from_json(event.account_id, event.payload)
            states[key] = OrderState(draft, event, event)
            continue
        previous = states.get(key)
        if previous is None or event.account_id != previous.draft.account_id:
            raise AlpacaPaperError("El registro contiene una observación sin su intento Paper.")
        if event.kind in ("accepted", "observed"):
            receipt = validate_receipt(previous.draft, event.payload)
            old = previous.receipt
            if old:
                if receipt["id"] != old["id"]:
                    raise AlpacaPaperError("Alpaca devolvió identificadores distintos para el mismo intento.")
                if decimal_value(receipt["filled_qty"]) < decimal_value(old["filled_qty"]):
                    continue
                if old["status"] in TERMINAL and receipt["status"] not in TERMINAL:
                    continue
                if old["status"] == "filled" and receipt["status"] != "filled":
                    continue
                if old.get("filled_at") and not receipt.get("filled_at") and receipt["status"] == "filled":
                    receipt["filled_at"] = old["filled_at"]
                    event = replace(event, payload=receipt)
        elif previous.receipt:
            # A failed lookup never erases an earlier broker confirmation.
            continue
        states[key] = OrderState(previous.draft, previous.intent, event)
    return list(states.values())


def _load(store, issuer, subject, account_id):
    return order_states(store.load(issuer, subject, account_id))


def _state(store, issuer, subject, draft):
    state = next((item for item in _load(store, issuer, subject, draft.account_id)
                  if item.draft.client_order_id == draft.client_order_id), None)
    if state is None:
        raise AlpacaPaperError("No se pudo confirmar el intento para este usuario y cuenta.")
    return state


def _checks(client, symbol, side, quantity, price, *, account_id=None, now=None):
    symbol, side, quantity, price = limit_inputs(symbol, side, quantity, price)
    snapshot = client.fetch_snapshot()
    account = snapshot.account
    if account_id is not None and account.id != account_id:
        raise AlpacaPaperError("La cuenta cambió desde la propuesta. Prepara una nueva antes de enviar.")
    if (account.status != "ACTIVE" or account.currency != "USD" or account.account_blocked
            or account.trading_blocked or account.trade_suspended is not False):
        raise AlpacaPaperError("La cuenta no confirmó disponibilidad para negociar esta prueba Paper.")
    asset = client.order_resource("asset", symbol)
    if (not isinstance(asset, dict) or asset.get("symbol") != symbol
            or asset.get("class") != "us_equity" or asset.get("tradable") is not True
            or asset.get("status") != "active"):
        raise AlpacaPaperError("El símbolo no es una acción de EE. UU. activa y negociable en Alpaca.")
    position = next((p for p in snapshot.positions if p.symbol == symbol), None)
    if side == "buy":
        if account.cash_buying_power is None:
            raise AlpacaPaperError("Alpaca no confirmó el poder de compra disponible sin margen.")
        if quantity * price > min(account.cash, account.buying_power, account.cash_buying_power):
            raise AlpacaPaperError("El importe supera el efectivo o poder de compra simulado disponible.")
        if position and position.side == "short":
            raise AlpacaPaperError("Esta prueba trabaja con posiciones largas; revisa la posición existente.")
    elif (position is None or position.side != "long" or position.available_quantity is None
            or quantity > min(position.quantity, position.available_quantity)):
        raise AlpacaPaperError("No hay suficientes títulos largos disponibles para esta venta simulada.")
    clock = client.order_resource("clock")
    return new_draft(account.id, symbol, side, quantity, price, clock, now=now)


def prepare_order(client, store, issuer, subject, symbol, side, quantity, price, *, now=None,
                  signal_store=None, signal_key=None, trial_store=None):
    draft = _checks(client, symbol, side, quantity, price, now=now)
    if any(item.unresolved for item in _load(store, issuer, subject, draft.account_id)):
        raise AlpacaPaperError("Hay un envío sin confirmar. Consulta su estado antes de preparar otra orden.")
    if signal_key is not None:
        from alpaca_signal_context import saved_context

        if signal_store is None:
            raise AlpacaPaperError("La referencia requiere verificar la bitácora de señales.")
        draft = replace(draft, research_json=saved_context(
            signal_store, issuer, subject, signal_key, draft.symbol, draft.prepared_at))
    if trial_store is not None and side == "buy":
        from alpaca_risk import build_trial_context

        draft = replace(draft, trial_json=build_trial_context(
            client, trial_store, store, issuer, subject, draft, now=now))
    return draft


def reconcile_order(client, store, issuer, subject, account_id, client_order_id):
    states = _load(store, issuer, subject, account_id)
    state = next((s for s in states if s.draft.client_order_id == client_order_id), None)
    if state is None:
        raise AlpacaPaperError("Este usuario no tiene ese intento registrado para la cuenta.")
    if state.latest.kind == "rejected":
        return state
    if client.fetch_snapshot().account.id != account_id:
        raise AlpacaPaperError("La cuenta conectada no coincide con el intento que quieres consultar.")
    try:
        row = client.order_resource("order", client_order_id)
        if row is None:
            raise AlpacaPaperError("Alpaca aún no devuelve una orden con este identificador.")
        receipt = validate_receipt(state.draft, row)
    except AlpacaPaperError:
        store.append(issuer, subject, account_id, client_order_id,
                     "unknown", {"reason": "lookup_unconfirmed"})
        raise AlpacaPaperError(
            "No se pudo confirmar la orden. No se reenvió; vuelve a consultar o revisa el panel Paper."
        ) from None
    store.append(issuer, subject, account_id, client_order_id, "observed", receipt)
    return _state(store, issuer, subject, state.draft)


def submit_order(client, store, issuer, subject, draft: LimitDraft, *, confirmed: bool, now=None,
                 signal_store=None, trial_store=None):
    if confirmed is not True:
        raise AlpacaPaperError("Confirma los datos de la orden de simulación antes de enviarla.")
    states = _load(store, issuer, subject, draft.account_id)
    existing = next((s for s in states if s.draft.client_order_id == draft.client_order_id), None)
    if existing:
        return existing  # A repeated click, browser reload or second session never repeats the POST.
    if any(s.unresolved for s in states):
        raise AlpacaPaperError("Hay un envío sin confirmar. Consulta su estado antes de enviar otro.")
    checked_at = now or datetime.now(UTC)
    if draft.prepared_at.tzinfo is None or not 0 <= (checked_at - draft.prepared_at).total_seconds() <= 300:
        raise AlpacaPaperError("La propuesta venció. Prepara otra para revisar datos recientes.")
    checked = _checks(client, draft.symbol, draft.side, draft.quantity, draft.limit_price,
                      account_id=draft.account_id, now=now)
    if checked.market_open != draft.market_open or checked.next_open != draft.next_open:
        raise AlpacaPaperError("El horario de mercado cambió. Prepara y revisa una nueva propuesta.")
    if draft.research_json:
        from alpaca_signal_context import saved_context

        if signal_store is None or saved_context(signal_store, issuer, subject,
                json.loads(draft.research_json)["key"], draft.symbol,
                draft.prepared_at) != draft.research_json:
            raise AlpacaPaperError("La señal de referencia cambió o no pudo verificarse.")
    if trial_store is not None and draft.side == "buy" or draft.trial_json:
        from alpaca_risk import build_trial_context

        if trial_store is None or draft.trial_json is None:
            raise AlpacaPaperError("Prepara otra compra con límites y un plan de salida guardados.")
        fresh = build_trial_context(client, trial_store, store, issuer, subject, draft, now=now)
        old, current = json.loads(draft.trial_json), json.loads(fresh)
        if any(old[key] != current[key] for key in ("settings_key", "plan_key")):
            raise AlpacaPaperError("Los límites o el plan cambiaron. Prepara otra propuesta.")
        draft = replace(draft, trial_json=fresh)
    if ((now or datetime.now(UTC)) - draft.prepared_at).total_seconds() > 300:
        raise AlpacaPaperError("La propuesta venció durante la comprobación. Prepara otra.")
    try:
        store.append(issuer, subject, draft.account_id, draft.client_order_id, "intent", draft.to_json())
    except OrderAlreadyRecorded:
        return _state(store, issuer, subject, draft)
    try:
        row = client.submit_limit_order(draft)
        receipt = validate_receipt(draft, row)
    except PaperOrderRejected as exc:
        store.append(issuer, subject, draft.account_id, draft.client_order_id,
                     "rejected", {"reason": "provider_rejected", "http_status": exc.status_code})
        return _state(store, issuer, subject, draft)
    except AlpacaPaperError:
        # GET reconciliation only; never repeat a submission after a timeout or ambiguous response.
        try:
            return reconcile_order(client, store, issuer, subject, draft.account_id, draft.client_order_id)
        except AlpacaPaperError:
            return _state(store, issuer, subject, draft)
    try:
        store.append(issuer, subject, draft.account_id, draft.client_order_id, "accepted", receipt)
    except AlpacaPaperError:
        raise AlpacaPaperError(
            "Alpaca respondió al envío, pero no se guardó el estado. Consulta el intento antes de continuar."
        ) from None
    return _state(store, issuer, subject, draft)
