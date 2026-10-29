"""Saved signal attribution and clearly scoped Paper performance, without trading actions."""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import streamlit as st

from alpaca_fill_results import fill_results
from alpaca_order_store import order_store_for
from alpaca_orders import order_states
from alpaca_paper import AlpacaPaperError
from alpaca_results_sync import refresh_results
from alpaca_signal_context import alignment
from alpaca_trial_store import latest, stored_fills, trial_store_for


def money(value):
    return (value or Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def render_paper_results(watchlist, issuer, subject, snapshot, *, client_loader, expected_signature,
                         history_loader=None):
    st.subheader("Resultados y señales")
    st.caption("Sólo órdenes enviadas desde esta app · Paper · USD · consulta manual")
    notice = st.session_state.pop("_technical_alpaca_results_notice", None)
    if notice:
        st.info(notice[0])
        for error in notice[1]:
            st.warning(error)
    store = order_store_for(watchlist)
    trial_store = trial_store_for(watchlist)
    try:
        states = order_states(store.load(issuer, subject, snapshot.account.id))
        controls = trial_store.load(issuer, subject, snapshot.account.id)
    except AlpacaPaperError as exc:
        st.error(str(exc))
        return
    if st.button("Actualizar resultados", key="technical_alpaca_order_results_refresh"):
        try:
            client = client_loader()
            if client.configuration_signature != expected_signature:
                raise AlpacaPaperError("La configuración cambió. Vuelve a conectar la cuenta.")
            with st.spinner("Consultando la cuenta y hasta diez intentos existentes…"):
                fresh, updated, remaining, errors = refresh_results(
                    client, store, issuer, subject, snapshot.account.id, trial_store=trial_store)
            st.session_state["_technical_alpaca_snapshot"] = fresh
            message = f"Cuenta actualizada · {updated} intentos consultados."
            if remaining:
                message += f" Quedan {remaining} por consultar en otro lote."
            st.session_state["_technical_alpaca_results_notice"] = (message, errors)
            st.rerun()
        except AlpacaPaperError as exc:
            st.error(str(exc))
    st.caption(f"Precios de la cuenta consultados {snapshot.fetched_at:%Y-%m-%d %H:%M:%S} UTC. "
               "Actualizar resultados consulta la cuenta y los intentos pendientes; no envía órdenes.")
    if not states:
        st.info("Aún no hay órdenes registradas en esta app para la cuenta conectada.")
        return
    config = latest(controls, "settings")
    cost = Decimal(config.payload["cost_rate"]) if config else Decimal("0.0035")
    try:
        rows, limitations, flows = fill_results(states, snapshot, stored_fills(controls), cost_rate=cost)
    except AlpacaPaperError as exc:
        rows, limitations, flows = [], [str(exc)], []
    closed = sum((money(r["Resultado cerrado · USD"])
                  for r in rows), Decimal(0))
    closed_count = sum(r["Resultado cerrado · USD"] is not None for r in rows)
    open_rows = [r for r in rows if r["Abiertas"] > 0]
    complete_open = bool(rows) and not limitations and all(
        r["Resultado abierto · USD"] is not None for r in open_rows)
    total_open = sum((money(r["Resultado abierto · USD"])
                      for r in open_rows), Decimal(0))
    left, right = st.columns(2)
    left.metric("Resultado abierto del registro · USD", f"{total_open:+,.2f}" if complete_open else "—")
    right.metric("Resultado cerrado del registro · USD", f"{closed:+,.2f}"
                 if closed_count and not limitations else "—")
    net_open = sum((money(r["Neto abierto estimado · USD"])
                    for r in open_rows), Decimal(0))
    net_closed = sum((money(r["Neto cerrado estimado · USD"])
                      for r in rows), Decimal(0))
    net_left, net_right = st.columns(2)
    net_left.metric("Neto abierto estimado · USD", f"{net_open:+,.2f}" if complete_open else "—")
    net_right.metric("Neto cerrado estimado · USD", f"{net_closed:+,.2f}"
                     if closed_count and not limitations else "—")
    st.caption(f"FIFO por ejecución individual · fricción supuesta {100 * cost:.2f} % por lado. "
               "El neto abierto supone cerrar al precio consultado, con esos costos. Dividendos e impuestos "
               "quedan fuera; el cálculo no representa cargos reales ni el resultado fiscal del broker.")
    for reason in limitations:
        st.warning(reason)
    if rows:
        frame = pd.DataFrame(rows).map(lambda value: float(value) if isinstance(value, Decimal) else value)
        leading = ["Símbolo", "Abiertas", "Resultado abierto · USD", "Entrada media · USD",
                   "Resultado cerrado · USD", "Rendimiento abierto · %", "Rendimiento cerrado · %"]
        frame = frame[leading + [c for c in frame.columns if c not in leading]]
        numeric = [c for c in frame.columns if "USD" in c or "%" in c]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column].map(
                lambda value: float(money(Decimal(str(value)))) if pd.notna(value) else None),
                errors="coerce")
        formats = {c: "{:,.2f}" for c in numeric}
        formats.update({name: lambda value: f"{value:,.8f}".rstrip("0").rstrip(".")
                        for name in ("Abiertas", "Compradas")})
        st.dataframe(frame.style.format(formats, na_rep="—"),
                     hide_index=True, width="stretch",
                     column_config={"Símbolo": st.column_config.TextColumn(pinned=True)})
        st.download_button("Descargar resultados CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                           "alpaca_paper_resultados.csv", "text/csv",
                           key="technical_alpaca_order_results_csv")
    else:
        st.info("Aún no hay lotes completos evaluables. Consulta el estado de los intentos.")
    st.caption("Las referencias de ATR usan la señal guardada y el precio ejecutado. "
               "El presupuesto y las alertas usan el plan vigente de Control de la prueba. "
               "Las salidas se confirman y gestionan manualmente en el broker.")
    try:
        fills = stored_fills(controls)
        if fills:
            st.download_button("Descargar ejecuciones individuales CSV",
                pd.DataFrame([f.to_json() for f in fills]).to_csv(index=False).encode("utf-8-sig"),
                "ejecuciones_paper.csv", "text/csv", key="technical_alpaca_order_fills_csv")
    except AlpacaPaperError:
        pass  # The visible reconciliation message above explains the incomplete download.
    from alpaca_performance_ui import render_performance

    render_performance(rows, flows, limitations, cost, history_loader)
    st.write("**Señal guardada de cada intento**")
    by_id = {s.draft.client_order_id: s for s in states}
    selected_id = st.selectbox("Intento para revisar su señal", list(reversed(by_id)),
                               format_func=lambda key: f"{by_id[key].draft.symbol} · "
                               f"{'Compra' if by_id[key].draft.side == 'buy' else 'Venta'} · "
                               f"{by_id[key].draft.quantity} · {key[-8:]}",
                               key="technical_alpaca_order_result_selection")
    state = next(s for s in states if s.draft.client_order_id == selected_id)
    st.write(f"{state.draft.symbol} · {alignment(state.draft)}")
    if not state.draft.research_json:
        st.info("Este intento se preparó sin señal congelada vinculada. "
                "Se conserva como prueba técnica; no se le asigna una señal posterior.")
        return
    row = json.loads(state.draft.research_json)
    observation = row["observation"]
    st.write(f"**{observation['signal']} · sesión {row['session']}**")
    st.caption(f"Registrada {row['recorded_at']} · {observation['strategy_version']} · "
               f"{observation['origin_source']} · {observation['origin_market']} · USD")
    st.write(observation["reason"])
    conditions = observation["buy_checks" if state.draft.side == "buy" else "sell_checks"]
    st.dataframe(pd.DataFrame(conditions).rename(columns={"label": "Condición", "met": "Cumplida",
                                                        "reading": "Lectura"}),
                 hide_index=True, width="stretch")
