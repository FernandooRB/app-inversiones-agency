"""FIFO from individual executions, including partial orders, with explicit assumed costs."""

from __future__ import annotations

import json
from decimal import Decimal

from alpaca_orders import TERMINAL
from alpaca_paper import AlpacaPaperError
from alpaca_signal_context import alignment, reference_levels

ZERO = Decimal(0)


def fill_results(states, snapshot, fills, *, cost_rate=Decimal("0.0035")):
    cost_rate = Decimal(str(cost_rate))
    if not cost_rate.is_finite() or not ZERO <= cost_rate <= Decimal("0.1"):
        raise AlpacaPaperError("El supuesto de costos por lado debe estar entre 0 % y 10 %.")
    if len({fill.id for fill in fills}) != len(fills):
        raise AlpacaPaperError("Hay ejecuciones duplicadas; no se calcula un resultado parcial.")
    by_order = {state.receipt["id"]: state for state in states if state.receipt}
    positions = {position.symbol: position for position in snapshot.positions}
    symbols = {state.draft.symbol for state in states}
    rows, issues, flows = [], [], []
    for symbol in sorted(symbols):
        own = [state for state in states if state.draft.symbol == symbol]
        trades = sorted((f for f in fills if f.symbol == symbol), key=lambda f: (f.timestamp, f.id))
        invalid = None
        for state in own:
            known = state.receipt
            if known is None:
                if state.unresolved:
                    invalid = "hay un intento sin confirmar"
                continue
            executions = [f for f in trades if f.order_id == known["id"]]
            quantity = sum((f.quantity for f in executions), ZERO)
            notional = sum((f.price * f.quantity for f in executions), ZERO)
            expected = Decimal(known["filled_qty"])
            if (
                quantity != expected
                or expected
                and abs(notional - expected * Decimal(known["filled_avg_price"]))
                > expected * Decimal("0.0001")
                or any(
                    f.side != state.draft.side or f.timestamp < state.draft.prepared_at for f in executions
                )
            ):
                invalid = "faltan ejecuciones individuales o no coinciden con la orden confirmada"
                break
        if invalid:
            issues.append(f"{symbol}: {invalid}. Pulsa Actualizar resultados.")
            continue
        if not trades:
            if positions.get(symbol) or any(
                o.symbol == symbol and o.filled_quantity > 0 for o in snapshot.orders
            ):
                issues.append(f"{symbol}: falta conciliar la posición con sus ejecuciones. "
                              "Pulsa Actualizar resultados.")
            continue
        lots, entries, symbol_flows = [], {}, []
        for fill in trades:
            state = by_order.get(fill.order_id)
            if fill.side == "buy":
                owned = state is not None and state.draft.side == "buy"
                entry_id = state.draft.client_order_id if owned else None
                lots.append(
                    {
                        "remaining": fill.quantity,
                        "price": fill.price,
                        "entry_id": entry_id,
                        "timestamp": fill.timestamp,
                    }
                )
                if not owned:
                    continue
                if entry_id not in entries:
                    entries[entry_id] = {
                        "state": state,
                        "quantity": ZERO,
                        "basis": ZERO,
                        "count": 0,
                        "closed_qty": ZERO,
                        "closed_basis": ZERO,
                        "gross": ZERO,
                        "net": ZERO,
                        "first_at": fill.timestamp,
                        "last_exit_at": None,
                        "exit_qualified": True,
                    }
                entry = entries[entry_id]
                entry["quantity"] += fill.quantity
                entry["basis"] += fill.price * fill.quantity
                entry["count"] += 1
                symbol_flows.append(
                    {
                        "side": "buy",
                        "symbol": symbol,
                        "entry_id": entry_id,
                        "timestamp": fill.timestamp,
                        "quantity": fill.quantity,
                        "price": fill.price,
                        "net_cash": -fill.price * fill.quantity * (1 + cost_rate),
                        "net_profit": ZERO,
                    }
                )
                continue
            quantity = fill.quantity
            if sum((lot["remaining"] for lot in lots), ZERO) < quantity:
                invalid = "el periodo no contiene compras suficientes para reconstruir la venta"
                break
            for lot in lots:
                used = min(quantity, lot["remaining"])
                lot["remaining"] -= used
                quantity -= used
                if used and lot["entry_id"] is not None:
                    entry = entries[lot["entry_id"]]
                    gross = used * (fill.price - lot["price"])
                    net = used * (fill.price * (1 - cost_rate) - lot["price"] * (1 + cost_rate))
                    entry["closed_qty"] += used
                    entry["closed_basis"] += used * lot["price"]
                    entry["gross"] += gross
                    entry["net"] += net
                    entry["last_exit_at"] = fill.timestamp
                    entry["exit_qualified"] &= state is not None and alignment(state.draft).startswith(
                        "Coincide"
                    )
                    symbol_flows.append(
                        {
                            "side": "sell",
                            "symbol": symbol,
                            "entry_id": lot["entry_id"],
                            "timestamp": fill.timestamp,
                            "quantity": used,
                            "price": fill.price,
                            "net_cash": used * fill.price * (1 - cost_rate),
                            "net_profit": net,
                        }
                    )
                if quantity == 0:
                    break
        if invalid:
            issues.append(f"{symbol}: {invalid}; no se presenta FIFO incompleto.")
            continue
        position = positions.get(symbol)
        remaining = sum((lot["remaining"] for lot in lots), ZERO)
        broker_qty = position.quantity if position and position.side == "long" else ZERO
        reconciled = remaining == broker_qty
        if not reconciled:
            issues.append(
                f"{symbol}: la cantidad reconstruida no coincide con Alpaca; "
                "el resultado abierto queda pendiente de conciliación."
            )
        for entry_id, entry in entries.items():
            state = entry["state"]
            opened = [lot for lot in lots if lot["entry_id"] == entry_id]
            quantity = sum((lot["remaining"] for lot in opened), ZERO)
            basis = sum((lot["remaining"] * lot["price"] for lot in opened), ZERO)
            mark = position.current_price if reconciled and position else None
            gross_open = (
                quantity * mark - basis if quantity and mark is not None else ZERO if not quantity else None
            )
            net_open = (
                quantity * mark * (1 - cost_rate) - basis * (1 + cost_rate)
                if quantity and mark is not None
                else ZERO
                if not quantity
                else None
            )
            average = entry["basis"] / entry["quantity"]
            levels = reference_levels(state.draft, average)
            context = json.loads(state.draft.trial_json) if state.draft.trial_json else None
            rows.append(
                {
                    "Símbolo": symbol,
                    "ID de entrada": entry_id,
                    "Clasificación": alignment(state.draft),
                    "Compradas": entry["quantity"],
                    "Abiertas": quantity,
                    "Entrada media · USD": average,
                    "Resultado abierto · USD": gross_open,
                    "Neto abierto estimado · USD": net_open,
                    "Rendimiento abierto · %": 100 * gross_open / basis
                    if basis and gross_open is not None
                    else None,
                    "Resultado cerrado · USD": entry["gross"] if entry["closed_qty"] else None,
                    "Neto cerrado estimado · USD": entry["net"] if entry["closed_qty"] else None,
                    "Rendimiento cerrado · %": 100 * entry["gross"] / entry["closed_basis"]
                    if entry["closed_basis"]
                    else None,
                    "Costos estimados cerrados · USD": entry["gross"] - entry["net"]
                    if entry["closed_qty"]
                    else None,
                    "Stop de referencia · USD": levels[0] if levels else None,
                    "Objetivo de referencia · USD": levels[1] if levels else None,
                    "Ejecuciones de entrada": entry["count"],
                    "Cerrada": quantity == 0 and state.status in TERMINAL,
                    "Salida con señal": entry["exit_qualified"] if entry["closed_qty"] else None,
                    "Primera ejecución UTC": entry["first_at"],
                    "Última salida UTC": entry["last_exit_at"],
                    "Presupuesto de origen": context["settings_key"] if context else None,
                    "Capital de referencia · USD": Decimal(context["settings"]["max_position"])
                    if context
                    else None,
                }
            )
        flows.extend(symbol_flows)
    return rows, issues, flows
