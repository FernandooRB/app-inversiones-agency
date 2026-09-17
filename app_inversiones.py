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
from allocation_policy import parse_asset_classes, parse_class_limits, policy_table
from backtesting import run_holdout_backtest
from covariance_calibration import select_diagonal_shrinkage
from currencies import convert_prices, currency_map, download_fx
from fixed_income import merge_cetes_index, read_banxico_cetes_csv
from fx_comparison import render_comparison
from implementation_costs import (
    ImplementationCostAssumptions,
    estimate_implementation_cost,
)
from instruments import analysis_inputs, display_catalog, load_catalog
from multi_cut import run_multi_cut_backtest
from portfolio_core import (
    PortfolioError,
    PortfolioMetrics,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    download_adjusted_prices,
    efficient_frontier,
    feasible_reference_weights,
    normalize_tickers,
    optimize_portfolio,
    parse_current_weights,
    portfolio_statistics,
    random_portfolios,
)
from price_quality import assess_price_quality
from price_upload import read_adjusted_price_csv
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    StressReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from sensitivity import analyze_allocation_sensitivity
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows, parse_asset_shocks
from walk_forward import run_walk_forward_backtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="Optimizador de Portafolios V2", page_icon="📊", layout="wide")
require_access()


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_prices(tickers: tuple[str, ...], start: date, end: date):
    return download_adjusted_prices(tickers, start, end)


def percent(value: float) -> str:
    return f"{value:.2%}"


