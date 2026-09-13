"""Secure V2 Streamlit interface for the portfolio optimizer."""

import logging
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio_core import (
    PortfolioError,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    download_adjusted_prices,
    efficient_frontier,
    normalize_tickers,
    optimize_portfolio,
    random_portfolios,
)
from reporting import create_pdf_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="Optimizador de Portafolios V2", page_icon="📊", layout="wide")


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_prices(tickers: tuple[str, ...], start: date, end: date):
    return download_adjusted_prices(tickers, start, end)


def percent(value: float) -> str:
    return f"{value:.2%}"


st.title("Optimizador de Portafolios V2")
st.caption("Análisis histórico educativo · No constituye una recomendación personalizada de inversión")

with st.sidebar:
    st.header("Configuración")
    tickers_input = st.text_input("Tickers", "AAPL, MSFT, GOOG, TSLA", help="Máximo 25; separados por comas.")
    start_date = st.date_input("Fecha inicial", value=date(2023, 1, 1), min_value=date(2000, 1, 1))
    end_date = st.date_input("Fecha final", value=date.today(), max_value=date.today())
    risk_free_rate = (
        st.number_input(
            "Tasa libre de riesgo anual (%)", min_value=-5.0, max_value=50.0, value=5.0, step=0.25
        )
        / 100
    )
    max_weight = st.slider("Peso máximo por activo", 10, 100, 60, 5) / 100
    confidence = st.select_slider("Confianza de VaR", options=[0.90, 0.95, 0.975, 0.99], value=0.95)
    horizon = st.selectbox(
        "Horizonte de riesgo", [1, 5, 10, 21], index=0, format_func=lambda value: f"{value} día(s)"
    )
    portfolio_value = st.number_input("Valor del portafolio", min_value=0.0, value=100_000.0, step=10_000.0)
    analyze = st.button("Analizar portafolio", type="primary", use_container_width=True)

if not analyze:
    st.info("Configura los parámetros y selecciona **Analizar portafolio**.")
    with st.expander("Metodología y límites"):
        st.markdown(
            """
            - Utiliza precios de cierre ajustados y rendimientos aritméticos históricos.
            - El rendimiento mostrado es una media histórica anualizada; no es un pronóstico.
            - La frontera eficiente usa optimización de mínima varianza con posiciones largas.
            - VaR y CVaR dependen de la muestra y no representan la pérdida máxima posible.
            - Los activos deben ser comparables en una moneda base; esta versión no convierte divisas.
            """
        )
    st.stop()

try:
    tickers = tuple(normalize_tickers(tickers_input))
    if len(tickers) * max_weight < 1:
        raise PortfolioError(
            f"Con {len(tickers)} activos, el peso máximo debe ser al menos {1 / len(tickers):.1%}."
        )
    with st.spinner("Descargando y validando datos..."):
        download = cached_prices(tickers, start_date, end_date)
        returns = calculate_returns(download.prices)
        mean_returns, covariance = annualized_moments(returns)
        max_sharpe = optimize_portfolio(mean_returns, covariance, risk_free_rate, "max_sharpe", max_weight)
        min_volatility = optimize_portfolio(
            mean_returns, covariance, risk_free_rate, "min_volatility", max_weight
        )
        frontier = efficient_frontier(mean_returns, covariance, max_weight)
        random_set = random_portfolios(mean_returns, covariance, risk_free_rate)
        risk = calculate_risk_metrics(returns, max_sharpe.weights, confidence, horizon)

    if download.rejected_tickers:
        st.warning("Tickers excluidos por falta de datos: " + ", ".join(download.rejected_tickers))
    st.success(
        f"Análisis realizado con {len(returns):,} observaciones, del "
        f"{download.prices.index.min().date()} al {download.prices.index.max().date()}."
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
            mode="lines",
            name="Frontera eficiente",
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
    figure.update_xaxes(tickformat=".1%")
    figure.update_yaxes(tickformat=".1%")
    st.plotly_chart(figure, use_container_width=True)

    weights = pd.DataFrame(
        {
            "Ticker": download.valid_tickers,
            "Peso máximo Sharpe": max_sharpe.weights,
            "Peso mínima volatilidad": min_volatility.weights,
            "Contribución al retorno": max_sharpe.weights * mean_returns.to_numpy(),
        }
    )
    st.subheader("Asignación propuesta por el modelo")
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

    pdf = create_pdf_report(
        download.valid_tickers,
        download.prices.index.min().date(),
        download.prices.index.max().date(),
        max_sharpe,
        risk,
        portfolio_value,
    )
    st.download_button(
        "Descargar reporte metodológico PDF", pdf, f"reporte_portafolio_{date.today()}.pdf", "application/pdf"
    )
    st.warning(
        "Los resultados dependen de datos históricos y supuestos estadísticos. No incorporan impuestos, "
        "comisiones, liquidez, situación personal ni riesgo cambiario."
    )
except PortfolioError as exc:
    st.error(str(exc))
except Exception:
    LOGGER.exception("Unexpected portfolio analysis error")
    st.error("Ocurrió un error inesperado. Revisa los parámetros o inténtalo nuevamente más tarde.")
