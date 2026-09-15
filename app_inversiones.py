"""Secure V2 Streamlit interface for the portfolio optimizer."""

import logging
from datetime import date
from hashlib import sha256

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from access import require_access
from backtesting import run_holdout_backtest
from currencies import convert_prices, currency_map, download_fx
from fixed_income import merge_cetes_index, read_banxico_cetes_csv
from fx_comparison import render_comparison
from instruments import analysis_inputs, display_catalog, load_catalog
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
    StressReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows, parse_asset_shocks

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

instrument_catalog = load_catalog()
with st.expander("Catálogo piloto de instrumentos México y SIC"):
    st.dataframe(display_catalog(instrument_catalog), hide_index=True, use_container_width=True)
    available_inputs = analysis_inputs(instrument_catalog)
    examples = ", ".join(
        f"{row.analysis_symbol} ({row.analysis_currency})"
        for row in available_inputs.itertuples(index=False)
    )
    st.caption(
        "Compatibles hoy con el motor histórico: " + examples + ". "
        "En SIC se usa una aproximación con la serie del mercado de origen convertida a MXN; "
        "no representa el precio local ejecutable. CETES puede añadirse mediante un CSV validado; "
        "bonos, efectivo y fondos permanecen fuera hasta integrar su valoración específica."
    )
    st.download_button(
        "Descargar catálogo y notas CSV",
        instrument_catalog.to_csv(index=False).encode("utf-8-sig"),
        "catalogo_instrumentos_mx_sic.csv",
        "text/csv",
    )

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
            "Un porcentaje por activo, en el mismo orden; si cargas CETES, su peso va al final. "
            "Deben sumar 100. "
            "No se guarda en una base de datos."
        ),
    )
    cetes_upload = st.file_uploader(
        "Serie CETES de Banxico (opcional)",
        type=["csv"],
        help=(
            "CSV con Fecha, Precio, Plazo y Tasa opcional en % anual. Máximo 5 MB; "
            "sólo para análisis en MXN. Se rechazan cambios anticipados de emisión."
        ),
    )
    cetes_name_input = st.text_input(
        "Nombre de la serie CETES", "CETES28", help="Etiqueta que aparecerá en tablas y reportes."
    )
    st.download_button(
        "Descargar plantilla CETES CSV",
        b"Fecha,Precio,Plazo,Tasa\n",
        "plantilla_cetes.csv",
        "text/csv",
    )
    analyze = st.button("Analizar portafolio", type="primary", use_container_width=True)

