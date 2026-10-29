"""Price-only FIFO research for this app's confirmed, completely filled Paper orders."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from alpaca_signal_context import alignment, reference_levels


def paper_results(states, snapshot):
    """Keep broker account marks separate; reject ambiguous/partial lot reconstruction."""
    groups = defaultdict(list)
    for state in states:
        groups[state.draft.symbol].append(state)
    positions = {position.symbol: position for position in snapshot.positions}
    rows, limitations = [], []
    for symbol, orders in sorted(groups.items()):
        executions = [s for s in orders if s.receipt and Decimal(s.receipt["filled_qty"]) > 0]
        if not executions:
            continue
        if any(s.status != "filled" for s in executions):
            limitations.append(f"{symbol}: hay órdenes con ejecución parcial; "
                               "este modelo requiere ejecuciones completas.")
            continue
        has_sales = any(s.draft.side == "sell" for s in executions)
        if has_sales and any(not s.receipt.get("filled_at") for s in executions):
            limitations.append(f"{symbol}: faltan horas de ejecución; "
                               "consulta cada intento para reconstruir FIFO.")
            continue
        executions.sort(key=lambda s: (datetime.fromisoformat(s.receipt["filled_at"])
                                       if has_sales else s.draft.prepared_at, s.intent.sequence))
        lots, invalid = [], False
        for state in executions:
            quantity = Decimal(state.receipt["filled_qty"])
            price = Decimal(state.receipt["filled_avg_price"])
            if state.draft.side == "buy":
                lots.append({"state": state, "quantity": quantity, "remaining": quantity,
                             "price": price, "closed_cost": Decimal(0), "realized": Decimal(0)})
            else:
                if sum((lot["remaining"] for lot in lots), Decimal(0)) < quantity:
                    invalid = True
                    break
                for lot in lots:
                    used = min(quantity, lot["remaining"])
                    lot["remaining"] -= used
                    lot["closed_cost"] += used * lot["price"]
                    lot["realized"] += used * (price - lot["price"])
                    quantity -= used
                    if quantity == 0:
                        break
        if invalid:
            limitations.append(f"{symbol}: hay ventas sin compras previas suficientes en este registro.")
            continue
        position = positions.get(symbol)
        remaining = sum((lot["remaining"] for lot in lots), Decimal(0))
        broker_quantity = position.quantity if position and position.side == "long" else Decimal(0)
        known_ids = {s.receipt["id"] for s in orders if s.receipt}
        outside = any(o.symbol == symbol and o.filled_quantity > 0 and o.id not in known_ids
                      for o in snapshot.orders)
        matched = remaining == broker_quantity and not outside
        if not matched:
            limitations.append(f"{symbol}: el registro y la cuenta difieren o incluyen órdenes externas; "
                               "el resultado abierto queda pendiente de conciliación.")
        for lot in lots:
            state = lot["state"]
            open_cost = lot["remaining"] * lot["price"]
            current = position.current_price if matched and position else None
            unrealized = ((current - lot["price"]) * lot["remaining"]
                          if lot["remaining"] > 0 and current is not None else
                          Decimal(0) if lot["remaining"] == 0 else None)
            levels = reference_levels(state.draft, lot["price"])
            rows.append({"Símbolo": symbol, "ID de entrada": state.draft.client_order_id,
                         "Clasificación": alignment(state.draft), "Compradas": lot["quantity"],
                         "Abiertas": lot["remaining"], "Entrada media · USD": lot["price"],
                         "Resultado cerrado · USD": lot["realized"] if lot["closed_cost"] else None,
                         "Rendimiento cerrado · %": 100 * lot["realized"] / lot["closed_cost"]
                         if lot["closed_cost"] else None,
                         "Resultado abierto · USD": unrealized,
                         "Rendimiento abierto · %": 100 * unrealized / open_cost
                         if unrealized is not None and open_cost else None,
                         "Stop de referencia · USD": levels[0] if levels else None,
                         "Objetivo de referencia · USD": levels[1] if levels else None})
    return rows, limitations
