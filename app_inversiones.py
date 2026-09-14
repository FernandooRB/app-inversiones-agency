"""Secure V2 Streamlit interface for the portfolio optimizer."""

import logging
from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from access import require_access
from currencies import convert_prices, currency_map, download_fx
from fx_comparison import render_comparison
from portfolio_core import (
    PortfolioError,
    PortfolioMetrics,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    download_adjusted_prices,
    efficient_frontier,
    normalize_tickers,
    optimize_portfolio,
    parse_current_weights,
    portfolio_statistics,
    random_portfolios,
)
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from simulation import simulate_portfolio_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="Optimizador de Portafolios V2", page_icon="📊", layout="wide")
require_access()


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_prices(tickers: tuple[str, ...], start: date, end: date):
    return download_adjusted_prices(tickers, start, end)


def percent(value: float) -> str:
    return f"{value:.2%}"


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_fx(quotes, base, start, end):
    return download_fx(quotes, base, start, end)


st.title("Optimizador de Portafolios V2")
st.caption("Análisis histórico educativo · No constituye una recomendación personalizada de inversión")

with st.sidebar:
    st.header("Configuración")
    tickers_input = st.text_input("Tickers", "AAPL, MSFT, GOOG, TSLA", help="Máximo 25; separados por comas.")
    quote_input = st.text_input("Monedas de cotización, en el mismo orden", "USD, USD, USD, USD")
    base_currency = st.selectbox(
        "Moneda base del análisis", ["USD", "MXN", "EUR", "GBP", "CAD", "JPY", "CHF"]
    )
    st.caption("Verifica cada moneda en el mercado de cotización; no se deduce del ticker.")
    start_date = st.date_input("Fecha inicial", value=date(2023, 1, 1), min_value=date(2000, 1, 1))
    end_date = st.date_input("Fecha final", value=date.today(), max_value=date.today())
    risk_free_rate = (
        st.number_input(
            "Tasa libre de riesgo anual (%)", min_value=-5.0, max_value=50.0, value=5.0, step=0.25
        )
        / 100
    )
    st.caption(
        "Supuesto manual: verifica la tasa para la moneda base y el periodo; no se consulta una fuente."
    )
    max_weight = st.slider("Peso máximo por activo", 10, 100, 60, 5) / 100
    confidence = st.select_slider("Confianza de VaR", options=[0.90, 0.95, 0.975, 0.99], value=0.95)
    horizon = st.selectbox(
        "Horizonte de riesgo", [1, 5, 10, 21], index=0, format_func=lambda value: f"{value} día(s)"
    )
    portfolio_value = st.number_input(
        f"Valor del portafolio ({base_currency})", min_value=0.0, value=100_000.0, step=10_000.0
    )
    current_weights_input = st.text_input(
        "Cartera actual, pesos en % (opcional)",
        help=(
            "Un porcentaje por ticker, en el mismo orden; deben sumar 100. "
            "No se guarda en una base de datos."
        ),
    )
    analyze = st.button("Analizar portafolio", type="primary", use_container_width=True)

settings = (
    tickers_input,
    start_date,
    end_date,
    risk_free_rate,
    max_weight,
    confidence,
    horizon,
    portfolio_value,
    quote_input,
    base_currency,
    current_weights_input,
)
if analyze:
    st.session_state["analysis_settings"] = settings
if st.session_state.get("analysis_settings") != settings:
    st.info("Configura los parámetros y selecciona **Analizar portafolio**.")
    with st.expander("Metodología y límites"):
        st.markdown(
            """
            - Utiliza precios de cierre ajustados y rendimientos aritméticos históricos.
            - El rendimiento mostrado es una media histórica anualizada; no es un pronóstico.
            - La frontera eficiente usa optimización de mínima varianza con posiciones largas.
            - VaR y CVaR dependen de la muestra y no representan la pérdida máxima posible.
            - Los precios se convierten a la moneda base con tipos de cambio históricos disponibles.
            """
        )
    st.stop()