cetes_contents = cetes_upload.getvalue() if cetes_upload is not None else b""
cetes_fingerprint = sha256(cetes_contents).hexdigest() if cetes_contents else None
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
    cetes_fingerprint,
    cetes_name_input,
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
    asset_count = len(tickers) + bool(cetes_contents)
    if asset_count * max_weight < 1:
        raise PortfolioError(
            f"Con {asset_count} activos, el peso máximo debe ser al menos {1 / asset_count:.1%}."
        )
    cetes_result = None
    with st.spinner("Descargando y validando datos..."):
        download = cached_prices(tickers, start_date, end_date)
        if download.rejected_tickers:
            raise PortfolioError("Corrige los tickers sin datos: " + ", ".join(download.rejected_tickers))
        fx = cached_fx(quotes, base_currency, start_date, end_date)
        prices = convert_prices(download.prices, quotes, base_currency, fx)
        removed = len(download.prices) - len(prices)
        if removed:
            st.warning(f"Se excluyeron {removed} fechas sin tipo de cambio; no se rellenaron precios.")
        if cetes_contents:
            if base_currency != "MXN":
                raise PortfolioError("La serie CETES sólo puede añadirse con moneda base MXN.")
            cetes_name = normalize_tickers([cetes_name_input])[0]
            if cetes_name in prices.columns:
                raise PortfolioError("El nombre de la serie CETES coincide con otro ticker.")
            cetes_result = read_banxico_cetes_csv(
                cetes_contents,
                date_column="Fecha",
                price_column="Precio",
                term_column="Plazo",
                name=cetes_name,
            )
            prepared_index = cetes_result.index.loc[
                pd.Timestamp(start_date):pd.Timestamp(end_date)
            ]
            prices = merge_cetes_index(prices, prepared_index)
        analysis_tickers = tuple(str(column) for column in prices.columns)
        analysis_quotes = quotes | ({cetes_name: "MXN"} if cetes_result is not None else {})
        data_source = "Yahoo Finance mediante yfinance; precios ajustados y FX histórico"
        if cetes_result is not None:
            data_source += (
                f"; {cetes_name}: CSV aportado por el usuario y preparado desde precio/plazo, "
                f"SHA-256 {cetes_fingerprint[:12]}"
            )
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
        equal_weights = np.full(len(analysis_tickers), 1 / len(analysis_tickers))
        equal_return, equal_volatility, equal_sharpe = portfolio_statistics(
            equal_weights, mean_returns, covariance, risk_free_rate
        )
        alternatives.append(PortfolioAlternative(
            "Pesos iguales",
            PortfolioMetrics(equal_weights, equal_return, equal_volatility, equal_sharpe),
            calculate_risk_metrics(returns, equal_weights, confidence, horizon),
        ))
        if current_weights_input.strip():
            current_weights = parse_current_weights(current_weights_input, len(analysis_tickers))
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
    if cetes_result is not None:
        relevant_rolls = [
            item for item in cetes_result.roll_dates if prices.index.min() <= item <= prices.index.max()
        ]
        relevant_maturities = [
            item
            for item in cetes_result.maturity_dates
            if prices.index.min() <= item <= prices.index.max()
        ]
        st.info(
            f"Serie {cetes_name} integrada desde archivo: {len(relevant_rolls)} renovación(es) "
            "por vencimiento, "
            f"{len(relevant_maturities)} vencimiento(s) reconocido(s). Revisa las fechas antes de "
            "usar los resultados."
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
        if cetes_result is not None:
            st.download_button(
                "Índice CETES preparado CSV",
                cetes_result.index.rename("Indice retorno total").to_csv().encode("utf-8"),
                "cetes_indice_preparado.csv",
                "text/csv",
            )

    weights = pd.DataFrame(
        {
            "Ticker": analysis_tickers,
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
        st.write(f"**Activos válidos:** {len(analysis_tickers)}")
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
                flow_mode = st.radio(
                    "Flujo mensual", ["Sin flujos", "Aportaciones", "Retiros"], horizontal=True
                )
                contribution, withdrawal = 0.0, 0.0
                if flow_mode == "Aportaciones":
                    contribution = st.number_input(
                        f"Aportación mensual ({base_currency})", min_value=0.0,
                        value=0.0, step=1000.0,
                    )
                elif flow_mode == "Retiros":
                    withdrawal = st.number_input(
                        f"Retiro mensual ({base_currency})", min_value=0.0,
                        value=0.0, step=1000.0,
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
                    months=years * 12, paths=path_count,
                    monthly_contribution=contribution, monthly_withdrawal=withdrawal,
                    annual_fee=fee, transaction_cost_bps=trading_cost,
                    rebalance_months=rebalance_months, inflation_rate=inflation,
                    method=method, seed=int(seed), block_days=block_days,
                )
                simulation_report = SimulationReport(
                    alternative_name=selected, result=simulated,
                    monthly_contribution=contribution, monthly_withdrawal=withdrawal,
                    annual_fee=fee,
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
                if withdrawal > 0:
                    sim_cols[3].metric(
                        "Con retiro no cubierto", f"{simulated.probability_of_shortfall:.1%}"
                    )
                    bands["Retiros programados acumulados"] = withdrawal * bands["Mes"]
                else:
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
                    x=bands["Mes"], y=bands["Capital aportado"],
                    name="Capital inicial" if withdrawal > 0 else "Capital aportado",
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
                if withdrawal > 0:
                    st.caption(
                        f"Retiros programados: {withdrawal * years * 12:,.0f} {base_currency}; "
                        f"mediana efectivamente retirada: "
                        f"{np.median(simulated.total_withdrawn):,.0f} {base_currency}. "
                        "Si una trayectoria no alcanza para un retiro, se vende lo disponible "
                        "y el patrimonio queda en cero. No se permite saldo negativo."
                    )
                st.caption(
                    "La comisión se aplica diariamente; el costo de operación se aplica "
                    "a compras, ventas por retiros y rebalanceos. El valor real descuenta "
                    "la inflación supuesta. No se modelan impuestos, spreads ni liquidez."
                )

    stress_report = None
    with st.expander("Pruebas de estrés históricas e hipotéticas"):
        st.caption(
            "Las ventanas históricas identifican pérdidas observadas en esta muestra. "
            "El escenario hipotético aplica cambios simultáneos elegidos por ti."
        )
        if st.checkbox("Calcular pruebas de estrés"):
            historical_parts = []
            for alternative in alternatives:
                history = historical_worst_windows(
                    returns, alternative.metrics.weights, horizons=(1, 5, 21)
                )
                history.insert(0, "Escenario", alternative.name)
                historical_parts.append(history)
            stress_history = pd.concat(historical_parts, ignore_index=True)
            display_history = stress_history.copy()
            display_history["Inicio"] = display_history["Inicio"].dt.date
            display_history["Fin"] = display_history["Fin"].dt.date
            display_history["Peor retorno"] = display_history["Peor retorno"].map(
                lambda value: f"{value:.2%}"
            )
            st.write("Peores ventanas históricas con rebalanceo diario:")
            st.dataframe(display_history, hide_index=True, use_container_width=True)

            shocks = None
            shock_results = None
            if st.checkbox("Añadir shock hipotético por activo"):
                raw_shocks = st.text_input(
                    "Cambios por activo en %, en el mismo orden",
                    value=", ".join("-10" for _ in analysis_tickers),
                    help="Ejemplo para dos activos: -20, -5. El mínimo por activo es -100%.",
                )
                shocks_array = parse_asset_shocks(raw_shocks, len(analysis_tickers))
                shocks = pd.Series(shocks_array, index=analysis_tickers, name="Shock")
                shock_results = {
                    alternative.name: deterministic_shock(
                        alternative.metrics.weights, shocks_array, portfolio_value,
                        labels=analysis_tickers,
                    )
                    for alternative in alternatives
                }
                shock_table = pd.DataFrame({
                    "Escenario": list(shock_results),
                    "Cambio de cartera": [
                        f"{item.portfolio_return:.2%}" for item in shock_results.values()
                    ],
                    f"Valor estresado ({base_currency})": [
                        f"{item.stressed_value:,.0f}" for item in shock_results.values()
                    ],
                    f"Pérdida ({base_currency})": [
                        f"{item.loss_amount:,.0f}" for item in shock_results.values()
                    ],
                })
                st.write("Resultado del shock simultáneo:")
                st.dataframe(shock_table, hide_index=True, use_container_width=True)
                contributions = pd.DataFrame({
                    name: result.contributions for name, result in shock_results.items()
                })
                st.write("Contribución de cada activo al cambio total:")
                st.dataframe(contributions.style.format("{:.2%}"), use_container_width=True)
            stress_report = StressReport(stress_history, shocks, shock_results)
            st.caption(
                "El estrés histórico usa pesos constantes al cierre de cada sesión. El shock "
                "hipotético es estático, no tiene probabilidad asignada y no modela recuperación, "
                "liquidez, suspensiones ni incumplimientos."
            )

    with st.expander("Validación fuera de muestra: una fecha de corte"):
        st.caption(
            "Los pesos se estiman una sola vez con la primera parte de la muestra. "
            "La parte posterior evalúa una cartera hipotética mantenida sin rebalanceo. "
            "Cambiar la fecha de corte después de ver resultados puede sesgar la conclusión."
        )
        if st.checkbox("Comparar resultados fuera de muestra"):
            if removed:
                st.warning(
                    "Hay fechas omitidas por falta de FX; resuelve esos huecos antes de "
                    "usar retornos supuestamente diarios en la validación."
                )
            else:
                training_percent = st.slider("Muestra para estimación (%)", 50, 90, 70, 5)
                entry_cost_bps = st.number_input(
                    "Costo inicial por rotación (puntos base)",
                    min_value=0.0, max_value=500.0, value=0.0, step=5.0,
                )
                backtest = run_holdout_backtest(
                    returns, training_fraction=training_percent / 100,
                    risk_free_rate=risk_free_rate, max_weight=max_weight,
                    current_weights=(
                        current_weights if current_weights_input.strip() else None
                    ),
                    trading_cost_bps=entry_cost_bps,
                )
                st.write(
                    f"**Estimación:** {backtest.training_start.date()} a "
                    f"{backtest.training_end.date()} "
                    f"({backtest.training_observations} retornos). "
                    f"**Evaluación:** {backtest.evaluation_start.date()} a "
                    f"{backtest.evaluation_end.date()} "
                    f"({backtest.evaluation_observations} retornos)."
                )
                display = backtest.summary.copy()
                for column in (
                    "Retorno total neto", "Retorno anualizado neto",
                    "Volatilidad anualizada", "Máxima caída", "Rotación inicial",
                    "Costo inicial sobre capital",
                ):
                    display[column] = display[column].map(lambda value: f"{value:.2%}")
                display["Sharpe realizado"] = display["Sharpe realizado"].map(
                    lambda value: f"{value:.2f}"
                )
                st.dataframe(display, use_container_width=True)
                st.line_chart(backtest.equity_curves, y_label="Capital relativo (1 = inicio)")
                with st.expander("Pesos estimados antes de la evaluación"):
                    st.dataframe(
                        backtest.allocations.style.format("{:.2%}"),
                        use_container_width=True,
                    )
                st.download_button(
                    "Descargar resultados fuera de muestra CSV",
                    backtest.summary.to_csv().encode("utf-8-sig"),
                    "validacion_fuera_de_muestra.csv", "text/csv",
                )
                st.caption(
                    "El costo se aplica sólo a la rotación inicial desde la cartera actual ingresada; "
                    "sin cartera actual se supone una posición inicial ya asignada y costo cero. "
                    "No se modelan rebalanceos, comisiones continuas, spreads, impuestos, "
                    "deslizamiento ni liquidez. El resultado es hipotético, no una operación real."
                )

    render_comparison(
        download.prices, analysis_quotes, base_currency, fx, max_sharpe.weights,
        risk_free_rate, max_weight, confidence, horizon,
    )

    pdf = create_pdf_report(
        analysis_tickers,
        prices.index.min().date(),
        prices.index.max().date(),
        max_sharpe,
        risk,
        portfolio_value,
        base_currency=base_currency,
        risk_free_rate=risk_free_rate,
        max_weight=max_weight,
        observations=len(returns),
        quotes=analysis_quotes,
        data_source=data_source,
    )
    st.download_button(
        "Descargar reporte metodológico PDF", pdf, f"reporte_portafolio_{date.today()}.pdf", "application/pdf"
    )
    comparison_pdf = create_comparison_pdf_report(
        analysis_tickers,
        prices.index.min().date(),
        prices.index.max().date(),
        tuple(alternatives),
        portfolio_value,
        base_currency=base_currency,
        risk_free_rate=risk_free_rate,
        observations=len(returns),
        quotes=analysis_quotes,
        data_source=data_source,
        simulation=simulation_report,
        stress=stress_report,
    )
    st.download_button(
        (
            "Descargar comparativo ampliado PDF"
            if simulation_report is not None or stress_report is not None
            else "Descargar comparativo de carteras PDF"
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
