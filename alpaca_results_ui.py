"""Saved signal attribution and clearly scoped Paper performance, without trading actions."""

from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd
import streamlit as st

from alpaca_order_store import order_store_for
from alpaca_orders import order_states
from alpaca_paper import AlpacaPaperError
from alpaca_results import paper_results
from alpaca_signal_context import alignment


def render_paper_results(watchlist, issuer, subject, snapshot):
    st.subheader("Resultados y señales")
    st.caption("Sólo órdenes enviadas desde esta app · Paper · USD · consulta manual")
    try:
        states = order_states(order_store_for(watchlist).load(issuer, subject, snapshot.account.id))
        rows, limitations = paper_results(states, snapshot)
    except AlpacaPaperError as exc:
        st.error(str(exc))
        return
    st.caption(f"Precios de la cuenta consultados {snapshot.fetched_at:%Y-%m-%d %H:%M:%S} UTC. "
               "Actualiza la cuenta y consulta los intentos para incorporar cambios.")
    if not states:
        st.info("Aún no hay órdenes registradas en esta app para la cuenta conectada.")
        return
    closed = sum((r["Resultado cerrado · USD"] or Decimal(0) for r in rows), Decimal(0))
    closed_count = sum(r["Resultado cerrado · USD"] is not None for r in rows)
    open_rows = [r for r in rows if r["Abiertas"] > 0]
    complete_open = bool(rows) and not limitations and all(
        r["Resultado abierto · USD"] is not None for r in open_rows)
    total_open = sum((r["Resultado abierto · USD"] or Decimal(0) for r in open_rows), Decimal(0))
    left, right = st.columns(2)
    left.metric("Resultado abierto del registro · USD", f"{total_open:+,.2f}" if complete_open else "—")
    right.metric("Resultado cerrado del registro · USD", f"{closed:+,.2f}"
                 if closed_count and not limitations else "—")
    st.caption("Rendimiento por precio, antes de comisiones, dividendos e impuestos. "
               "Modelo FIFO por finalización de órdenes completas, usando su precio medio; "
               "no es el resultado total de la cuenta ni un resultado fiscal.")
    for reason in limitations:
        st.warning(reason)
    if rows:
        frame = pd.DataFrame(rows).map(lambda value: float(value) if isinstance(value, Decimal) else value)
        leading = ["Símbolo", "Abiertas", "Resultado abierto · USD", "Entrada media · USD",
                   "Resultado cerrado · USD", "Rendimiento abierto · %", "Rendimiento cerrado · %"]
        frame = frame[leading + [c for c in frame.columns if c not in leading]]
        numeric = [c for c in frame.columns if "USD" in c or "%" in c]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        formats = {c: "{:,.2f}" for c in numeric}
        formats.update({"Abiertas": "{:,.0f}", "Compradas": "{:,.0f}"})
        st.dataframe(frame.style.format(formats, na_rep="—"),
                     hide_index=True, width="stretch",
                     column_config={"Símbolo": st.column_config.TextColumn(pinned=True)})
        st.download_button("Descargar resultados CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                           "alpaca_paper_resultados.csv", "text/csv",
                           key="technical_alpaca_order_results_csv")
    else:
        st.info("Aún no hay lotes completos evaluables. Consulta el estado de los intentos.")
    st.caption("Stop y objetivo son referencias calculadas con el ATR guardado y el precio ejecutado. "
               "No son órdenes de salida enviadas al broker.")
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
    st.dataframe(pd.DataFrame(conditions), hide_index=True, width="stretch")
