"""Review, explicit confirmation and manual reconciliation of limit DAY Paper orders."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from alpaca_order_models import limit_inputs
from alpaca_order_store import order_store_for
from alpaca_orders import order_states, prepare_order, reconcile_order, submit_order
from alpaca_paper import AlpacaPaperError

ZONE = ZoneInfo("America/Mexico_City")
LABELS = {"filled": "Ejecutada", "partially_filled": "Ejecución parcial", "new": "Pendiente",
          "accepted": "Aceptada", "pending_new": "En revisión", "canceled": "Cancelada",
          "expired": "Vencida", "rejected": "Rechazada", "solicitud_rechazada": "Solicitud rechazada",
          "sin_confirmar": "Sin confirmar"}


def _notice(message):
    st.session_state["_technical_alpaca_order_notice"] = message
    st.rerun()


def render_paper_orders(client, watchlist_store, issuer, subject, *, client_loader):
    st.subheader("Orden limitada de prueba")
    st.caption("Prueba técnica manual · cuenta Paper · acciones de EE. UU. · USD · límite DAY")
    notice = st.session_state.pop("_technical_alpaca_order_notice", None)
    if notice:
        st.info(notice)
    account = st.session_state["_technical_alpaca_snapshot"].account
    account_id = account.id
    store = order_store_for(watchlist_store)
    try:
        states = order_states(store.load(issuer, subject, account_id))
    except AlpacaPaperError as exc:
        st.error(str(exc))
        st.caption("El registro debe estar disponible antes de preparar o enviar una orden.")
        return

    def authorized_client():
        current = client_loader()
        if current.configuration_signature != client.configuration_signature:
            raise AlpacaPaperError("La configuración cambió. Actualiza la cuenta y prepara otra propuesta.")
        return current

    unknown = any(state.unresolved for state in states)
    if unknown:
        st.warning("Hay un intento sin confirmar. Consulta su estado abajo antes de crear otra orden.")
        st.session_state.pop("_technical_alpaca_draft", None)
    else:
        symbol = st.text_input("Símbolo en Alpaca", key="technical_alpaca_order_symbol")
        side_label = st.selectbox("Lado de la prueba", ["Compra", "Venta"],
                                  key="technical_alpaca_order_side")
        side = "buy" if side_label == "Compra" else "sell"
        quantity = st.number_input("Títulos enteros", min_value=1, max_value=10000, value=1,
                                    step=1, key="technical_alpaca_order_quantity")
        price = st.number_input("Precio límite · USD", min_value=0.0, value=0.0, step=0.01,
                                format="%.4f", key="technical_alpaca_order_price")
        draft = st.session_state.get("_technical_alpaca_draft")
        if draft:
            try:
                changed = draft.account_id != account_id or limit_inputs(symbol, side, quantity, price) != (
                    draft.symbol, draft.side, draft.quantity, draft.limit_price)
            except AlpacaPaperError:
                changed = True
            if changed:
                st.session_state.pop("_technical_alpaca_draft", None)
                draft = None
        if st.button("Preparar propuesta Paper", key="technical_alpaca_order_prepare"):
            try:
                with st.spinner("Comprobando instrumento, cuenta, disponibilidad y horario…"):
                    draft = prepare_order(authorized_client(), store, issuer, subject,
                                          symbol, side, quantity, price)
                st.session_state["_technical_alpaca_draft"] = draft
            except AlpacaPaperError as exc:
                st.error(str(exc))
                st.session_state.pop("_technical_alpaca_draft", None)
                draft = None
        if draft:
            units = "título" if draft.quantity == 1 else "títulos"
            price_text = (f"{draft.limit_price:,.2f}" if draft.limit_price >= 1
                          else f"{draft.limit_price:,.4f}")
            st.write("**Revisa esta propuesta de simulación**")
            st.write(f"{side_label} · **{draft.symbol}** · {draft.quantity} {units} · "
                     f"límite **{price_text} USD** por título")
            st.write(f"Importe al límite, antes de costos: **{draft.quantity * draft.limit_price:,.2f} USD**")
            st.caption(f"Cuenta Paper …{account.number[-4:]} · preparada {draft.prepared_at:%H:%M:%S} UTC · "
                       "vigencia de la revisión: 5 minutos")
            if draft.market_open:
                st.caption("Sesión regular abierta. La orden DAY vence al cierre si no se ejecuta.")
            else:
                st.info("Sesión regular cerrada. La orden DAY puede quedar en cola para la siguiente sesión: "
                        f"{draft.next_open.astimezone(ZONE):%Y-%m-%d %H:%M} · Ciudad de México.")
            confirmed = st.checkbox(
                f"Confirmo esta orden simulada: {side_label.lower()} de {draft.quantity} "
                f"{draft.symbol} a límite {price_text} USD, DAY y sesión regular.",
                key=f"technical_alpaca_order_confirm_{draft.client_order_id}",
            )
            expired = (datetime.now(UTC) - draft.prepared_at).total_seconds() > 300
            if expired:
                st.warning("La revisión venció. Prepara otra propuesta para consultar datos recientes.")
            if st.button("Confirmar y enviar a Paper", type="primary", disabled=not confirmed or expired,
                         key="technical_alpaca_order_submit"):
                try:
                    with st.spinner("Guardando el intento y enviando una única solicitud Paper…"):
                        result = submit_order(authorized_client(), store, issuer, subject,
                                               draft, confirmed=confirmed)
                    message = ("Envío sin confirmar. Consulta su estado; este intento no se reenviará."
                               if result.unresolved else
                               "Estado de la orden Paper: " + LABELS.get(result.status, result.status) + ".")
                except AlpacaPaperError as exc:
                    message = str(exc)
                st.session_state.pop("_technical_alpaca_draft", None)
                _notice(message)

    st.subheader("Seguimiento de los envíos de esta app")
    if not states:
        st.info("Aún no hay intentos guardados para esta cuenta Paper.")
        return
    rows = []
    for state in reversed(states):
        draft, receipt = state.draft, state.receipt
        code = state.latest.payload.get("http_status")
        detail = f"HTTP {code}" if type(code) is int and 400 <= code < 500 else None
        rows.append({"Símbolo": draft.symbol, "Lado": "Compra" if draft.side == "buy" else "Venta",
                     "Títulos": draft.quantity, "Límite · USD": float(draft.limit_price),
                     "Estado": LABELS.get(state.status, state.status), "Detalle": detail,
                     "Ejecutados": float(receipt["filled_qty"]) if receipt else None,
                     "Precio medio · USD": float(receipt["filled_avg_price"])
                     if receipt and receipt["filled_avg_price"] is not None else None,
                     "Última confirmación UTC": state.latest.recorded_at,
                     "ID de intento": draft.client_order_id,
                     "ID de Alpaca": receipt["id"] if receipt else None})
    frame = pd.DataFrame(rows)
    st.dataframe(frame, hide_index=True, width="stretch", height=min(300, 38 + 35 * len(frame)),
                 column_config={"Símbolo": st.column_config.TextColumn(pinned=True),
                                "Límite · USD": st.column_config.NumberColumn(format="%.4f"),
                                "Precio medio · USD": st.column_config.NumberColumn(format="%.4f")})
    by_id = {state.draft.client_order_id: state for state in states}
    selected_id = st.selectbox("Intento a consultar", list(reversed(by_id)),
                               format_func=lambda key: f"{by_id[key].draft.symbol} · "
                               f"{LABELS.get(by_id[key].status, by_id[key].status)} · {key[-8:]}",
                               key="technical_alpaca_order_tracking")
    selected = by_id[selected_id]
    st.caption(f"Identificador del intento: {selected.draft.client_order_id}")
    if st.button("Consultar estado del intento", key="technical_alpaca_order_reconcile"):
        try:
            result = reconcile_order(authorized_client(), store, issuer, subject, account_id,
                                     selected.draft.client_order_id)
            message = "Último estado confirmado: " + LABELS.get(result.status, result.status) + "."
        except AlpacaPaperError as exc:
            message = str(exc)
        _notice(message)
    st.download_button("Descargar envíos CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       "alpaca_paper_envios.csv", "text/csv", key="technical_alpaca_order_download")
    st.caption("La aceptación no implica ejecución. Para cancelar una orden, usa el panel Paper de Alpaca "
               "y después consulta su estado aquí. Actualiza la cuenta para revisar saldos y posiciones.")