def render_covariance_comparison(sample, diagonal, calibrated=None):
    scenarios = ("Máximo Sharpe", "Mínima volatilidad")
    variants = {"Muestral": sample, "Diagonal 50%": diagonal}
    if calibrated is not None:
        label = (
            f"Calibrada {calibrated.covariance_shrinkage:.0%}"
            if hasattr(calibrated, "covariance_shrinkage")
            else "Calibrada en cada revisión"
        )
        variants[label] = calibrated
    rows = pd.concat(
        {label: result.summary.loc[list(scenarios)] for label, result in variants.items()},
        names=["Covarianza", "Escenario"],
    )
    overview = rows[[
        "Retorno total neto", "Volatilidad anualizada", "Sharpe realizado",
        "Máxima caída",
        "Rotación inicial" if "Rotación inicial" in rows else "Rotación acumulada",
        "Costo inicial sobre capital" if "Costo inicial sobre capital" in rows
        else "Costo pagado sobre capital inicial",
    ]].copy()
    for column in overview:
        if column == "Sharpe realizado":
            overview[column] = overview[column].map(lambda value: f"{value:.2f}")
        else:
            overview[column] = overview[column].map(lambda value: f"{value:.2%}")
    st.dataframe(overview, use_container_width=True)
    curves = {
        f"{label} · {name}": result.equity_curves[name]
        for label, result in variants.items() for name in scenarios
    }
    reference_name = next(
        name for name in ("Pesos iguales", "Referencia simple factible")
        if name in sample.equity_curves
    )
    curves[reference_name] = sample.equity_curves[reference_name]
    st.line_chart(pd.DataFrame(curves), y_label="Capital relativo (1 = inicio)")
    st.caption(
        "Los estimadores usan idénticos retornos, fechas, restricciones y costos supuestos. "
        "El 50% es fijo; la opción calibrada usa sólo bloques anteriores a cada evaluación. "
        "Elegir después de ver las curvas puede sesgar la comparación."
    )


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
    with st.expander("Política por clase de activo"):
        use_class_policy = st.checkbox("Aplicar límites por clase")
        asset_classes_input = st.text_input(
            "Clases de los tickers, en el mismo orden",
            "renta_variable, renta_variable, renta_variable, renta_variable",
            help=(
                "Una etiqueta por ticker. Usa minúsculas y guion bajo. Si cargas CETES, "
                "la app añade deuda_gubernamental automáticamente."
            ),
        )
        class_limits_input = st.text_area(
            "Límites: clase, mínimo %, máximo %",
            "renta_variable,0,100",
            help="Incluye exactamente una línea por cada clase declarada.",
        )
        st.caption(
            "Son restricciones de un escenario de investigación. No asignan por sí solas "
            "un perfil de riesgo ni sustituyen la revisión humana."
        )
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
    with st.expander("Supuestos de costo de implementación"):
        st.caption(
            "Escenario manual por compra o venta. Los valores iniciales son cero; usa el tarifario "
            "vigente del contrato y no incluyas impuestos sobre ganancias."
        )
        implementation_commission_percent = st.number_input(
            "Comisión sobre cada operación (%)", min_value=0.0, max_value=5.0,
            value=0.0, step=0.01, format="%.3f",
        )
        implementation_vat_percent = st.number_input(
            "IVA aplicado a la comisión (%)", min_value=0.0, max_value=100.0,
            value=0.0, step=1.0,
        )
        implementation_market_bps = st.number_input(
            "Costo de mercado sobre nominal (pb)", min_value=0.0, max_value=500.0,
            value=0.0, step=1.0,
            help="Supuesto conjunto de medio spread, deslizamiento e impacto por cada compra o venta.",
        )
        implementation_minimum = st.number_input(
            f"Comisión mínima por orden ({base_currency})", min_value=0.0,
            max_value=100_000.0, value=0.0, step=1.0,
        )
        implementation_source_input = st.text_input(
            "Referencia del tarifario",
            help="Institución, producto, contrato o nombre del documento; máximo 120 caracteres.",
        )
        implementation_source_date = st.date_input(
            "Fecha de consulta del tarifario", value=date.today(), max_value=date.today(),
        )
    price_upload = st.file_uploader(
        "Precios ajustados CSV aportados por el equipo (opcional)",
        type=["csv"],
        help=(
            "Tabla con Fecha y una columna por ticker; UTF-8, YYYY-MM-DD, máximo 5 MB. "
            "No cargues posiciones ni datos personales. Confirma ajustes, moneda y derechos "
            "de uso con la fuente antes de interpretar o distribuir resultados."
        ),
    )
    price_source_input = st.text_input(
        "Fuente declarada de precios CSV",
        help="Nombre del proveedor o exportación; aparecerá en el PDF si cargas precios.",
    )
    st.download_button(
        "Descargar plantilla de precios CSV",
        b"Fecha,AAPL,MSFT\n",
        "plantilla_precios_ajustados.csv", "text/csv",
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

price_contents = price_upload.getvalue() if price_upload is not None else b""
price_fingerprint = sha256(price_contents).hexdigest() if price_contents else None
cetes_contents = cetes_upload.getvalue() if cetes_upload is not None else b""
cetes_fingerprint = sha256(cetes_contents).hexdigest() if cetes_contents else None
settings = (
    tickers_input,
    start_date,
    end_date,
    risk_free_rate,
    max_weight,
    use_class_policy,
    asset_classes_input,
    class_limits_input,
    confidence,
    horizon,
    portfolio_value,
    quote_input,
    base_currency,
    current_weights_input,
    implementation_commission_percent,
    implementation_vat_percent,
    implementation_market_bps,
    implementation_minimum,
    implementation_source_input,
    implementation_source_date,
    price_fingerprint,
    price_source_input,
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
    with st.spinner("Preparando y validando datos..."):
        if price_contents:
            price_source = price_source_input.strip()
            if (
                not price_source or len(price_source) > 120
                or any(ord(char) < 32 for char in price_source)
            ):
                raise PortfolioError("Declara una fuente de precios CSV de 1 a 120 caracteres.")
            download = read_adjusted_price_csv(
                price_contents, tickers, start_date, end_date
            )
        else:
            download = cached_prices(tickers, start_date, end_date)
        if download.rejected_tickers:
            raise PortfolioError("Corrige los tickers sin datos: " + ", ".join(download.rejected_tickers))
        price_quality_issues = assess_price_quality(download.prices)
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
        allocation_groups = ()
        allocation_policy_table = None
        if use_class_policy:
            declared_classes = parse_asset_classes(asset_classes_input, len(tickers))
            analysis_classes = declared_classes + (
                ("deuda_gubernamental",) if cetes_result is not None else ()
            )
            allocation_groups = parse_class_limits(class_limits_input, analysis_classes)
            allocation_policy_table = policy_table(allocation_groups)
        if price_contents:
            data_source = (
                f"CSV aportado por el equipo; fuente declarada: {price_source}; "
                f"ajustes no verificados; SHA-256 {price_fingerprint[:12]}"
            )
            if any(quotes[ticker] != base_currency for ticker in tickers):
                data_source += "; FX histórico Yahoo mediante yfinance"
        else:
            data_source = "Yahoo Finance mediante yfinance; precios ajustados y FX histórico"
        if cetes_result is not None:
            data_source += (
                f"; {cetes_name}: CSV aportado por el usuario y preparado desde precio/plazo, "
                f"SHA-256 {cetes_fingerprint[:12]}"
            )
        returns = calculate_returns(prices)
        mean_returns, covariance = annualized_moments(returns)
        max_sharpe = optimize_portfolio(
            mean_returns, covariance, risk_free_rate, "max_sharpe", max_weight,
            allocation_groups,
        )
        min_volatility = optimize_portfolio(
            mean_returns, covariance, risk_free_rate, "min_volatility", max_weight,
            allocation_groups,
        )
        frontier = efficient_frontier(
            mean_returns, covariance, max_weight, allocation_groups=allocation_groups
        )
        random_set = random_portfolios(
            mean_returns, covariance, risk_free_rate, max_weight=max_weight,
            allocation_groups=allocation_groups,
        )
        risk = calculate_risk_metrics(returns, max_sharpe.weights, confidence, horizon)
        alternatives = [
            PortfolioAlternative("Máximo Sharpe", max_sharpe, risk),
            PortfolioAlternative(
                "Mínima volatilidad", min_volatility,
                calculate_risk_metrics(returns, min_volatility.weights, confidence, horizon),
            ),
        ]
        equal_weights = feasible_reference_weights(
            len(analysis_tickers), max_weight, allocation_groups
        )
        equal_return, equal_volatility, equal_sharpe = portfolio_statistics(
            equal_weights, mean_returns, covariance, risk_free_rate
        )
        alternatives.append(PortfolioAlternative(
            "Referencia simple factible" if allocation_groups else "Pesos iguales",
            PortfolioMetrics(equal_weights, equal_return, equal_volatility, equal_sharpe),
            calculate_risk_metrics(returns, equal_weights, confidence, horizon),
        ))
        current_weights = None
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
        implementation_assumptions = ImplementationCostAssumptions(
            commission_bps=implementation_commission_percent * 100,
            market_cost_bps=implementation_market_bps,
            vat_rate=implementation_vat_percent / 100,
            minimum_commission=implementation_minimum,
        )
        has_implementation_cost = any((
            implementation_assumptions.commission_bps,
            implementation_assumptions.market_cost_bps,
            implementation_assumptions.vat_rate,
            implementation_assumptions.minimum_commission,
        ))
        implementation_source = implementation_source_input.strip()
        if has_implementation_cost and (
            not implementation_source or len(implementation_source) > 120
            or any(ord(char) < 32 for char in implementation_source)
        ):
            raise PortfolioError(
                "Declara la referencia del tarifario de costos en 1 a 120 caracteres."
            )
        if not has_implementation_cost:
            implementation_source = "Sin tarifario; supuestos de costo en cero"
        implementation_estimates = tuple(
            estimate_implementation_cost(
                analysis_tickers, alternative.metrics.weights, portfolio_value,
                implementation_assumptions, alternative_name=alternative.name,
                current_weights=current_weights,
            )
            for alternative in alternatives
        )

    if download.rejected_tickers:
        st.warning("Tickers excluidos por falta de datos: " + ", ".join(download.rejected_tickers))
    st.success(
        f"Análisis realizado con {len(returns):,} observaciones, del "
        f"{prices.index.min().date()} al {prices.index.max().date()}. Moneda: {base_currency}."
    )
    if allocation_policy_table is not None:
        with st.expander("Política aplicada por clase de activo", expanded=True):
            policy_view = allocation_policy_table.copy()
            policy_view["Mínimo"] = policy_view["Mínimo"].map(lambda value: f"{value:.1%}")
            policy_view["Máximo"] = policy_view["Máximo"].map(lambda value: f"{value:.1%}")
            st.dataframe(policy_view, hide_index=True, use_container_width=True)
            st.caption(
                "La clasificación fue declarada por el usuario y no se verificó contra una "
                "fuente externa. Máximo Sharpe, mínima volatilidad, frontera, nube y "
                "validaciones usan estos mismos límites."
            )
    if price_contents:
        st.info(
            f"Precios CSV aportados por el equipo · Fuente declarada: {price_source} · "
            f"SHA-256 {price_fingerprint[:12]}. "
            "Confirma con la fuente que son cierres ajustados comparables, su moneda, "
            "calendario y derechos de uso; la app no puede verificar esos extremos."
        )
    with st.expander("Revisión heurística de precios originales", expanded=bool(price_quality_issues)):
        st.caption(
            "Se revisan cierres en su moneda de cotización antes del FX: cambios de al menos "
            "30% entre sesiones y cinco sesiones consecutivas sin variación. "
            "Revisa eventos corporativos, calendario y fuente; una alerta no prueba un error "
            "y su ausencia no verifica los ajustes."
        )
        if price_quality_issues:
            st.warning(f"Se detectaron {len(price_quality_issues)} alerta(s) para revisión humana.")
            quality_rows = pd.DataFrame([
                {
                    "Activo": issue.ticker, "Tipo": issue.kind,
                    "Desde": issue.first_date, "Hasta": issue.last_date,
                    "Detalle": issue.detail,
                }
                for issue in price_quality_issues
            ])
            st.dataframe(quality_rows.head(100), hide_index=True, use_container_width=True)
            st.download_button(
                "Descargar todas las alertas CSV", quality_rows.to_csv(index=False).encode("utf-8-sig"),
                "revision_precios.csv", "text/csv",
            )
        else:
            st.info("No se detectaron alertas con estos umbrales.")
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

    with st.expander("Costo estimado para implementar cada asignación"):
        starting_point = "cartera actual" if current_weights is not None else "efectivo"
        st.caption(
            f"Punto de partida: {starting_point}. Se cobra cada compra y venta por separado. "
            "El costo se suma al nominal objetivo; no se resuelven órdenes autofinanciadas, lotes, "
            "retenciones ni impuestos sobre ganancias. Verifica el tarifario vigente del contrato."
        )
        st.caption(
            f"Referencia: {implementation_source} · Consulta: "
            f"{implementation_source_date.isoformat()}."
        )
        cost_summary = pd.DataFrame([
            {
                "Alternativa": item.alternative_name,
                "Compras": item.buy_notional,
                "Ventas": item.sell_notional,
                "Nominal negociado": item.traded_notional,
                "Comisión": item.commission,
                "IVA sobre comisión": item.vat,
                "Costo de mercado": item.market_cost,
                "Costo total": item.total_cost,
                "Costo / capital": item.total_cost / portfolio_value if portfolio_value else np.nan,
            }
            for item in implementation_estimates
        ])
        st.dataframe(
            cost_summary.style.format({
                "Compras": "{:,.2f}", "Ventas": "{:,.2f}",
                "Nominal negociado": "{:,.2f}", "Comisión": "{:,.2f}",
                "IVA sobre comisión": "{:,.2f}", "Costo de mercado": "{:,.2f}",
                "Costo total": "{:,.2f}", "Costo / capital": "{:.3%}",
            }), use_container_width=True, hide_index=True,
        )
        detail_parts = []
        for item in implementation_estimates:
            part = item.detail.copy()
            part.insert(0, "Alternativa", item.alternative_name)
            detail_parts.append(part)
        cost_detail = pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
        if not cost_detail.empty:
            selected_cost_alternative = st.selectbox(
                "Ver órdenes estimadas", [item.alternative_name for item in implementation_estimates]
            )
            st.dataframe(
                cost_detail[cost_detail["Alternativa"] == selected_cost_alternative],
                hide_index=True, use_container_width=True,
            )
            st.download_button(
                "Descargar detalle de costos CSV",
                cost_detail.to_csv(index=False).encode("utf-8-sig"),
                "costos_implementacion.csv", "text/csv",
            )

    with st.expander("Sensibilidad de pesos a la longitud de la muestra"):
        st.caption(
            "Reestima máximo Sharpe y mínima volatilidad con los últimos 60, 126 y 252 "
            "retornos disponibles y los compara con la muestra completa. Todas las ventanas "
            "terminan en la misma fecha; diferencias grandes indican sensibilidad histórica."
        )
        if st.checkbox("Comparar ventanas de estimación"):
            sensitivity = analyze_allocation_sensitivity(
                returns, risk_free_rate=risk_free_rate, max_weight=max_weight,
                allocation_groups=allocation_groups,
            )
            overview = sensitivity.summary.reset_index().copy()
            overview["Mayor peso"] = overview["Mayor peso"].map(
                lambda value: f"{value:.2%}"
            )
            overview["Cambio de pesos vs. muestra completa"] = overview[
                "Cambio de pesos vs. muestra completa"
            ].map(lambda value: f"{value:.2%}")
            st.dataframe(overview, hide_index=True, use_container_width=True)
            with st.expander("Pesos de cada activo por ventana"):
                st.dataframe(
                    sensitivity.weights.style.format({"Peso": "{:.2%}"}),
                    use_container_width=True,
                )
            st.download_button(
                "Descargar sensibilidad de pesos CSV",
                sensitivity.weights.to_csv().encode("utf-8-sig"),
                "sensibilidad_pesos.csv", "text/csv",
            )
            st.caption(
                "El cambio de pesos es la mitad de la suma de diferencias absolutas frente "
                "a la muestra completa. No es un costo ni una validación fuera de muestra; "
                "las ventanas comparten datos y la media histórica sigue sin ser un pronóstico."
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
                    allocation_groups=allocation_groups,
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
                if st.checkbox("Comparar estimadores de covarianza (corte único)"):
                    diagonal = run_holdout_backtest(
                        returns, training_fraction=training_percent / 100,
                        risk_free_rate=risk_free_rate, max_weight=max_weight,
                        current_weights=(
                            current_weights if current_weights_input.strip() else None
                        ),
                        trading_cost_bps=entry_cost_bps,
                        covariance_shrinkage=0.5,
                        allocation_groups=allocation_groups,
                    )
                    variants = {
                            "Muestral": backtest.allocations,
                            "Diagonal 50%": diagonal.allocations,
                    }
                    calibrated = None
                    if st.checkbox("Añadir intensidad calibrada (corte único)"):
                        if backtest.training_observations < 100:
                            st.info("Se necesitan 100 retornos iniciales para calibrar.")
                        else:
                            calibrated = run_holdout_backtest(
                                returns, training_fraction=training_percent / 100,
                                risk_free_rate=risk_free_rate, max_weight=max_weight,
                                current_weights=(
                                    current_weights if current_weights_input.strip() else None
                                ),
                                trading_cost_bps=entry_cost_bps,
                                covariance_shrinkage="cv",
                                allocation_groups=allocation_groups,
                            )
                            calibration = select_diagonal_shrinkage(
                                returns.iloc[:backtest.training_observations]
                            )
                            st.write(
                                f"**Contracción elegida con bloques iniciales:** "
                                f"{calibrated.covariance_shrinkage:.0%}."
                            )
                            with st.expander("Bloques y errores de calibración"):
                                st.dataframe(
                                    calibration.fold_scores, hide_index=True,
                                    use_container_width=True,
                                )
                                st.caption(
                                    "Menor error cuadrático de covarianza = mejor "
                                    "en los bloques internos."
                                )
                            variants[f"Calibrada {calibrated.covariance_shrinkage:.0%}"] = (
                                calibrated.allocations
                            )
                    render_covariance_comparison(backtest, diagonal, calibrated)
                    with st.expander("Pesos estimados por cada estimador"):
                        st.dataframe(pd.concat(
                            variants, names=["Covarianza", "Activo"]
                        ).style.format("{:.2%}"))
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

    with st.expander("Sensibilidad a cuatro fechas de corte"):
        st.caption(
            "Compara cortes iniciales fijos de 50%, 60%, 70% y 80%. Cada cartera se estima "
            "antes de su evaluación y se mantiene después. La diferencia frente a la referencia "
            "simple se calcula sólo dentro del mismo periodo."
        )
        if st.checkbox("Evaluar cuatro cortes predefinidos"):
            if len(returns) < 120:
                st.info("Se necesitan 120 retornos para evaluar los cuatro cortes.")
            elif removed:
                st.warning(
                    "Hay fechas omitidas por falta de FX; resuelve los huecos antes de "
                    "comparar periodos con retornos supuestamente diarios."
                )
            else:
                estimator = st.selectbox(
                    "Covarianza para los cuatro cortes",
                    ("Muestral", "Diagonal 50%", "Calibrada con bloques previos"),
                )
                multi_cost = st.number_input(
                    "Costo inicial por rotación en los cuatro cortes (puntos base)",
                    min_value=0.0, max_value=500.0, value=0.0, step=5.0,
                )
                if estimator == "Calibrada con bloques previos" and len(returns) < 200:
                    st.info("La opción calibrada requiere 200 retornos para los cuatro cortes.")
                else:
                    method = {
                        "Muestral": 0.0, "Diagonal 50%": 0.5,
                        "Calibrada con bloques previos": "cv",
                    }[estimator]
                    multi = run_multi_cut_backtest(
                        returns, risk_free_rate=risk_free_rate, max_weight=max_weight,
                        current_weights=(
                            current_weights if current_weights_input.strip() else None
                        ),
                        trading_cost_bps=multi_cost,
                        covariance_shrinkage=method,
                        allocation_groups=allocation_groups,
                    )
                    reference_difference = (
                        "Diferencia total neta vs referencia simple"
                        if allocation_groups else "Diferencia total neta vs pesos iguales"
                    )
                    overview = multi.summary.reset_index()[[
                        "Corte inicial", "Escenario", "Estimación hasta",
                        "Retornos de estimación", "Evaluación desde", "Evaluación hasta",
                        "Retornos de evaluación", "Contracción de covarianza",
                        "Retorno total neto", "Retorno anualizado neto",
                        reference_difference,
                        "Volatilidad anualizada", "Sharpe realizado", "Máxima caída",
                        "Rotación inicial", "Costo inicial sobre capital",
                    ]].copy()
                    for column in (
                        "Contracción de covarianza", "Retorno total neto",
                        "Retorno anualizado neto", reference_difference,
                        "Volatilidad anualizada", "Máxima caída", "Rotación inicial",
                        "Costo inicial sobre capital",
                    ):
                        overview[column] = overview[column].map(lambda value: f"{value:.2%}")
                    overview["Sharpe realizado"] = overview["Sharpe realizado"].map(
                        lambda value: f"{value:.2f}"
                    )
                    st.dataframe(overview, hide_index=True, use_container_width=True)
                    selected_cut = st.selectbox(
                        "Corte para ver la trayectoria", tuple(multi.results)
                    )
                    st.line_chart(
                        multi.results[selected_cut].equity_curves,
                        y_label="Capital relativo (1 = inicio)",
                    )
                    st.download_button(
                        "Descargar resumen de cuatro cortes CSV",
                        multi.summary.to_csv().encode("utf-8-sig"),
                        "validacion_cuatro_cortes.csv", "text/csv",
                    )
                    st.download_button(
                        "Descargar pesos de cuatro cortes CSV",
                        multi.allocations.to_csv().encode("utf-8-sig"),
                        "pesos_cuatro_cortes.csv", "text/csv",
                    )
                    st.caption(
                        "Las evaluaciones se solapan y tienen distinta duración; no se suman "
                        "sus retornos ni se interpretan como cuatro pruebas independientes. "
                        "El costo supuesto se aplica sólo al cambio inicial desde la cartera "
                        "actual; sin cartera actual se supone posición ya asignada."
                    )

    with st.expander("Validación con revisiones sucesivas"):
        st.caption(
            "La primera parte estima los pesos iniciales. Después, cada revisión de 3, 6 o 12 "
            "meses utiliza sólo retornos observados hasta la sesión anterior. La referencia "
            "simple se rebalancea en las mismas fechas; la cartera actual opcional se mantiene."
        )
        if st.checkbox("Evaluar revisiones sucesivas"):
            if removed:
                st.warning(
                    "Hay fechas omitidas por falta de FX; resuelve esos huecos antes de "
                    "usar retornos supuestamente diarios en la validación."
                )
            else:
                cadence = st.selectbox("Revisión cada (meses)", (3, 6, 12))
                train_percent = st.slider(
                    "Muestra inicial para estimación (%)", 50, 90, 70, 5
                )
                cost_bps = st.number_input(
                    "Costo por rotación en cada revisión (puntos base)",
                    min_value=0.0, max_value=500.0, value=0.0, step=5.0,
                )
                walk = run_walk_forward_backtest(
                    returns, training_fraction=train_percent / 100,
                    cadence_months=cadence, risk_free_rate=risk_free_rate,
                    max_weight=max_weight,
                    current_weights=(
                        current_weights if current_weights_input.strip() else None
                    ),
                    trading_cost_bps=cost_bps,
                    allocation_groups=allocation_groups,
                )
                st.write(
                    f"**Estimación inicial hasta:** {walk.training_end.date()}. "
                    f"**Evaluación:** {walk.evaluation_start.date()} a "
                    f"{walk.evaluation_end.date()}."
                )
                display = walk.summary.copy()
                for column in (
                    "Retorno total neto", "Retorno anualizado neto",
                    "Volatilidad anualizada", "Máxima caída", "Rotación acumulada",
                    "Costo pagado sobre capital inicial",
                ):
                    display[column] = display[column].map(lambda value: f"{value:.2%}")
                display["Sharpe realizado"] = display["Sharpe realizado"].map(
                    lambda value: f"{value:.2f}"
                )
                st.dataframe(display, use_container_width=True)
                st.line_chart(walk.equity_curves, y_label="Capital relativo (1 = inicio)")
                if st.checkbox("Comparar estimadores de covarianza (revisiones)"):
                    diagonal_walk = run_walk_forward_backtest(
                        returns, training_fraction=train_percent / 100,
                        cadence_months=cadence, risk_free_rate=risk_free_rate,
                        max_weight=max_weight,
                        current_weights=(
                            current_weights if current_weights_input.strip() else None
                        ),
                        trading_cost_bps=cost_bps,
                        covariance_shrinkage=0.5,
                        allocation_groups=allocation_groups,
                    )
                    calibrated_walk = None
                    if st.checkbox("Añadir intensidad calibrada (revisiones)"):
                        if int(len(returns) * train_percent / 100) < 100:
                            st.info("Se necesitan 100 retornos iniciales para calibrar.")
                        else:
                            calibrated_walk = run_walk_forward_backtest(
                                returns, training_fraction=train_percent / 100,
                                cadence_months=cadence, risk_free_rate=risk_free_rate,
                                max_weight=max_weight,
                                current_weights=(
                                    current_weights if current_weights_input.strip() else None
                                ),
                                trading_cost_bps=cost_bps,
                                covariance_shrinkage="cv",
                                allocation_groups=allocation_groups,
                            )
                            st.download_button(
                                "Descargar revisiones con intensidad calibrada CSV",
                                calibrated_walk.allocation_history.to_csv().encode("utf-8-sig"),
                                "revisiones_covarianza_calibrada.csv", "text/csv",
                            )
                    render_covariance_comparison(walk, diagonal_walk, calibrated_walk)
                    st.download_button(
                        "Descargar revisiones con covarianza diagonal CSV",
                        diagonal_walk.allocation_history.to_csv().encode("utf-8-sig"),
                        "revisiones_covarianza_diagonal.csv", "text/csv",
                    )
                with st.expander("Fechas, ventanas y pesos de cada revisión"):
                    st.dataframe(walk.allocation_history, use_container_width=True)
                st.download_button(
                    "Descargar historial de revisiones CSV",
                    walk.allocation_history.to_csv().encode("utf-8-sig"),
                    "revisiones_sucesivas.csv", "text/csv",
                )
                st.caption(
                    "El costo supuesto se descuenta del capital al iniciar y en cada revisión; "
                    "sin cartera actual se supone una posición inicial ya asignada. "
                    "No se incluyen impuestos, comisiones fijas, spreads, deslizamiento ni "
                    "restricciones de ejecución. La evaluación es hipotética y depende de "
                    "la muestra y de los parámetros elegidos."
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
        price_quality_issues=price_quality_issues,
        implementation_costs=(implementation_estimates[0],),
        implementation_cost_assumptions=implementation_assumptions,
        implementation_cost_source=implementation_source,
        implementation_cost_source_date=implementation_source_date,
        allocation_policy=allocation_policy_table,
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
        price_quality_issues=price_quality_issues,
        implementation_costs=implementation_estimates,
        implementation_cost_assumptions=implementation_assumptions,
        implementation_cost_source=implementation_source,
        implementation_cost_source_date=implementation_source_date,
        simulation=simulation_report,
        stress=stress_report,
        allocation_policy=allocation_policy_table,
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
        "Los resultados dependen de datos históricos y supuestos estadísticos. Los costos "
        "configurables de simulación, rebalanceo e implementación son hipotéticos; las métricas "
        "optimizadas no descuentan esos costos, impuestos, liquidez ni situación personal. "
        "La conversión cambiaria no constituye una cobertura."
    )
except PortfolioError as exc:
    st.error(str(exc))
except Exception:
    LOGGER.exception("Unexpected portfolio analysis error")
    st.error("Ocurrió un error inesperado. Revisa los parámetros o inténtalo nuevamente más tarde.")
