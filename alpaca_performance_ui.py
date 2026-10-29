"""Evidence separated by entry provenance, with a transparent daily hold comparison."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alpaca_paper import AlpacaPaperError
from alpaca_performance import cohort_summary, compare_to_hold
from technical_analysis import MarketHistory, completed_bars


def render_performance(rows, flows, limitations, cost, history_loader):
    st.subheader("Evaluación de la estrategia")
    summary = pd.DataFrame(cohort_summary(rows)).map(
        lambda x: float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if isinstance(x, Decimal) else x
    )
    st.dataframe(summary, hide_index=True, width="stretch", column_config={
        "Neto cerrado estimado · USD": st.column_config.NumberColumn(format="%.2f"),
    })
    st.caption(
        "Una entrada con señal previa confirma cumplimiento de las condiciones al preparar; "
        "las salidas manuales se identifican en el registro. El porcentaje ganador usa entradas "
        "completamente cerradas, después de los costos supuestos. Una muestra pequeña no establece "
        "la eficacia de la estrategia."
    )
    if limitations:
        st.info("La comparación queda pendiente mientras haya ejecuciones o posiciones sin conciliar.")
        return
    eligible = [
        r
        for r in rows
        if r["Clasificación"].startswith("Coincide") and r["Presupuesto de origen"] is not None
    ]
    if not eligible:
        st.info(
            "Todavía no hay entradas de estrategia con presupuesto previo para comparar. "
            "Las pruebas técnicas permanecen en su grupo."
        )
        return
    choices = list(dict.fromkeys((r["Símbolo"], r["Presupuesto de origen"]) for r in eligible))
    selected = st.selectbox(
        "Acción y presupuesto de la comparación",
        choices,
        format_func=lambda value: value[0] + " · " + value[1][-8:],
        key="technical_alpaca_order_compare_scope",
    )
    if st.button(
        "Calcular comparación al cierre diario",
        disabled=history_loader is None,
        key="technical_alpaca_order_compare_run",
    ):
        try:
            history = history_loader(selected[0])
            if not isinstance(history, MarketHistory) or history.currency != "USD":
                raise AlpacaPaperError("La comparación requiere precios del mismo símbolo en USD.")
            bars = completed_bars(history, datetime.now(UTC))
            frame, stats = compare_to_hold(rows, flows, selected[0], bars, selected[1], cost)
            figure = go.Figure()
            for column, color in ((frame.columns[0], "#245b9e"), (frame.columns[1], "#777777")):
                figure.add_scatter(
                    x=frame.index,
                    y=frame[column],
                    name=column,
                    mode="lines",
                    line={"color": color, "width": 2},
                )
            figure.update_layout(
                template="plotly_white",
                height=330,
                yaxis_title="USD",
                xaxis={"tickformat": "%d %b %Y", "nticks": 5},
                margin={"l": 15, "r": 15, "t": 70, "b": 15},
                legend={"orientation": "h", "yanchor": "bottom", "y": 1.03, "x": 0},
            )
            # Daily observations should never acquire intraday labels on short histories.
            if len(frame) <= 5:
                figure.update_xaxes(
                    tickmode="array", tickvals=list(frame.index),
                    range=[frame.index[0] - pd.Timedelta(hours=12),
                           frame.index[-1] + pd.Timedelta(hours=12)],
                )
            st.plotly_chart(figure, width="stretch", key="technical_alpaca_order_compare_chart")
            a, b, c = st.columns(3)
            a.metric("Rendimiento de la prueba", f"{100 * stats['strategy_return']:+.2f}%")
            b.metric("Mantener primera entrada", f"{100 * stats['hold_return']:+.2f}%")
            c.metric("Máxima caída al cierre", f"{100 * stats['max_drawdown']:.2f}%")
            st.caption(
                f"Hasta {stats['as_of']} · capital de referencia {stats['capital']:,.2f} USD, "
                "tomado del límite por acción capturado antes de las entradas. Ambas alternativas "
                "compran inicialmente la misma cantidad y usan los mismos costos. La comparación "
                "mantiene la primera entrada y el efectivo restante; la prueba incorpora los flujos "
                "de sus operaciones. La caída se mide entre cierres diarios, no intradía."
            )
            st.download_button(
                "Descargar comparación CSV",
                frame.to_csv().encode("utf-8-sig"),
                "comparacion_paper.csv",
                "text/csv",
                key="technical_alpaca_order_compare_download",
            )
        except Exception as exc:
            if isinstance(exc, AlpacaPaperError):
                st.info(str(exc))
            else:
                st.info("No se pudo completar la comparación; vuelve a actualizar precios y ejecuciones.")
