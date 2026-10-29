"""Read-only broker reconciliation for the Paper research ledger."""

from alpaca_order_models import validate_receipt
from alpaca_orders import TERMINAL, order_states
from alpaca_paper import AlpacaPaperError
from alpaca_trial_store import fills_digest, stable_key


def refresh_results(client, store, issuer, subject, account_id, *, batch_size=10, trial_store=None):
    snapshot = client.fetch_snapshot()
    if snapshot.account.id != account_id:
        raise AlpacaPaperError("La cuenta cambió. Vuelve a conectar antes de actualizar resultados.")
    events = store.load(issuer, subject, account_id)
    states = order_states(events)
    pending = [s for s in states if s.latest.kind != "rejected" and
               (s.status not in TERMINAL or s.status == "filled" and not s.receipt.get("filled_at"))]
    # Rotate batches: a failing early attempt must not starve all later ones.
    last_attempt = {e.client_order_id: e.recorded_at for e in events}
    pending.sort(key=lambda s: last_attempt[s.draft.client_order_id])
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
            try:
                store.append(issuer, subject, account_id, state.draft.client_order_id,
                             "unknown", {"reason": "results_lookup_unconfirmed"})
            except AlpacaPaperError:
                errors.append("No se pudo guardar el fallo de consulta; se conserva el estado anterior.")
            errors.append(f"{state.draft.symbol} · {state.draft.client_order_id[-8:]}: {exc}")
    if trial_store is not None and states:
        from datetime import timedelta

        try:
            after = min(s.draft.prepared_at for s in states) - timedelta(days=1)
            fills = client.fetch_fills(after)
            known = {e.payload["id"]: e.payload for e in trial_store.load(issuer, subject, account_id)
                     if e.kind == "fill"}
            for fill in fills:
                if known.get(fill.id) == fill.to_json():
                    continue
                trial_store.append(issuer, subject, account_id, "fill", fill.to_json(),
                                   key=stable_key("fill", fill.id))
            trial_store.append(issuer, subject, account_id, "fills_sync", {
                "after": after.isoformat(), "count": len(fills), "complete": True,
                "digest": fills_digest(fills),
                "fetched_at": snapshot.fetched_at.isoformat()})
        except AlpacaPaperError as exc:
            errors.append(str(exc))
    return snapshot, updated, max(0, len(pending) - batch_size), errors
