"""Streamlit view for prospective, manually quoted one-share SIC paper trades."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from supabase_watchlist import SupabaseWatchlistStore
from technical_analysis import UNAVAILABLE, MarketHistory, TechnicalSnapshot, analyze_history
from technical_paper import (
    EXIT_REASONS,
    PaperError,
    PaperEvent,
    entry_event,
    exit_event,
    paper_result,
    signal_event,
    signal_key,
)
from technical_paper_store import SQLitePaperStore, SupabasePaperStore
from watchlist_store import WatchlistStore

MEXICO_CITY = ZoneInfo("America/Mexico_City")


def paper_store_for(store: WatchlistStore | SupabaseWatchlistStore):
    if isinstance(store, SupabaseWatchlistStore):
        return SupabasePaperStore(store)
    return SQLitePaperStore(store.path.with_suffix(".paper.db"))


def _load_events(store, issuer: str, subject: str, *, refresh: bool = False) -> list[PaperEvent]:
    if refresh or "_technical_paper_events" not in st.session_state:
        st.session_state["_technical_paper_events"] = store.load(issuer, subject)
    return st.session_state["_technical_paper_events"]


def _save_event(store, issuer: str, subject: str, event: PaperEvent):
    stored = store.append(issuer, subject, event)
    st.session_state["_technical_paper_events"] = store.load(issuer, subject)
    st.success(f"{stored.kind.capitalize()} guardada a las {stored.recorded_at:%Y-%m-%d %H:%M} UTC.")


def _quote_widgets(prefix: str):
    current = datetime.now(MEXICO_CITY)
    day = st.date_input("Fecha de la cotización · Ciudad de México", value=current.date(),
                        key=f"{prefix}_day")
    hour = st.time_input("Hora de la cotización · Ciudad de México",
                         value=current.time().replace(second=0, microsecond=0),
                         key=f"{prefix}_time")
    return datetime.combine(day, hour, tzinfo=MEXICO_CITY)


def _render_signal_capture(store, issuer: str, subject: str, events: list[PaperEvent],
                           symbols: list[str], histories: dict):
    st.subheader("1 · Congelar la señal")
    st.caption("El registro fija la sesión, condiciones, fuente y hora de captura. No puede editarse.")
    if not symbols:
        st.info("Añade un ticker a Mi seguimiento para capturar una señal nueva.")
        return
    ticker = st.selectbox("Acción observada", symbols, key="technical_paper_ticker")
    history = histories.get(ticker)
    if not isinstance(history, MarketHistory):
        st.info("Consulta primero esta acción en Señales con «Actualizar señales».")
        return
    snapshot: TechnicalSnapshot = analyze_history(history, datetime.now(UTC))
    if snapshot.signal == UNAVAILABLE or snapshot.as_of is None:
        st.info(f"{ticker}: {snapshot.reason}")
        return
    key = signal_key(ticker, snapshot.as_of)
    existing = next((item for item in events if item.event_key == key), None)
    st.write(f"**{ticker} · {snapshot.signal} · sesión {snapshot.as_of}**")
    st.caption(f"{snapshot.reason} · {history.currency} · {history.exchange} · {history.source}")
    fetched_age = (datetime.now(UTC) - history.fetched_at.astimezone(UTC)).total_seconds()
    if existing:
        st.info(f"Señal registrada el {existing.recorded_at:%Y-%m-%d %H:%M} UTC.")
    elif fetched_age > 3_600 or fetched_age < 0:
        st.warning("La consulta tiene más de una hora. Actualiza señales antes de registrar.")
    elif st.button("Registrar señal observada", type="primary", key="technical_paper_log_signal"):
        try:
            _save_event(store, issuer, subject, signal_event(snapshot, history))
        except PaperError as exc:
            st.error(str(exc))


def _render_entry(store, issuer: str, subject: str, events: list[PaperEvent]):
    st.subheader("2 · Entrada simulada")
    signals = [event for event in events if event.kind == "signal"
               and event.payload.get("signal") == "Compra"
               and not any(item.event_key == event.signal_key + ":entry" for item in events)]
    if not signals:
        st.info("No hay señales Compra registradas pendientes de una entrada simulada.")
        return
    signal = st.selectbox(
        "Señal Compra", signals,
        format_func=lambda item: (
            f"{item.ticker} · {item.signal_date} · "
            f"capturada {item.recorded_at:%Y-%m-%d %H:%M} UTC"
        ), key="technical_paper_entry_signal",
    )
    with st.form("technical_paper_entry_form"):
        st.caption("Transcribe el libro SIC de GBM. Se simula una acción; no se fija capital real.")
        next_session = st.checkbox("Es la siguiente sesión SIC disponible tras la señal",
                                   key="technical_paper_next_session")
        local_symbol = st.text_input("Serie SIC en GBM", key="technical_paper_local_symbol")
        local_isin = st.text_input("ISIN local", key="technical_paper_local_isin")
        quote_at = _quote_widgets("technical_paper_entry_quote")
        bid = st.number_input("Mejor compra (bid) · MXN", min_value=0.0, step=0.01,
                              key="technical_paper_entry_bid")
        ask = st.number_input("Mejor venta (ask) · MXN", min_value=0.0, step=0.01,
                              key="technical_paper_entry_ask")
        volume = st.number_input("Volumen SIC · títulos", min_value=0, step=1,
                                 key="technical_paper_entry_volume")
        stop = st.number_input("Stop planeado · MXN", min_value=0.0, step=0.01,
                               key="technical_paper_entry_stop")
        target = st.number_input("Objetivo planeado · MXN", min_value=0.0, step=0.01,
                                 key="technical_paper_entry_target")
        cost = st.number_input("Costo adicional supuesto por lado (%)", min_value=0.0,
                               max_value=10.0, value=0.35, step=0.05,
                               key="technical_paper_entry_cost") / 100
        with st.expander("Referencia SIC opcional para el mismo intervalo"):
            use_reference = st.checkbox("Registrar referencia local",
                                        key="technical_paper_use_reference")
            reference_symbol = st.text_input("Serie de referencia SIC",
                                             key="technical_paper_reference_symbol")
            reference_isin = st.text_input("ISIN de referencia",
                                           key="technical_paper_reference_isin")
            reference_bid = st.number_input("Bid de referencia · MXN", min_value=0.0,
                                            step=0.01, key="technical_paper_reference_bid")
            reference_ask = st.number_input("Ask de referencia · MXN", min_value=0.0,
                                            step=0.01, key="technical_paper_reference_ask")
            reference_volume = st.number_input("Volumen de referencia · títulos", min_value=0,
                                               step=1, key="technical_paper_reference_volume")
        submitted = st.form_submit_button("Guardar entrada en papel")
    if not submitted:
        return
    if not next_session:
        st.warning("Confirma la siguiente sesión SIC o deja la señal sin operación simulada.")
        return
    try:
        event = entry_event(
            signal, local_symbol=local_symbol, local_isin=local_isin, quote_at=quote_at,
            bid_mxn=bid, ask_mxn=ask, volume=volume, stop_mxn=stop,
            target_mxn=target, cost_rate=cost,
            benchmark_symbol=reference_symbol if use_reference else "",
            benchmark_isin=reference_isin if use_reference else "",
            benchmark_bid_mxn=reference_bid if use_reference else None,
            benchmark_ask_mxn=reference_ask if use_reference else None,
            benchmark_volume=reference_volume if use_reference else None,
        )
        _save_event(store, issuer, subject, event)
    except PaperError as exc:
        st.error(str(exc))


def _render_exit(store, issuer: str, subject: str, events: list[PaperEvent]):
    st.subheader("3 · Salida simulada")
    entries = [event for event in events if event.kind == "entry"
               and not any(item.event_key == event.signal_key + ":exit" for item in events)]
    if not entries:
        st.info("No hay entradas simuladas abiertas.")
        return
    entry = st.selectbox("Entrada abierta", entries, format_func=lambda item:
                         f"{item.ticker} · {item.payload.get('local_symbol')} · "
                         f"entrada {item.recorded_at:%Y-%m-%d %H:%M} UTC",
                         key="technical_paper_exit_entry")
    with st.form("technical_paper_exit_form"):
        st.caption(
            "Registra el mejor bid observado para una acción. "
            "El precio real de ejecución podría diferir."
        )
        quote_at = _quote_widgets("technical_paper_exit_quote")
        bid = st.number_input("Mejor compra para vender (bid) · MXN", min_value=0.0,
                              step=0.01, key="technical_paper_exit_bid")
        volume = st.number_input("Volumen SIC de salida · títulos", min_value=0,
                                 step=1, key="technical_paper_exit_volume")
        reason = st.selectbox("Motivo de salida", EXIT_REASONS,
                              key="technical_paper_exit_reason")
        reference = entry.payload.get("benchmark")
        if reference:
            st.caption(f"Referencia registrada al entrar: {reference['symbol']} · {reference['isin']}")
            reference_bid = st.number_input("Bid de salida de referencia · MXN",
                                             min_value=0.0, step=0.01,
                                             key="technical_paper_exit_reference_bid")
            reference_volume = st.number_input("Volumen de salida de referencia · títulos",
                                                min_value=0, step=1,
                                                key="technical_paper_exit_reference_volume")
        else:
            reference_bid, reference_volume = None, None
        submitted = st.form_submit_button("Guardar salida en papel")
    if not submitted:
        return
    try:
        event = exit_event(entry, quote_at=quote_at, bid_mxn=bid, volume=volume,
                           reason=reason, benchmark_bid_mxn=reference_bid,
                           benchmark_volume=reference_volume)
        _save_event(store, issuer, subject, event)
    except PaperError as exc:
        st.error(str(exc))


def _render_results(events: list[PaperEvent]):
    st.subheader("Registro y resultados")
    signals = [item for item in events if item.kind == "signal"]
    entries = {item.signal_key: item for item in events if item.kind == "entry"}
    exits = {item.signal_key: item for item in events if item.kind == "exit"}
    rows = []
    for signal in signals:
        entry = entries.get(signal.signal_key)
        exit_ = exits.get(signal.signal_key)
        result = paper_result(entry, exit_) if entry and exit_ else None
        rows.append({
            "Acción": signal.ticker, "Sesión": signal.signal_date,
            "Señal": signal.payload.get("signal"),
            "Capturada UTC": signal.recorded_at,
            "Serie SIC": entry.payload.get("local_symbol") if entry else None,
            "Entrada MXN": float(entry.payload["ask_mxn"]) if entry else None,
            "Salida MXN": float(exit_.payload["bid_mxn"]) if exit_ else None,
            "Retorno neto (%)": float(result.net_return * 100) if result else None,
            "Referencia neta (%)": float(result.benchmark_net_return * 100)
            if result and result.benchmark_net_return is not None else None,
            "Estado": "Cerrada" if exit_ else "Abierta" if entry else "Solo señal",
        })
    st.caption(f"{len(signals)} señales observadas · {len(entries)} entradas · {len(exits)} salidas.")
    if not rows:
        st.info("Aún no hay observaciones guardadas. La primera señal se registra arriba.")
        return
    frame = pd.DataFrame(rows).sort_values("Capturada UTC", ascending=False)
    st.dataframe(frame, hide_index=True, width="stretch",
                 column_config={"Retorno neto (%)": st.column_config.NumberColumn(format="%.2f"),
                                "Referencia neta (%)": st.column_config.NumberColumn(format="%.2f")})
    paired = frame.dropna(subset=["Retorno neto (%)", "Referencia neta (%)"])
    if not paired.empty:
        strategy = paired["Retorno neto (%)"].mean()
        reference = paired["Referencia neta (%)"].mean()
        st.write(
            f"Media por operación con referencia ({len(paired)} intervalos): "
            f"estrategia {strategy:+.2f}% · referencia {reference:+.2f}% · "
            f"diferencia {strategy - reference:+.2f} puntos porcentuales."
        )
    st.download_button("Descargar bitácora CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       "bitacora_papel_sic.csv", "text/csv")
    st.caption(
        "Una acción simulada por entrada. Cotizaciones y disponibilidad declaradas manualmente; "
        "costos editables y sin dividendos ni impuestos. La referencia compara solo los mismos "
        "intervalos de operaciones cerradas; no representa el retorno de una cartera ni una "
        "prueba de ejecución real. Los stops no garantizan el precio de salida."
    )


def render_paper_journal(
    watchlist_store: WatchlistStore | SupabaseWatchlistStore,
    issuer: str, subject: str, symbols: list[str], histories: dict,
):
    st.subheader("Prueba prospectiva en papel")
    st.caption("Captura cronológica · SIC en MXN · una acción ficticia · sin conexión de órdenes")
    store = paper_store_for(watchlist_store)
    try:
        events = _load_events(store, issuer, subject,
                              refresh=st.button("Actualizar bitácora", key="technical_paper_refresh"))
    except PaperError as exc:
        st.error(str(exc))
        return
    st.caption(
        f"{sum(item.kind == 'signal' for item in events)} señales · "
        f"{sum(item.kind == 'entry' for item in events)} entradas · "
        f"{sum(item.kind == 'exit' for item in events)} salidas registradas"
    )
    capture, trade, history = st.tabs(["Señal", "Operación simulada", "Historial"])
    with capture:
        _render_signal_capture(store, issuer, subject, events, symbols, histories)
    with trade:
        entry_column, exit_column = st.columns(2, gap="large")
        with entry_column:
            _render_entry(store, issuer, subject, events)
        with exit_column:
            _render_exit(store, issuer, subject, events)
    with history:
        _render_results(st.session_state.get("_technical_paper_events", events))
