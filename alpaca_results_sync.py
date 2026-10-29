"""Read-only broker reconciliation for the Paper research ledger."""

from alpaca_order_models import validate_receipt
from alpaca_orders import TERMINAL, order_states
from alpaca_paper import AlpacaPaperError


def refresh_results(client, store, issuer, subject, account_id, *, batch_size=10):
    snapshot = client.fetch_snapshot()
    if snapshot.account.id != account_id:
        raise AlpacaPaperError("La cuenta cambió. Vuelve a conectar antes de actualizar resultados.")
    states = order_states(store.load(issuer, subject, account_id))
    pending = [s for s in states if s.latest.kind != "rejected" and
               (s.status not in TERMINAL or s.status == "filled" and not s.receipt.get("filled_at"))]
    updated, errors = 0, []
    for state in pending[:batch_size]:
        try:
            row = client.order_resource("order", state.draft.client_order_id)
            if row is None:
                raise AlpacaPaperError("Alpaca no devolvió este intento; conserva su estado anterior.")
            receipt = validate_receipt(state.draft, row)
            store.append(issuer, subject, account_id, state.draft.client_order_id, "observed", receipt)
            updated += 1
        except AlpacaPaperError as exc:
            errors.append(f"{state.draft.symbol} · {state.draft.client_order_id[-8:]}: {exc}")
    return snapshot, updated, max(0, len(pending) - batch_size), errors
