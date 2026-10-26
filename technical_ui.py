"""SIG research screen: private watchlists, evidence, charts and historical simulation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from access import authorized
from safe_logging import log_unexpected_analysis_error
from supabase_watchlist import SupabaseWatchlistStore
from technical_analysis import (
    BUY,
    SELL,
    STRATEGY_VERSION,
    UNAVAILABLE,
    WAIT,
    MarketHistory,
    TechnicalError,
    TechnicalSnapshot,
    analyze_history,
    create_trade_plan,
)
from technical_backtesting import run_technical_backtest
from technical_market_data import download_market_history
from watchlist_store import WatchlistError, WatchlistStore, identity_key

LOGGER = logging.getLogger(__name__)
BLUE = "#1d5fbf"
INK = "#141414"
MUTED = "#737373"
RED = "#c4242a"


@st.cache_data(ttl=3_600, max_entries=50, show_spinner=False)
def cached_market_history(symbol: str, refresh_id: str) -> MarketHistory:
    # Public market data only. A manual refresh uses a new ID without clearing other app caches.
    return download_market_history(symbol)


def configured_watchlist() -> tuple[WatchlistStore | SupabaseWatchlistStore, str, str]:
    try:
        policy = st.secrets.get("access", {})
        configuration = st.secrets.get("technical_watchlist", {})
        claims = st.user.to_dict()
    except (FileNotFoundError, AttributeError):
        raise WatchlistError("Inicia una sesión autorizada para abrir tu seguimiento.") from None
    if not authorized(claims, policy):
        raise WatchlistError("La sesión no está autorizada o ha expirado.")
    default = Path(__file__).resolve().parent / "data" / "private" / "technical_watchlists.db"
    location = configuration.get("database_path", str(default))
    if not isinstance(location, str):
        raise WatchlistError("Configura una ruta absoluta para el almacenamiento privado de seguimiento.")
    if configuration.get("backend", "sqlite") == "supabase":
        return (
            SupabaseWatchlistStore(
                configuration.get("url", ""),
                configuration.get("secret_key", ""),
                legacy_path=Path(location),
            ),
            claims["iss"],
            claims["sub"],
        )
    if configuration.get("backend", "sqlite") != "sqlite":
        raise WatchlistError("El almacenamiento de Seguimiento debe ser sqlite o supabase.")
    return WatchlistStore(Path(location)), claims["iss"], claims["sub"]


def _remember_draft():
    st.session_state["_technical_draft"] = st.session_state["technical_list_widget"]


def _render_list_editor(store: WatchlistStore | SupabaseWatchlistStore, issuer: str, subject: str):
    with st.sidebar:
        st.header("Mi seguimiento")
        if st.button("Copiar desde Análisis", width="stretch"):
            source = st.session_state.get("_optimizer_tickers")
            if source is None:
                st.info("Abre Análisis y configura sus tickers antes de copiarlos.")
            else:
                st.session_state["_technical_draft"] = source
                st.session_state["technical_list_widget"] = source
        if "technical_list_widget" not in st.session_state:
            st.session_state["technical_list_widget"] = st.session_state.get("_technical_draft", "")
        st.text_area(
            "Tickers de seguimiento",
            key="technical_list_widget", on_change=_remember_draft,
            help="Separa con comas. Añade o elimina símbolos y guarda la lista. Máximo 25.",
            height=100,
        )
        if st.button("Guardar lista", width="stretch"):
            try:
                symbols = store.save(issuer, subject, st.session_state["technical_list_widget"])
                st.session_state["_technical_symbols"] = symbols
                st.session_state["_technical_draft"] = ", ".join(symbols)
                histories = st.session_state.get("_technical_histories", {})
                st.session_state["_technical_histories"] = {
                    symbol: value for symbol, value in histories.items() if symbol in symbols
                }
                st.success("Lista guardada para tu usuario.")
            except WatchlistError as exc:
                st.error(str(exc))
        if isinstance(store, SupabaseWatchlistStore):
            st.caption("Lista guardada en Supabase para tu usuario.")
        else:
            st.caption("Lista local: en Streamlit Cloud puede perderse al reiniciar. Configura Supabase.")
        with st.expander("Supuestos de operación"):
            cost = st.number_input(
                "Costo total por lado (%)", min_value=0.0, max_value=10.0,
                value=0.25, step=0.05, key="technical_cost_widget",
            ) / 100
            slippage = st.number_input(
                "Deslizamiento por lado (pb)", min_value=0.0, max_value=500.0,
                value=10.0, step=1.0, key="technical_slippage_widget",
            )
            st.caption("Supuestos editables para comparar escenarios; no son una tarifa del intermediario.")
    return cost, slippage


def _refresh_histories(
    symbols: list[str], loader: Callable[[str, str], MarketHistory | TechnicalSnapshot] | None = None,
):
    loader = loader or cached_market_history
    refresh_id = uuid4().hex
    histories = {}
    progress = st.progress(0, text="Consultando sesiones y volumen…")
    for i, symbol in enumerate(symbols):
        try:
            histories[symbol] = loader(symbol, refresh_id)
        except TechnicalError as exc:
            histories[symbol] = TechnicalSnapshot(symbol, UNAVAILABLE, str(exc))
        except Exception as exc:
            log_unexpected_analysis_error(LOGGER, exc)
            histories[symbol] = TechnicalSnapshot(symbol, UNAVAILABLE, "No se pudo actualizar este ticker.")
        progress.progress((i + 1) / len(symbols), text=f"{i + 1} de {len(symbols)} acciones consultadas")
    progress.empty()
    st.session_state["_technical_histories"] = histories
    st.session_state["_technical_refresh_id"] = refresh_id
    st.session_state["_technical_updated"] = datetime.now(UTC).isoformat(timespec="seconds")


def build_technical_chart(snapshot: TechnicalSnapshot, *, currency: str, months: int = 6) -> go.Figure:
    full = snapshot.indicators
    data = full.loc[full.index >= full.index[-1] - pd.DateOffset(months=months)]
    figure = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.065,
        row_heights=[0.43, 0.17, 0.20, 0.20],
        subplot_titles=(f"Precio · {currency}", "Volumen · media de 20 sesiones previas",
                        "RSI 14", "MACD 12/26/9"),
    )
    figure.add_trace(go.Candlestick(
        x=data.index, open=data.Open, high=data.High, low=data.Low, close=data.Close,
        increasing_line_color=BLUE, decreasing_line_color=RED,
        increasing_fillcolor=BLUE, decreasing_fillcolor="white", name="OHLC", showlegend=False,
    ), row=1, col=1)
    for period, color, dash in ((20, INK, "solid"), (50, MUTED, "dash"), (200, "#a3a3a3", "dot")):
        figure.add_trace(go.Scatter(
            x=data.index, y=data[f"SMA{period}"], name=f"Media {period}",
            line={"color": color, "width": 1.3, "dash": dash},
        ), row=1, col=1)
    for column, name, color in (("Support20", "Soporte 20 previas", MUTED),
                                ("Resistance20", "Resistencia 20 previas", BLUE)):
        figure.add_trace(go.Scatter(
            x=data.index, y=data[column], name=name, showlegend=False,
            line={"color": color, "width": 1, "dash": "dot"},
            hovertemplate=name + ": %{y:,.2f}<extra></extra>",
        ), row=1, col=1)
    figure.add_trace(go.Bar(
        x=data.index, y=data.Volume, marker_color="#b7b7b7", name="Volumen", showlegend=False,
    ), row=2, col=1)
    figure.add_trace(go.Scatter(
        x=data.index, y=data.VolumeMean20, line={"color": INK, "width": 1.5},
        name="Volumen medio previo", showlegend=False,
    ), row=2, col=1)
    figure.add_trace(go.Scatter(
        x=data.index, y=data.RSI14, name="RSI", line={"color": BLUE, "width": 1.8}, showlegend=False,
    ), row=3, col=1)
    for level in (30, 50, 70):
        figure.add_hline(y=level, row=3, col=1, line_color="#d4d4d4", line_dash="dot", line_width=1)
    figure.update_yaxes(range=[0, 100], tickvals=[0, 30, 50, 70, 100], row=3, col=1)
    figure.add_trace(go.Bar(
        x=data.index, y=data.MACDHistogram, name="Histograma", showlegend=False,
        marker_color=[BLUE if value >= 0 else "#a3a3a3" for value in data.MACDHistogram],
    ), row=4, col=1)
    for column, name, color, dash in (("MACD", "MACD", BLUE, "solid"),
                                      ("MACDSignal", "Señal MACD", INK, "dash")):
        figure.add_trace(go.Scatter(
            x=data.index, y=data[column], name=name,
            line={"color": color, "width": 1.5, "dash": dash},
        ), row=4, col=1)
    figure.update_layout(
        height=640, margin={"l": 6, "r": 10, "t": 30, "b": 38},
        paper_bgcolor="white", plot_bgcolor="white", font={"color": INK, "size": 11},
        hovermode="x unified", legend={"orientation": "h", "y": -0.07, "x": 0, "font": {"size": 11}},
        bargap=0.15,
    )
    figure.update_annotations(font_size=12, x=0, xanchor="left")
    figure.update_xaxes(rangeslider_visible=False, showgrid=False, nticks=5, tickangle=0)
    figure.update_yaxes(showgrid=True, gridcolor="#ededed", nticks=4, zeroline=False)
    figure.update_yaxes(rangemode="tozero", row=2, col=1)
    return figure


def _render_conditions(snapshot: TechnicalSnapshot):
    tabs = st.tabs(["Condiciones de compra", "Condiciones de venta"])
    for tab, conditions in zip(tabs, (snapshot.buy_conditions, snapshot.sell_conditions), strict=True):
        with tab:
            table = pd.DataFrame([
                {"Condición": item.label, "Estado": "Cumple" if item.met else "Pendiente",
                 "Lectura": item.reading}
                for item in conditions
            ])
            st.dataframe(table, hide_index=True, width="stretch")


def _render_reference_plan(snapshot: TechnicalSnapshot, currency: str, cost: float, slippage: float):
    st.subheader("Plan de referencia")
    if snapshot.signal != BUY:
        if snapshot.signal == SELL:
            st.write("Revisar salida o reducción si tienes una posición en esta acción.")
        else:
            st.write("Esperar las confirmaciones pendientes antes de plantear una entrada.")
        return
    entry = st.number_input(
        f"Entrada de referencia ({currency})", min_value=0.000001,
        value=float(snapshot.close), format="%.4f",
        key=f"technical_entry_{snapshot.symbol}_{snapshot.as_of}",
    )
    try:
        plan = create_trade_plan(entry, float(snapshot.indicators.iloc[-1].ATR14),
                                 cost_rate=cost, slippage_bps=slippage)
        st.metric(f"Stop · {currency}", f"{plan.stop:,.2f}")
        st.metric(f"Objetivo · {currency}", f"{plan.target:,.2f}")
        st.write(f"**Beneficio/riesgo bruto:** {plan.gross_reward_risk:.2f}:1")
        st.write(f"**Con costos y deslizamiento:** {plan.net_reward_risk:.2f}:1")
        if plan.net_reward_risk <= 0:
            st.warning("Con estos costos, llegar al objetivo no deja beneficio neto. Revisa los supuestos.")
        st.caption("Stop a 2 ATR y objetivo a 4 ATR de la entrada. Cambia la referencia para recalcular.")
    except TechnicalError as exc:
        st.info(str(exc))


def _render_backtest(snapshot: TechnicalSnapshot, currency: str, cost: float, slippage: float):
    st.subheader("Prueba histórica de las reglas")
    st.caption(
        "Dos años de evaluación · entradas en la apertura siguiente · máximo 20 sesiones por operación · "
        f"costo {cost:.2%} y deslizamiento {slippage:g} pb por lado."
    )
    signature = (
        snapshot.symbol, str(snapshot.as_of), cost, slippage,
        st.session_state.get("_technical_refresh_id"), STRATEGY_VERSION,
    )
    if st.button("Ejecutar prueba histórica", key=f"technical_backtest_{snapshot.symbol}"):
        try:
            with st.spinner("Evaluando las mismas reglas sesión por sesión…"):
                result = run_technical_backtest(snapshot.indicators,
                                                cost_rate=cost, slippage_bps=slippage)
            st.session_state["_technical_backtest"] = (signature, result)
        except TechnicalError as exc:
            st.session_state.pop("_technical_backtest", None)
            st.info(str(exc))
    saved = st.session_state.get("_technical_backtest")
    if saved is None or saved[0] != signature:
        return
    result = saved[1]
    st.caption(f"Evaluación: {result.start.date()} a {result.end.date()} · {result.strategy_version}")
    left, right = st.columns(2)
    left.metric("Operaciones cerradas", str(len(result.trades)))
    right.metric("Operaciones ganadoras netas", "—" if result.win_rate is None else f"{result.win_rate:.1%}")
    st.dataframe(result.summary.style.format("{:.2%}"), width="stretch")
    chart = go.Figure()
    for column, color in (("Estrategia neta", BLUE), ("Comprar y mantener neto", MUTED)):
        chart.add_trace(go.Scatter(x=result.equity.index, y=result.equity[column], name=column,
                                   line={"color": color, "width": 1.8}))
    chart.update_layout(
        height=280, margin={"l": 10, "r": 10, "t": 15, "b": 20},
        paper_bgcolor="white", plot_bgcolor="white", hovermode="x unified",
        yaxis_title="Capital relativo (100 = inicio)", legend={"orientation": "h", "y": -0.2},
    )
    chart.update_xaxes(showgrid=False, nticks=5)
    chart.update_yaxes(gridcolor="#ededed")
    st.plotly_chart(chart, width="stretch", key=f"technical_equity_{snapshot.symbol}")
    st.caption(
        "Simulación de rendimiento por precio en " + currency + ". Dividendos e impuestos fuera del cálculo. "
        "Ambas alternativas incluyen los mismos costos por lado. Los gaps salen a la apertura; "
        "si se tocan stop y objetivo en una vela, se aplica primero el stop. "
        "La posición restante se liquida al último cierre de evaluación."
    )
    if result.trades.empty:
        st.info("No hubo operaciones con todas las confirmaciones; el porcentaje ganador no es aplicable.")
    else:
        with st.expander("Registro de entradas y salidas", expanded=True):
            view = result.trades.copy()
            for column in ("Fecha señal", "Entrada", "Salida"):
                view[column] = view[column].dt.date
            st.dataframe(view.style.format({
                "Retorno bruto": "{:.2%}", "Retorno neto": "{:.2%}",
            }), hide_index=True, width="stretch")
    a, b = st.columns(2)
    a.download_button("Operaciones simuladas CSV", result.trades.to_csv(index=False).encode("utf-8-sig"),
                      f"operaciones_{snapshot.symbol}.csv", "text/csv")
    b.download_button("Curvas de capital CSV", result.equity.to_csv().encode("utf-8-sig"),
                      f"curvas_{snapshot.symbol}.csv", "text/csv")


def render_technical_detail(
    history: MarketHistory, snapshot: TechnicalSnapshot, cost: float, slippage: float,
):
    st.subheader(f"{snapshot.symbol} · {snapshot.signal}")
    st.write(snapshot.reason)
    st.caption(f"Sesión {snapshot.as_of} · {history.currency} · {history.exchange} · {history.source}")
    chart_column, decision_column = st.columns([3, 1.15], gap="medium")
    with chart_column:
        period = st.radio("Ventana del gráfico", [3, 6, 12, 24], index=1,
                          format_func=lambda value: f"{value} meses", horizontal=True,
                          key="technical_chart_months")
        st.plotly_chart(build_technical_chart(snapshot, currency=history.currency, months=period),
                        width="stretch", key=f"technical_chart_{snapshot.symbol}")
    with decision_column:
        st.metric(f"Último cierre · {history.currency}", f"{snapshot.close:,.2f}",
                  delta=f"{snapshot.daily_change:+.2%}")
        st.metric("Volumen relativo", f"{snapshot.relative_volume:.2f}×")
        st.metric("RSI 14", f"{snapshot.rsi:.2f}")
        _render_reference_plan(snapshot, history.currency, cost, slippage)
    _render_conditions(snapshot)
    with st.expander("Fuente y eventos corporativos"):
        st.write(f"Zona de la bolsa: {history.timezone} · "
                 f"consulta {history.fetched_at.astimezone(UTC):%Y-%m-%d %H:%M} UTC")
        st.write(
            "La serie corresponde al mercado consultado. Para una operación en SIC, verifica el precio, "
            "la moneda y la liquidez locales; este volumen corresponde al mercado de origen."
        )
        columns = [column for column in ("Dividends", "Stock Splits") if column in snapshot.indicators]
        if columns:
            events = snapshot.indicators[columns]
            events = events.loc[events.fillna(0).ne(0).any(axis=1)]
            if not events.empty:
                st.dataframe(events.rename(columns={"Dividends": "Dividendo por acción",
                                                     "Stock Splits": "Factor de split"}), width="stretch")
            else:
                st.write("El proveedor no reportó eventos en el historial consultado.")
        else:
            st.write("El proveedor no entregó campos de eventos corporativos.")
        st.caption(
            "OHLC con auto_adjust=False; Adj Close se conserva separado y no alimenta los indicadores. "
            "Se respetan los ajustes de splits ya incorporados por el proveedor."
        )
    _render_backtest(snapshot, history.currency, cost, slippage)


def render_technical(
    *, watchlist_factory: Callable[
        [], tuple[WatchlistStore | SupabaseWatchlistStore, str, str]
    ] | None = None,
    history_loader: Callable[[str, str], MarketHistory | TechnicalSnapshot] | None = None,
):
    st.title("Seguimiento y señales")
    st.caption("Tendencias confirmadas · días a semanas · investigación interna · " + STRATEGY_VERSION)
    try:
        store, issuer, subject = (watchlist_factory or configured_watchlist)()
        owner = identity_key(issuer, subject)
        store_id = store.endpoint if isinstance(store, SupabaseWatchlistStore) else str(store.path)
        if (
            st.session_state.get("_technical_owner") != owner
            or st.session_state.get("_technical_store") != store_id
        ):
            # Keep no previous user's lists, quotes or simulated positions in a new identity's UI.
            for key in list(st.session_state):
                if key.startswith(("_technical_", "technical_")):
                    del st.session_state[key]
            symbols = store.load(issuer, subject)
            st.session_state["_technical_owner"] = owner
            st.session_state["_technical_store"] = store_id
            st.session_state["_technical_symbols"] = symbols
            st.session_state["_technical_draft"] = ", ".join(symbols)
    except WatchlistError as exc:
        st.info(str(exc))
        return
    cost, slippage = _render_list_editor(store, issuer, subject)
    symbols = st.session_state.get("_technical_symbols", [])
    actions, filters, detail_control = st.columns([1, 1, 1], vertical_alignment="bottom")
    refresh = actions.button("Actualizar señales", type="primary", disabled=not symbols, width="stretch")
    signal_filter = filters.selectbox("Mostrar señales", ["Todas", BUY, WAIT, SELL, UNAVAILABLE])
    if not symbols:
        st.info("Añade tus acciones en Mi seguimiento y guarda la lista para comenzar.")
        return
    if refresh:
        _refresh_histories(symbols, history_loader)
    histories = st.session_state.get("_technical_histories", {})
    snapshots = []
    now = datetime.now(UTC)
    for symbol in symbols:
        history = histories.get(symbol)
        if isinstance(history, MarketHistory):
            snapshots.append(analyze_history(history, now))
        elif isinstance(history, TechnicalSnapshot):
            snapshots.append(history)
        else:
            snapshots.append(TechnicalSnapshot(symbol, UNAVAILABLE, "Selecciona Actualizar señales."))
    visible = [item for item in snapshots if signal_filter == "Todas" or item.signal == signal_filter]
    updated = st.session_state.get("_technical_updated")
    st.caption(f"{len(visible)} de {len(symbols)} acciones · "
               + (f"última consulta {updated} (UTC)" if updated else "pendientes de primera consulta"))
    if not visible:
        st.info("Ninguna acción tiene esta señal en la consulta actual.")
        return
    table = pd.DataFrame([{
        "Acción": item.symbol, "Moneda": histories[item.symbol].currency
        if isinstance(histories.get(item.symbol), MarketHistory) else None,
        "Último cierre": item.close, "Var. diaria (%)": item.daily_change * 100
        if item.daily_change is not None else None,
        "Volumen relativo": item.relative_volume, "RSI 14": item.rsi,
        "Señal": item.signal, "Sesión": item.as_of,
    } for item in visible])
    table_signature = repr((signal_filter, tuple(item.symbol for item in visible),
                            st.session_state.get("_technical_refresh_id")))
    table_key = "technical_table_" + sha256(table_signature.encode()).hexdigest()
    # Keep native numbers: text-formatted values would sort lexicographically in the grid.
    display = table.copy()
    numeric_formats = {
        "Último cierre": "%.2f", "Var. diaria (%)": "%+.2f",
        "Volumen relativo": "%.2f", "RSI 14": "%.2f",
    }
    for column in numeric_formats:
        display[column] = pd.to_numeric(display[column], errors="coerce")
    display["Moneda"] = display["Moneda"].fillna("—")
    display["Sesión"] = display["Sesión"].map(lambda value: "—" if pd.isna(value) else str(value))
    selection = st.dataframe(
        display,
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key=table_key, height=min(290, 38 + len(visible) * 36),
        column_config={
            "Acción": st.column_config.TextColumn("Acción", pinned=True),
            **{name: st.column_config.NumberColumn(name, format=number_format)
               for name, number_format in numeric_formats.items()},
        },
    )
    rows = selection.selection.rows
    event_key = (table_key, tuple(rows), tuple(item.symbol for item in visible))
    if st.session_state.get("_technical_table_event") != event_key:
        if rows and 0 <= rows[0] < len(visible):
            st.session_state["technical_detail_widget"] = visible[rows[0]].symbol
        st.session_state["_technical_table_event"] = event_key
    options = [item.symbol for item in visible]
    if st.session_state.get("technical_detail_widget") not in options:
        st.session_state["technical_detail_widget"] = options[0]
    selected = detail_control.selectbox("Acción para revisar", options, key="technical_detail_widget")
    snapshot = next(item for item in visible if item.symbol == selected)
    if snapshot.signal == UNAVAILABLE:
        st.info(f"{selected}: {snapshot.reason}")
        return
    render_technical_detail(histories[selected], snapshot, cost, slippage)