try:
    tickers = tuple(normalize_tickers(tickers_input))
    quotes = currency_map(tickers, quote_input)
    if len(tickers) * max_weight < 1:
        raise PortfolioError(
            f"Con {len(tickers)} activos, el peso máximo debe ser al menos {1 / len(tickers):.1%}."
        )
    with st.spinner("Descargando y validando datos..."):
        download = cached_prices(tickers, start_date, end_date)
        if download.rejected_tickers:
            raise PortfolioError("Corrige los tickers sin datos: " + ", ".join(download.rejected_tickers))
        fx = cached_fx(quotes, base_currency, start_date, end_date)
        prices = convert_prices(download.prices, quotes, base_currency, fx)
        removed = len(download.prices) - len(prices)
        if removed:
            st.warning(f"Se excluyeron {removed} fechas sin tipo de cambio; no se rellenaron precios.")
        returns = calculate_returns(prices)
        mean_returns, covariance = annualized_moments(returns)
        max_sharpe = optimize_portfolio(mean_returns, covariance, risk_free_rate, "max_sharpe", max_weight)
        min_volatility = optimize_portfolio(
            mean_returns, covariance, risk_free_rate, "min_volatility", max_weight
        )
        frontier = efficient_frontier(mean_returns, covariance, max_weight)
        random_set = random_portfolios(mean_returns, covariance, risk_free_rate, max_weight=max_weight)
        risk = calculate_risk_metrics(returns, max_sharpe.weights, confidence, horizon)
        alternatives = [
            PortfolioAlternative("Máximo Sharpe", max_sharpe, risk),
            PortfolioAlternative(
                "Mínima volatilidad", min_volatility,
                calculate_risk_metrics(returns, min_volatility.weights, confidence, horizon),
            ),
        ]
        equal_weights = np.full(len(tickers), 1 / len(tickers))
        equal_return, equal_volatility, equal_sharpe = portfolio_statistics(
            equal_weights, mean_returns, covariance, risk_free_rate
        )
        alternatives.append(PortfolioAlternative(
            "Pesos iguales",
            PortfolioMetrics(equal_weights, equal_return, equal_volatility, equal_sharpe),
            calculate_risk_metrics(returns, equal_weights, confidence, horizon),
        ))
        if current_weights_input.strip():
            current_weights = parse_current_weights(current_weights_input, len(tickers))
            current_return, current_volatility, current_sharpe = portfolio_statistics(
                current_weights, mean_returns, covariance, risk_free_rate
            )
            alternatives.append(PortfolioAlternative(
                "Cartera actual",
                PortfolioMetrics(current_weights, current_return, current_volatility, current_sharpe),
                calculate_risk_metrics(returns, current_weights, confidence, horizon),
            ))

    if download.rejected_tickers:
        st.warning("Tickers excluidos por falta de datos: " + ", ".join(download.rejected_tickers))
    st.success(
        f"Análisis realizado con {len(returns):,} observaciones, del "
        f"{prices.index.min().date()} al {prices.index.max().date()}. Moneda: {base_currency}."
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Media histórica anualizada", percent(max_sharpe.annual_return))
    col2.metric("Volatilidad anualizada", percent(max_sharpe.annual_volatility))
    col3.metric("Sharpe histórico", f"{max_sharpe.sharpe_ratio:.2f}")
    col4.metric(f"VaR histórico ({confidence:.1%})", percent(risk.historical_var))

    figure = px.scatter(
        random_set,
        x="Volatilidad",
        y="Retorno",
        color="Sharpe",
        opacity=0.35,
        title="Conjunto de oportunidades y frontera eficiente",
        labels={"Retorno": "Media histórica anualizada", "Volatilidad": "Volatilidad anualizada"},
    )
    figure.add_trace(
        go.Scatter(
            x=frontier["Volatilidad"],
            y=frontier["Retorno"],
            mode="markers" if len(frontier) == 1 else "lines",
            name="Punto eficiente" if len(frontier) == 1 else "Frontera eficiente",
            line={"width": 4, "color": "#00CC96"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[max_sharpe.annual_volatility],
            y=[max_sharpe.annual_return],
            mode="markers",
            name="Máximo Sharpe",
            marker={"symbol": "star", "size": 18, "color": "#EF553B"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[min_volatility.annual_volatility],
            y=[min_volatility.annual_return],
            mode="markers",
            name="Mínima volatilidad",
            marker={"symbol": "diamond", "size": 13, "color": "#636EFA"},
        )
    )
    figure.update_layout(
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        margin={"t": 110, "r": 100, "b": 60},
        coloraxis_colorbar={"title": "Sharpe", "x": 1.02, "y": 0.5, "len": 0.7},
    )
    figure.update_xaxes(tickformat=".1%")
    figure.update_yaxes(tickformat=".1%")
    st.plotly_chart(figure, use_container_width=True)
    st.caption(
        "Los puntos coloreados son asignaciones aleatorias factibles; pueden incluir carteras dominadas. "
        "No representan simulaciones de precios futuros."
    )
    if len(frontier) == 1:
        st.info("Bajo estas restricciones, la frontera eficiente se reduce a un punto.")
    if np.allclose(max_sharpe.weights, min_volatility.weights, atol=1e-6, rtol=0):
        st.caption("Máximo Sharpe y mínima volatilidad coinciden; sus marcadores se superponen.")
    st.caption(
        "La media anualizada no es el rendimiento acumulado del periodo. "
        "La tasa libre de riesgo es un supuesto del usuario, sin verificación automática."
    )
    with st.expander("Datos utilizados para contrastar el cálculo"):
        st.write("Descarga las series y compáralas con una fuente independiente.")
        st.download_button(
            "Precios originales CSV", download.prices.to_csv().encode("utf-8"),
            "precios_originales.csv", "text/csv",
        )
        st.download_button(
            "Precios en moneda base CSV", prices.to_csv().encode("utf-8"),
            "precios_moneda_base.csv", "text/csv",
        )
        if fx:
            st.download_button(
                "Tipos de cambio CSV", pd.DataFrame(fx).to_csv().encode("utf-8"),
                "tipos_cambio.csv", "text/csv",
            )

    weights = pd.DataFrame(
        {
            "Ticker": download.valid_tickers,
            "Peso máximo Sharpe": max_sharpe.weights,
            "Peso mínima volatilidad": min_volatility.weights,
            "Contribución al retorno": max_sharpe.weights * mean_returns.to_numpy(),
        }
    )
    st.subheader("Escenarios de asignación del modelo (análisis histórico)")
    st.dataframe(
        weights.style.format(
            {
                "Peso máximo Sharpe": "{:.2%}",
                "Peso mínima volatilidad": "{:.2%}",
                "Contribución al retorno": "{:.2%}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Riesgo de cola")
        st.write(
            f"**VaR paramétrico:** {percent(risk.parametric_var)} "
            f"({portfolio_value * risk.parametric_var:,.2f})"
        )
        st.write(
            f"**VaR histórico:** {percent(risk.historical_var)} "
            f"({portfolio_value * risk.historical_var:,.2f})"
        )
        st.write(
            f"**CVaR histórico:** {percent(risk.historical_cvar)} "
            f"({portfolio_value * risk.historical_cvar:,.2f})"
        )
        st.caption(f"Horizonte: {horizon} día(s) hábil(es). Las cifras son magnitudes positivas de pérdida.")
    with right:
        st.subheader("Calidad de la estimación")
        st.write(f"**Activos válidos:** {len(download.valid_tickers)}")
        st.write(f"**Observaciones comunes:** {len(returns):,}")
        st.write(f"**Tasa libre de riesgo:** {risk_free_rate:.2%}")
        st.write(f"**Límite por activo:** {max_weight:.0%}")

    simulation_report = None
    with st.expander("Monte Carlo: escenarios hipotéticos del patrimonio"):
        st.caption(
            "Las trayectorias usan retornos históricos remuestreados en bloques o una distribución "
            "lognormal correlacionada estimada con la muestra. No son rendimientos previstos."
        )
        if st.checkbox("Calcular trayectorias hipotéticas"):
            if removed:
                st.warning(
                    "Hay fechas de precios sin tipo de cambio dentro de la muestra. "
                    "Resuelve esos huecos antes de simular retornos diarios."
                )
            else:
                selected = st.selectbox("Escenario de asignación", [item.name for item in alternatives])
                method_label = st.selectbox(
                    "Método", ["Bloques históricos", "Lognormal correlacionado"]
                )
                method = "bootstrap_blocks" if method_label == "Bloques históricos" else "lognormal"
                years = st.slider("Horizonte (años)", 1, 10, 3)
                path_count = st.slider("Trayectorias", 100, 2000, 500, 100)
                contribution = st.number_input(
                    f"Aportación mensual ({base_currency})", min_value=0.0, value=0.0, step=1000.0
                )
                fee = st.number_input(
                    "Comisión anual supuesta (%)", min_value=0.0, max_value=10.0,
                    value=0.0, step=0.25,
                ) / 100
                trading_cost = st.number_input(
                    "Costo por operación (puntos base)", min_value=0.0, max_value=500.0,
                    value=0.0, step=5.0,
                )
                inflation = st.number_input(
                    "Inflación anual supuesta (%)", min_value=-20.0, max_value=50.0,
                    value=4.0, step=0.25,
                ) / 100
                rebalance_label = st.selectbox(
                    "Rebalanceo", ["Sin rebalanceo", "Cada 3 meses", "Cada 6 meses", "Cada 12 meses"]
                )
                rebalance_months = {
                    "Sin rebalanceo": None, "Cada 3 meses": 3,
                    "Cada 6 meses": 6, "Cada 12 meses": 12,
                }[rebalance_label]
                block_days = 21
                if method == "bootstrap_blocks":
                    block_days = st.slider(
                        "Tamaño del bloque histórico (sesiones)", 1, min(63, len(returns)),
                        min(21, len(returns)),
                    )
                seed = st.number_input("Semilla reproducible", min_value=0, value=42, step=1)
                scenario = next(item for item in alternatives if item.name == selected)
                simulated = simulate_portfolio_paths(
                    returns, scenario.metrics.weights, initial_value=portfolio_value,
                    months=years * 12, paths=path_count, monthly_contribution=contribution,
                    annual_fee=fee, transaction_cost_bps=trading_cost,
                    rebalance_months=rebalance_months, inflation_rate=inflation,
                    method=method, seed=int(seed), block_days=block_days,
                )
                simulation_report = SimulationReport(
                    alternative_name=selected, result=simulated,
                    monthly_contribution=contribution, annual_fee=fee,
                    transaction_cost_bps=trading_cost, inflation_rate=inflation,
                    rebalance_months=rebalance_months, block_days=block_days,
                )
                bands = simulated.bands()
                end = bands.iloc[-1]
                sim_cols = st.columns(4)
                sim_cols[0].metric("Mediana final nominal", f"{end['Mediana']:,.0f} {base_currency}")
                sim_cols[1].metric("Percentil 5 nominal", f"{end['Percentil 5']:,.0f} {base_currency}")
                sim_cols[2].metric(
                    "Mediana final real",
                    f"{np.median(simulated.real_terminal_values):,.0f} {base_currency}",
                )
                sim_cols[3].metric(
                    "Bajo capital aportado", f"{simulated.probability_below_contributions:.1%}"
                )
                sim_chart = go.Figure()
                sim_chart.add_trace(go.Scatter(
                    x=bands["Mes"], y=bands["Percentil 95"],
                    name="Percentil 95", line={"width": 0}, showlegend=False,
                ))
                sim_chart.add_trace(go.Scatter(
                    x=bands["Mes"], y=bands["Percentil 5"], fill="tonexty",
                    name="Rango 5–95 %", line={"width": 0}, fillcolor="rgba(31,119,180,0.20)",
                ))
                sim_chart.add_trace(go.Scatter(
                    x=bands["Mes"], y=bands["Mediana"], name="Mediana",
                    line={"color": "#1f77b4", "width": 3},
                ))
                sim_chart.add_trace(go.Scatter(
                    x=bands["Mes"], y=bands["Capital aportado"], name="Capital aportado",
                    line={"color": "#555555", "dash": "dash"},
                ))
                sim_chart.update_layout(
                    xaxis_title="Mes", yaxis_title=f"Valor nominal ({base_currency})",
                    title="Distribución simulada del patrimonio",
                )
                st.plotly_chart(sim_chart, use_container_width=True)
                st.download_button(
                    "Descargar percentiles mensuales CSV", bands.to_csv(index=False).encode("utf-8"),
                    "montecarlo_percentiles.csv", "text/csv",
                )
                st.caption(
                    "Capital aportado = inicial + aportaciones nominales. La comisión se aplica "
                    "diariamente; el costo de operación se aplica al capital inicial, aportaciones "
                    "y volumen negociado al rebalancear. El valor real descuenta la inflación supuesta. "
                    "No se modelan impuestos, spreads ni liquidez."
                )

    render_comparison(
        download.prices, quotes, base_currency, fx, max_sharpe.weights,
        risk_free_rate, max_weight, confidence, horizon,
    )

    pdf = create_pdf_report(
        download.valid_tickers,
        prices.index.min().date(),
        prices.index.max().date(),
        max_sharpe,
        risk,
        portfolio_value,
        base_currency=base_currency,
        risk_free_rate=risk_free_rate,
        max_weight=max_weight,
        observations=len(returns),
        quotes=quotes,
    )
    st.download_button(
        "Descargar reporte metodológico PDF", pdf, f"reporte_portafolio_{date.today()}.pdf", "application/pdf"
    )
    comparison_pdf = create_comparison_pdf_report(
        download.valid_tickers,
        prices.index.min().date(),
        prices.index.max().date(),
        tuple(alternatives),
        portfolio_value,
        base_currency=base_currency,
        risk_free_rate=risk_free_rate,
        observations=len(returns),
        quotes=quotes,
        simulation=simulation_report,
    )
    st.download_button(
        (
            "Descargar comparativo con Monte Carlo PDF"
            if simulation_report is not None else "Descargar comparativo de carteras PDF"
        ), comparison_pdf,
        f"comparativo_carteras_{date.today()}.pdf", "application/pdf",
    )
    st.warning(
        "Los resultados dependen de datos históricos y supuestos estadísticos. No incorporan impuestos, "
        "comisiones, liquidez ni situación personal. La conversión cambiaria no constituye una cobertura."
    )
except PortfolioError as exc:
    st.error(str(exc))
except Exception:
    LOGGER.exception("Unexpected portfolio analysis error")
    st.error("Ocurrió un error inesperado. Revisa los parámetros o inténtalo nuevamente más tarde.")
