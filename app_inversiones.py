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
from benchmarking import analyze_benchmark
from black_litterman import black_litterman_posterior, parse_absolute_views
from broker_tariffs import read_broker_tariff_csv
from covariance_calibration import select_diagonal_shrinkage
from currencies import convert_prices, currency_map, download_fx
from data_rights import read_data_rights_csv
from fixed_income import (
    merge_bond_index,
    merge_cetes_index,
    read_banxico_cetes_csv,
    read_bond_total_return_csv,
)
from funds import merge_fund_index, read_fund_total_return_csv
from fx_comparison import render_comparison
from holdings import read_current_holdings_csv
from implementation_costs import (
    ImplementationCostAssumptions,
    estimate_implementation_cost,
)
from instruments import analysis_inputs, display_catalog, load_catalog
from liquidity import merge_liquidity_index, read_liquidity_rate_csv
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
from risk_attribution import attribute_volatility
from sensitivity import analyze_allocation_sensitivity
from simulation import simulate_portfolio_paths
from stress import (
    deterministic_shock,
    historical_worst_windows,
    parse_asset_shocks,
    parse_class_shocks,
    validate_scenario_metadata,
)
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
        "Bonos M puede añadirse por emisión mediante precio limpio, devengado y cupones; "
        "un vehículo de liquidez puede añadirse con tasas y convención declaradas; los fondos "
        "mexicanos requieren una serie exacta con valor de acción y distribuciones."
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
    with st.expander("Benchmark histórico"):
        benchmark_ticker_input = st.text_input(
            "Ticker del benchmark (opcional)",
            help=(
                "Índice o vehículo de referencia ajeno a la cartera. Verifica que represente "
                "el mercado relevante y que sus datos puedan usarse para el propósito previsto."
            ),
        )
        benchmark_name_input = st.text_input("Nombre del benchmark", "Referencia de mercado")
        benchmark_quote = st.selectbox(
            "Moneda de cotización del benchmark",
            ["MXN", "USD", "EUR", "GBP", "CAD", "JPY", "CHF"],
        )
        st.caption(
            "Se descarga como serie separada, se convierte a la moneda base y se compara "
            "únicamente en fechas comunes. No se incorpora como activo invertible."
        )
    with st.expander("Política por clase de activo"):
        use_class_policy = st.checkbox("Aplicar límites por clase")
        asset_classes_input = st.text_input(
            "Clases de los tickers, en el mismo orden",
            "renta_variable, renta_variable, renta_variable, renta_variable",
            help=(
                "Una etiqueta por ticker. Usa minúsculas y guion bajo. La app añade "
                "deuda_gubernamental para CETES y Bono M, efectivo para liquidez y fondo para "
                "una serie de fondo cargada."
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
            "Un porcentaje por activo, en el mismo orden; CETES, Bono M, liquidez y fondo van al final, "
            "en ese orden, cuando se cargan. "
            "Deben sumar 100. "
            "No se guarda en una base de datos."
        ),
    )
    holdings_upload = st.file_uploader(
        "Cartera actual valuada en MXN CSV (opcional)",
        type=["csv"],
        help=(
            "FechaCorte, Instrumento y ValorMXN; incluye exactamente todos los activos del análisis, "
            "también los de valor cero. Máximo 2 MB. No incluyas nombres, cuentas ni identificadores "
            "del cliente. Esta opción sustituye los pesos y el valor manuales."
        ),
    )
    holdings_source_input = st.text_input(
        "Fuente declarada de la cartera actual",
        help="Estado de cuenta o exportación utilizada; máximo 120 caracteres.",
    )
    st.download_button(
        "Descargar plantilla de cartera actual CSV",
        b"FechaCorte,Instrumento,ValorMXN\n2026-01-15,AAPL,60000\n2026-01-15,MSFT,40000\n",
        "plantilla_cartera_actual_mxn.csv", "text/csv",
    )
    with st.expander("Escenario Black-Litterman"):
        use_black_litterman = st.checkbox("Añadir alternativa Black-Litterman")
        black_litterman_equilibrium_input = st.text_input(
            "Pesos de equilibrio en % (opcional)",
            help=(
                "Un peso por activo en el mismo orden. Si se omite, se usa la cartera actual "
                "cuando exista; en otro caso, la referencia simple factible."
            ),
        )
        black_litterman_risk_aversion = st.number_input(
            "Aversión al riesgo del equilibrio", min_value=0.1, max_value=100.0,
            value=2.5, step=0.1,
        )
        black_litterman_tau = st.number_input(
            "Tau (incertidumbre del equilibrio)", min_value=0.001, max_value=1.0,
            value=0.05, step=0.01, format="%.3f",
        )
        black_litterman_views_input = st.text_area(
            "Opiniones: activo, rendimiento anual %, confianza %",
            help=(
                "Una opinión absoluta por línea. Ejemplo: AAPL,12,60. "
                "La confianza debe estar entre 1% y 99%."
            ),
        )
        st.caption(
            "Los pesos, parámetros y opiniones son supuestos declarados para investigación. "
            "No se infieren del perfil del cliente ni constituyen pronósticos verificados."
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
        implementation_annual_fixed = st.number_input(
            f"Costo fijo anual total ({base_currency})", min_value=0.0,
            max_value=1_000_000.0, value=0.0, step=100.0,
            help="Importe anual total, después de impuestos aplicables, por plataforma, datos o cuenta.",
        )
        implementation_annual_management_percent = st.number_input(
            "Administración anual total sobre saldo (%)", min_value=0.0, max_value=20.0,
            value=0.0, step=0.01, format="%.3f",
            help="Tasa anual total, después de impuestos aplicables, calculada sobre el capital.",
        )
        implementation_source_input = st.text_input(
            "Referencia del tarifario",
            help="Institución, producto, contrato o nombre del documento; máximo 400 caracteres.",
        )
        implementation_source_date = st.date_input(
            "Fecha de consulta del tarifario", value=date.today(), max_value=date.today(),
        )
        tariff_upload = st.file_uploader(
            "Perfil contractual de costos CSV (opcional)", type=["csv"],
            help=(
                "Un perfil, máximo 100 KB. Sustituye todos los supuestos manuales de este bloque. "
                "Usa los términos del contrato o tarifario aplicable al producto y mercado concretos."
            ),
        )
        st.download_button(
            "Descargar plantilla de perfil de costos CSV",
            (
                b"Intermediario,Producto,Mercado,FechaConsulta,ComisionOperacionPct,"
                b"IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,"
                b"CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente\n"
                b"Casa de Bolsa,Cuenta de ejemplo,Capitales MX y SIC,2026-01-15,0.25,16,0,"
                b"8,0,0,Contrato o tarifario de ejemplo\n"
            ),
            "plantilla_perfil_costos.csv", "text/csv",
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
    price_rights_upload = st.file_uploader(
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)",
        type=["csv"],
        help=(
            "Un registro, máximo 100 KB. Debe confirmar el producto, alcance permitido, "
            "convención de ajustes, hora de corte y referencia contractual vigente."
        ),
    )
    st.download_button(
        "Descargar plantilla de manifiesto de derechos",
        (
            b"Fuente,Producto,Mercados,FechaRevision,VigenciaHasta,EstadoDerechos,"
            b"AlcanceAutorizado,AjusteCorporativo,HoraCorteZona,ReferenciaContractual\n"
            b"Proveedor,Precios de cierre,BMV y SIC,2026-09-01,2027-09-01,CONFIRMADO,"
            b"INVESTIGACION_INTERNA,AJUSTADO,Cierre oficial America/Mexico_City,"
            b"Contrato o permiso verificable\n"
        ),
        "plantilla_derechos_datos.csv", "text/csv",
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
    bond_upload = st.file_uploader(
        "Serie de Bono M por emisión (opcional)",
        type=["csv"],
        help=(
            "Una sola emisión con Fecha, Emision, Vencimiento, PrecioLimpio, "
            "InteresDevengado y Cupon por 100 de nominal. Máximo 5 MB; sólo MXN."
        ),
    )
    bond_name_input = st.text_input(
        "Nombre de la serie Bono M", "BONOM", help="Etiqueta para tablas y reportes."
    )
    st.download_button(
        "Descargar plantilla Bono M CSV",
        (
            b"Fecha,Emision,Vencimiento,PrecioLimpio,InteresDevengado,Cupon\n"
            b"2026-01-02,M 310529,2031-05-29,98.0000,2.8000,0\n"
            b"2026-01-05,M 310529,2031-05-29,98.0500,2.8500,0\n"
            b"2026-01-06,M 310529,2031-05-29,98.1000,2.9000,0\n"
        ),
        "plantilla_bono_m.csv",
        "text/csv",
    )
    liquidity_upload = st.file_uploader(
        "Tasas de vehículo de liquidez MXN (opcional)",
        type=["csv"],
        help=(
            "Un solo vehículo con Fecha, Vehiculo, TasaAnualPct, Convencion y Tratamiento. "
            "Convenciones: nominal_360 o efectiva_365; tratamiento: BRUTA o NETA. Máximo 5 MB."
        ),
    )
    liquidity_name_input = st.text_input(
        "Nombre de la serie de liquidez", "LIQUIDEZ", help="Etiqueta para tablas y reportes."
    )
    liquidity_source_input = st.text_input(
        "Fuente declarada de la tasa de liquidez",
        help="Contrato, estado de cuenta o proveedor; aparecerá en el PDF.",
    )
    st.download_button(
        "Descargar plantilla de liquidez CSV",
        (
            b"Fecha,Vehiculo,TasaAnualPct,Convencion,Tratamiento\n"
            b"2026-01-02,Cuenta remunerada de ejemplo,8.50,nominal_360,NETA\n"
            b"2026-01-05,Cuenta remunerada de ejemplo,8.50,nominal_360,NETA\n"
            b"2026-01-06,Cuenta remunerada de ejemplo,8.45,nominal_360,NETA\n"
        ),
        "plantilla_liquidez_mxn.csv",
        "text/csv",
    )
    fund_upload = st.file_uploader(
        "Serie de fondo de inversión MXN (opcional)",
        type=["csv"],
        help=(
            "Un solo fondo y serie con Fecha, Fondo, Serie, Moneda, ValorAccion y Distribucion "
            "por acción. Máximo 5 MB; sólo MXN."
        ),
    )
    fund_name_input = st.text_input(
        "Nombre de la serie del fondo", "FONDOMXN", help="Etiqueta para tablas y reportes."
    )
    fund_source_input = st.text_input(
        "Fuente declarada del valor del fondo",
        help="Operadora, distribuidora o estado de cuenta; aparecerá en el PDF.",
    )
    st.download_button(
        "Descargar plantilla de fondo CSV",
        (
            b"Fecha,Fondo,Serie,Moneda,ValorAccion,Distribucion\n"
            b"2026-01-02,Fondo de ejemplo,A1,MXN,10.0000,0\n"
            b"2026-01-05,Fondo de ejemplo,A1,MXN,10.0100,0\n"
            b"2026-01-06,Fondo de ejemplo,A1,MXN,10.0150,0\n"
        ),
        "plantilla_fondo_mxn.csv",
        "text/csv",
    )
    analyze = st.button("Analizar portafolio", type="primary", use_container_width=True)

price_contents = price_upload.getvalue() if price_upload is not None else b""
price_fingerprint = sha256(price_contents).hexdigest() if price_contents else None
price_rights_contents = (
    price_rights_upload.getvalue() if price_rights_upload is not None else b""
)
price_rights_fingerprint = (
    sha256(price_rights_contents).hexdigest() if price_rights_contents else None
)
holdings_contents = holdings_upload.getvalue() if holdings_upload is not None else b""
holdings_fingerprint = sha256(holdings_contents).hexdigest() if holdings_contents else None
cetes_contents = cetes_upload.getvalue() if cetes_upload is not None else b""
cetes_fingerprint = sha256(cetes_contents).hexdigest() if cetes_contents else None
bond_contents = bond_upload.getvalue() if bond_upload is not None else b""
bond_fingerprint = sha256(bond_contents).hexdigest() if bond_contents else None
liquidity_contents = liquidity_upload.getvalue() if liquidity_upload is not None else b""
liquidity_fingerprint = sha256(liquidity_contents).hexdigest() if liquidity_contents else None
fund_contents = fund_upload.getvalue() if fund_upload is not None else b""
fund_fingerprint = sha256(fund_contents).hexdigest() if fund_contents else None
tariff_contents = tariff_upload.getvalue() if tariff_upload is not None else b""
tariff_fingerprint = sha256(tariff_contents).hexdigest() if tariff_contents else None
settings = (
    tickers_input,
    start_date,
    end_date,
    risk_free_rate,
    max_weight,
    benchmark_ticker_input,
    benchmark_name_input,
    benchmark_quote,
    use_class_policy,
    asset_classes_input,
    class_limits_input,
    confidence,
    horizon,
    portfolio_value,
    quote_input,
    base_currency,
    current_weights_input,
    holdings_fingerprint,
    holdings_source_input,
    use_black_litterman,
    black_litterman_equilibrium_input,
    black_litterman_risk_aversion,
    black_litterman_tau,
    black_litterman_views_input,
    implementation_commission_percent,
    implementation_vat_percent,
    implementation_market_bps,
    implementation_minimum,
    implementation_annual_fixed,
    implementation_annual_management_percent,
    implementation_source_input,
    implementation_source_date,
    tariff_fingerprint,
    price_fingerprint,
    price_rights_fingerprint,
    cetes_fingerprint,
    cetes_name_input,
    bond_fingerprint,
    bond_name_input,
    liquidity_fingerprint,
    liquidity_name_input,
    liquidity_source_input,
    fund_fingerprint,
    fund_name_input,
    fund_source_input,
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
    asset_count = (
        len(tickers) + bool(cetes_contents) + bool(bond_contents) + bool(liquidity_contents)
        + bool(fund_contents)
    )
    if holdings_contents and current_weights_input.strip():
        raise PortfolioError(
            "Usa sólo una entrada para la cartera actual: el CSV valuado o los pesos manuales."
        )
    if asset_count * max_weight < 1:
        raise PortfolioError(
            f"Con {asset_count} activos, el peso máximo debe ser al menos {1 / asset_count:.1%}."
        )
    cetes_result = None
    bond_result = None
    liquidity_result = None
    fund_result = None
    price_rights = None
    with st.spinner("Preparando y validando datos..."):
        if price_contents:
            if not price_rights_contents:
                raise PortfolioError(
                    "Carga el manifiesto de derechos correspondiente al archivo de precios."
                )
            price_rights = read_data_rights_csv(price_rights_contents)
            download = read_adjusted_price_csv(
                price_contents, tickers, start_date, end_date
            )
        else:
            if price_rights_contents:
                raise PortfolioError(
                    "El manifiesto de derechos sólo puede usarse junto con un CSV de precios."
                )
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
        if bond_contents:
            if base_currency != "MXN":
                raise PortfolioError("La serie del Bono M sólo puede añadirse con moneda base MXN.")
            bond_name = normalize_tickers([bond_name_input])[0]
            if bond_name in prices.columns:
                raise PortfolioError("El nombre de la serie Bono M coincide con otro activo.")
            bond_result = read_bond_total_return_csv(bond_contents, name=bond_name)
            prepared_bond_index = bond_result.index.loc[
                pd.Timestamp(start_date):pd.Timestamp(end_date)
            ]
            prices = merge_bond_index(prices, prepared_bond_index)
        if liquidity_contents:
            if base_currency != "MXN":
                raise PortfolioError("La serie de liquidez sólo puede añadirse con moneda base MXN.")
            liquidity_name = normalize_tickers([liquidity_name_input])[0]
            if liquidity_name in prices.columns:
                raise PortfolioError("El nombre de la serie de liquidez coincide con otro activo.")
            liquidity_source = liquidity_source_input.strip()
            if (
                not liquidity_source
                or len(liquidity_source) > 120
                or any(ord(char) < 32 for char in liquidity_source)
            ):
                raise PortfolioError("Declara una fuente de tasa de liquidez de 1 a 120 caracteres.")
            liquidity_result = read_liquidity_rate_csv(
                liquidity_contents, name=liquidity_name
            )
            prepared_liquidity_index = liquidity_result.index.loc[
                pd.Timestamp(start_date):pd.Timestamp(end_date)
            ]
            prices = merge_liquidity_index(prices, prepared_liquidity_index)
        if fund_contents:
            if base_currency != "MXN":
                raise PortfolioError("La serie del fondo sólo puede añadirse con moneda base MXN.")
            fund_name = normalize_tickers([fund_name_input])[0]
            if fund_name in prices.columns:
                raise PortfolioError("El nombre de la serie del fondo coincide con otro activo.")
            fund_source = fund_source_input.strip()
            if (
                not fund_source
                or len(fund_source) > 120
                or any(ord(char) < 32 for char in fund_source)
            ):
                raise PortfolioError("Declara una fuente del fondo de 1 a 120 caracteres.")
            fund_result = read_fund_total_return_csv(fund_contents, name=fund_name)
            prepared_fund_index = fund_result.index.loc[
                pd.Timestamp(start_date):pd.Timestamp(end_date)
            ]
            prices = merge_fund_index(prices, prepared_fund_index)
        analysis_tickers = tuple(str(column) for column in prices.columns)
        holdings_result = None
        current_weights = None
        holdings_source = None
        if holdings_contents:
            if base_currency != "MXN":
                raise PortfolioError("La cartera valuada en MXN requiere moneda base MXN.")
            holdings_source = holdings_source_input.strip()
            if (
                not holdings_source
                or len(holdings_source) > 120
                or any(ord(char) < 32 for char in holdings_source)
            ):
                raise PortfolioError(
                    "Declara una fuente de la cartera actual de 1 a 120 caracteres."
                )
            holdings_result = read_current_holdings_csv(
                holdings_contents, analysis_tickers
            )
            current_weights = holdings_result.weights.to_numpy(dtype=float)
            portfolio_value = holdings_result.total_value
        elif current_weights_input.strip():
            current_weights = parse_current_weights(
                current_weights_input, len(analysis_tickers)
            )
        analysis_quotes = (
            quotes
            | ({cetes_name: "MXN"} if cetes_result is not None else {})
            | ({bond_name: "MXN"} if bond_result is not None else {})
            | ({liquidity_name: "MXN"} if liquidity_result is not None else {})
            | ({fund_name: "MXN"} if fund_result is not None else {})
        )
        allocation_groups = ()
        allocation_policy_table = None
        if use_class_policy:
            declared_classes = parse_asset_classes(asset_classes_input, len(tickers))
            analysis_classes = declared_classes + ("deuda_gubernamental",) * sum((
                cetes_result is not None, bond_result is not None,
            )) + (("efectivo",) if liquidity_result is not None else ())
            analysis_classes += (("fondo",) if fund_result is not None else ())
            allocation_groups = parse_class_limits(class_limits_input, analysis_classes)
            allocation_policy_table = policy_table(allocation_groups)
        if price_contents:
            data_source = (
                f"CSV aportado por el equipo; {price_rights.source} / {price_rights.product}; "
                f"mercados {price_rights.markets}; derechos revisados "
                f"{price_rights.reviewed_on.isoformat()}; alcance "
                f"{price_rights.authorized_scope}; cierre {price_rights.cutoff_convention}; "
                f"referencia {price_rights.contractual_reference}; "
                f"precios declarados ajustados; SHA-256 datos {price_fingerprint[:12]} y "
                f"manifiesto {price_rights.fingerprint[:12]}"
            )
            if not price_rights.allows_client_deliverables:
                data_source += "; USO RESTRINGIDO A INVESTIGACIÓN INTERNA"
            if any(quotes[ticker] != base_currency for ticker in tickers):
                data_source += "; FX histórico Yahoo mediante yfinance"
        else:
            data_source = "Yahoo Finance mediante yfinance; precios ajustados y FX histórico"
        if cetes_result is not None:
            data_source += (
                f"; {cetes_name}: CSV aportado por el usuario y preparado desde precio/plazo, "
                f"SHA-256 {cetes_fingerprint[:12]}"
            )
        if bond_result is not None:
            data_source += (
                f"; {bond_name}: CSV aportado por el usuario, emisión "
                f"{bond_result.issue_id}, vencimiento {bond_result.maturity_date.date()}, "
                "retorno total desde precio limpio, interés devengado y cupones, "
                f"SHA-256 {bond_fingerprint[:12]}"
            )
        if liquidity_result is not None:
            data_source += (
                f"; {liquidity_name}: CSV aportado por el usuario para "
                f"{liquidity_result.vehicle}; fuente declarada: {liquidity_source}; "
                f"tasa {liquidity_result.treatment.lower()} con convención "
                f"{liquidity_result.convention}; SHA-256 {liquidity_fingerprint[:12]}"
            )
        if fund_result is not None:
            data_source += (
                f"; {fund_name}: CSV aportado por el usuario para {fund_result.fund_id}, "
                f"serie {fund_result.series_id}; fuente declarada: {fund_source}; retorno total "
                f"desde valor de acción y distribuciones; SHA-256 {fund_fingerprint[:12]}"
            )
        if holdings_result is not None:
            data_source += (
                f"; cartera actual al {holdings_result.as_of.date()} desde {holdings_source}; "
                f"SHA-256 {holdings_fingerprint[:12]}"
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
        if current_weights is not None:
            current_return, current_volatility, current_sharpe = portfolio_statistics(
                current_weights, mean_returns, covariance, risk_free_rate
            )
            alternatives.append(PortfolioAlternative(
                "Cartera actual",
                PortfolioMetrics(current_weights, current_return, current_volatility, current_sharpe),
                calculate_risk_metrics(returns, current_weights, confidence, horizon),
            ))
        black_litterman_result = None
        black_litterman_source = None
        if use_black_litterman:
            if black_litterman_equilibrium_input.strip():
                equilibrium_weights = parse_current_weights(
                    black_litterman_equilibrium_input, len(analysis_tickers)
                )
                black_litterman_source = "pesos de equilibrio ingresados por el usuario"
            elif current_weights is not None:
                equilibrium_weights = current_weights
                black_litterman_source = "cartera actual ingresada"
            else:
                equilibrium_weights = equal_weights
                black_litterman_source = "referencia simple factible"
            black_litterman_result = black_litterman_posterior(
                covariance,
                equilibrium_weights,
                risk_free_rate,
                risk_aversion=black_litterman_risk_aversion,
                tau=black_litterman_tau,
                views=parse_absolute_views(
                    black_litterman_views_input, analysis_tickers
                ),
            )
            black_litterman_metrics = optimize_portfolio(
                black_litterman_result.posterior_returns,
                covariance,
                risk_free_rate,
                "max_sharpe",
                max_weight,
                allocation_groups,
            )
            alternatives.append(PortfolioAlternative(
                "Black-Litterman",
                black_litterman_metrics,
                calculate_risk_metrics(
                    returns, black_litterman_metrics.weights, confidence, horizon
                ),
            ))
        risk_attributions = tuple(
            attribute_volatility(
                covariance,
                alternative.metrics.weights,
                alternative_name=alternative.name,
            )
            for alternative in alternatives
        )
        tariff_profile = None
        manual_cost_values = (
            implementation_commission_percent, implementation_vat_percent,
            implementation_market_bps, implementation_minimum,
            implementation_annual_fixed, implementation_annual_management_percent,
        )
        if tariff_contents:
            if base_currency != "MXN":
                raise PortfolioError("El perfil contractual en MXN requiere moneda base MXN.")
            if any(manual_cost_values) or implementation_source_input.strip():
                raise PortfolioError(
                    "Usa sólo una entrada de costos: el perfil contractual CSV o los supuestos manuales."
                )
            tariff_profile = read_broker_tariff_csv(tariff_contents)
            implementation_assumptions = tariff_profile.assumptions
            implementation_source = (
                f"{tariff_profile.source}; CSV SHA-256 {tariff_fingerprint[:12]}"
            )
            implementation_source_date = tariff_profile.consulted_on
        else:
            implementation_assumptions = ImplementationCostAssumptions(
                commission_bps=implementation_commission_percent * 100,
                market_cost_bps=implementation_market_bps,
                vat_rate=implementation_vat_percent / 100,
                minimum_commission=implementation_minimum,
                annual_fixed_cost=implementation_annual_fixed,
                annual_management_rate=implementation_annual_management_percent / 100,
            )
            implementation_source = implementation_source_input.strip()
        has_implementation_cost = any((
            implementation_assumptions.commission_bps,
            implementation_assumptions.market_cost_bps,
            implementation_assumptions.vat_rate,
            implementation_assumptions.minimum_commission,
            implementation_assumptions.annual_fixed_cost,
            implementation_assumptions.annual_management_rate,
        ))
        if has_implementation_cost and (
            not implementation_source or len(implementation_source) > 400
            or any(ord(char) < 32 for char in implementation_source)
        ):
            raise PortfolioError(
                "Declara la referencia del tarifario de costos en 1 a 400 caracteres."
            )
        if not has_implementation_cost and tariff_profile is None:
            implementation_source = "Sin tarifario; supuestos de costo en cero"
        implementation_estimates = tuple(
            estimate_implementation_cost(
                analysis_tickers, alternative.metrics.weights, portfolio_value,
                implementation_assumptions, alternative_name=alternative.name,
                current_weights=current_weights,
            )
            for alternative in alternatives
        )
        benchmark_analyses = ()
        benchmark_source = None
        benchmark_quality_issues = ()
        if benchmark_ticker_input.strip():
            benchmark_tickers = tuple(normalize_tickers(benchmark_ticker_input))
            if len(benchmark_tickers) != 1:
                raise PortfolioError("Ingresa un solo ticker como benchmark.")
            benchmark_ticker = benchmark_tickers[0]
            benchmark_download = cached_prices((benchmark_ticker,), start_date, end_date)
            if benchmark_download.rejected_tickers:
                raise PortfolioError("El benchmark no produjo una serie de precios válida.")
            benchmark_quality_issues = assess_price_quality(benchmark_download.prices)
            benchmark_fx = cached_fx(
                {benchmark_ticker: benchmark_quote}, base_currency, start_date, end_date
            )
            benchmark_prices = convert_prices(
                benchmark_download.prices,
                {benchmark_ticker: benchmark_quote},
                base_currency,
                benchmark_fx,
            )[benchmark_ticker]
            benchmark_analyses = tuple(
                analyze_benchmark(
                    returns, alternative.metrics.weights, benchmark_prices,
                    benchmark_name=benchmark_name_input,
                    portfolio_name=alternative.name,
                    risk_free_rate=risk_free_rate,
                )
                for alternative in alternatives
            )
            benchmark_source = (
                f"Yahoo Finance mediante yfinance; {benchmark_ticker}; precios ajustados; "
                f"cotización declarada {benchmark_quote}; convertido a {base_currency}"
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
            f"Precios CSV aportados por el equipo · {price_rights.source} / "
            f"{price_rights.product} · Alcance {price_rights.authorized_scope} · "
            f"Revisión {price_rights.reviewed_on.isoformat()} · "
            f"SHA-256 datos {price_fingerprint[:12]} y manifiesto "
            f"{price_rights.fingerprint[:12]}. La app valida la declaración, pero no sustituye "
            "la revisión del contrato ni verifica por sí misma los datos del proveedor."
        )
        if not price_rights.allows_client_deliverables:
            st.warning(
                "Este manifiesto autoriza sólo investigación interna. No entregues a clientes "
                "el PDF ni resultados derivados de estos precios."
            )
    else:
        st.warning(
            "Los precios descargados mediante Yahoo/yfinance se reservan para investigación "
            "interna y pruebas. No uses el PDF como entregable para clientes."
        )
    if holdings_result is not None:
        st.info(
            f"Cartera actual conciliada al {holdings_result.as_of.date()} · "
            f"{holdings_result.total_value:,.2f} MXN · {len(holdings_result.values)} instrumentos · "
            f"Fuente declarada: {holdings_source} · SHA-256 {holdings_fingerprint[:12]}. "
            "El total cargado sustituye el valor manual durante este análisis; el archivo no se persiste."
        )
        holdings_audit = pd.DataFrame({
            "Instrumento": holdings_result.values.index,
            "ValorMXN": holdings_result.values.to_numpy(),
            "Peso": holdings_result.weights.to_numpy(),
            "FechaCorte": holdings_result.as_of.date().isoformat(),
        })
        st.download_button(
            "Descargar conciliación de cartera actual CSV",
            holdings_audit.to_csv(index=False).encode("utf-8-sig"),
            "conciliacion_cartera_actual.csv", "text/csv",
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
    if bond_result is not None:
        coupon_count = int((bond_result.coupons > 0).sum())
        st.info(
            f"Serie {bond_name} integrada para la emisión {bond_result.issue_id}, con vencimiento "
            f"{bond_result.maturity_date.date()} y {coupon_count} cupón(es) reconocido(s) en el "
            "archivo. Verifica emisión, precios, devengado y flujos con la fuente."
        )
    if liquidity_result is not None:
        st.info(
            f"Serie {liquidity_name} integrada para {liquidity_result.vehicle}: tasa "
            f"{liquidity_result.treatment.lower()}, convención {liquidity_result.convention}. "
            "La tasa de cada fecha se aplica al intervalo siguiente. Verifica fuente, liquidez, "
            "comisiones, impuestos y protección aplicable al vehículo."
        )
    if fund_result is not None:
        distribution_count = int((fund_result.distributions > 0).sum())
        st.info(
            f"Serie {fund_name} integrada para {fund_result.fund_id}, serie "
            f"{fund_result.series_id}, con {distribution_count} distribución(es) reconocida(s). "
            "Verifica valores, distribuciones, comisiones, liquidez y derechos de la serie."
        )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Media histórica anualizada", percent(max_sharpe.annual_return))
    col2.metric("Volatilidad anualizada", percent(max_sharpe.annual_volatility))
    col3.metric("Sharpe histórico", f"{max_sharpe.sharpe_ratio:.2f}")
    col4.metric(f"VaR histórico ({confidence:.1%})", percent(risk.historical_var))

    if benchmark_analyses:
        with st.expander("Comparación contra benchmark", expanded=True):
            benchmark_rows = pd.DataFrame([
                {
                    "Alternativa": item.portfolio_name,
                    "Retorno anualizado": item.portfolio_annualized_return,
                    "Benchmark anualizado": item.benchmark_annualized_return,
                    "Retorno activo anualizado": item.annualized_active_return,
                    "Tracking error": item.tracking_error,
                    "Razón de información": item.information_ratio,
                    "Beta": item.beta,
                    "Alpha anualizada": item.annualized_alpha,
                    "Correlación": item.correlation,
                    "Máxima caída": item.portfolio_max_drawdown,
                    "Máxima caída benchmark": item.benchmark_max_drawdown,
                }
                for item in benchmark_analyses
            ])
            formatted_benchmark = benchmark_rows.copy()
            for column in (
                "Retorno anualizado", "Benchmark anualizado", "Retorno activo anualizado",
                "Tracking error", "Alpha anualizada", "Máxima caída",
                "Máxima caída benchmark",
            ):
                formatted_benchmark[column] = formatted_benchmark[column].map(
                    lambda value: f"{value:.2%}"
                )
            for column in ("Razón de información", "Beta", "Correlación"):
                formatted_benchmark[column] = formatted_benchmark[column].map(
                    lambda value: "N/D" if not np.isfinite(value) else f"{value:.2f}"
                )
            st.dataframe(formatted_benchmark, hide_index=True, use_container_width=True)
            selected_benchmark = st.selectbox(
                "Alternativa para la trayectoria relativa",
                [item.portfolio_name for item in benchmark_analyses],
            )
            selected_analysis = next(
                item for item in benchmark_analyses
                if item.portfolio_name == selected_benchmark
            )
            st.line_chart(selected_analysis.curves, y_label="Capital relativo (1 = inicio)")
            st.caption(
                f"{selected_analysis.name} · {selected_analysis.observations} retornos comunes · "
                f"{selected_analysis.start.date()} a {selected_analysis.end.date()}. "
                "La cartera supone rebalanceo diario para atribución histórica. Alpha usa CAPM "
                "con la tasa libre de riesgo indicada; no prueba habilidad ni causalidad."
            )
            if benchmark_quality_issues:
                st.warning(
                    f"El benchmark tiene {len(benchmark_quality_issues)} alerta(s) heurística(s) "
                    "de precio; revisa la fuente antes de interpretar la comparación."
                )

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
        if bond_result is not None:
            bond_audit = pd.concat([
                bond_result.clean_prices,
                bond_result.accrued_interest,
                bond_result.dirty_prices,
                bond_result.coupons,
                bond_result.index.rename("Índice retorno total"),
            ], axis=1)
            st.download_button(
                "Descargar auditoría Bono M CSV",
                bond_audit.to_csv().encode("utf-8-sig"),
                "bono_m_indice_preparado.csv",
                "text/csv",
            )
        if liquidity_result is not None:
            liquidity_audit = pd.concat([
                liquidity_result.annual_rates.mul(100).rename("Tasa anual %"),
                liquidity_result.calendar_days,
                liquidity_result.index.rename("Índice de acumulación"),
            ], axis=1)
            st.download_button(
                "Descargar auditoría de liquidez CSV",
                liquidity_audit.to_csv().encode("utf-8-sig"),
                "liquidez_indice_preparado.csv",
                "text/csv",
            )
        if fund_result is not None:
            fund_audit = pd.concat([
                fund_result.share_values,
                fund_result.distributions,
                fund_result.index.rename("Índice retorno total"),
            ], axis=1)
            st.download_button(
                "Descargar auditoría del fondo CSV",
                fund_audit.to_csv().encode("utf-8-sig"),
                "fondo_indice_preparado.csv",
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

    with st.expander("Atribución de riesgo y diversificación", expanded=True):
        risk_summary = pd.DataFrame([
            {
                "Alternativa": item.alternative_name,
                "Volatilidad": item.portfolio_volatility,
                "Razón de diversificación": item.diversification_ratio,
                "Posiciones efectivas": item.effective_positions,
                "Contribuyentes efectivos": item.effective_risk_contributors,
                "Mayor contribuyente": item.detail.loc[
                    item.detail["% absoluto del riesgo"].idxmax(), "Activo"
                ],
                "% absoluto mayor": item.detail["% absoluto del riesgo"].max(),
            }
            for item in risk_attributions
        ])
        formatted_risk = risk_summary.copy()
        formatted_risk["Volatilidad"] = formatted_risk["Volatilidad"].map(percent)
        formatted_risk["% absoluto mayor"] = formatted_risk["% absoluto mayor"].map(percent)
        for column in (
            "Razón de diversificación", "Posiciones efectivas", "Contribuyentes efectivos",
        ):
            formatted_risk[column] = formatted_risk[column].map(lambda value: f"{value:.2f}")
        st.dataframe(formatted_risk, hide_index=True, use_container_width=True)
        selected_risk_name = st.selectbox(
            "Alternativa para ver contribuciones de riesgo",
            [item.alternative_name for item in risk_attributions],
        )
        selected_risk = next(
            item for item in risk_attributions if item.alternative_name == selected_risk_name
        )
        detail_view = selected_risk.detail.copy()
        percentage_columns = [
            "Peso", "Volatilidad individual", "Contribución marginal",
            "Contribución a volatilidad", "% contribución a volatilidad",
            "% absoluto del riesgo",
        ]
        st.dataframe(
            detail_view.style.format({column: "{:.2%}" for column in percentage_columns}),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Las contribuciones con signo suman la volatilidad de la cartera; una contribución "
            "negativa indica cobertura dentro del modelo. El porcentaje absoluto se usa sólo "
            "para medir concentración y suma 100 %."
        )
        risk_download = pd.concat(
            [
                item.detail.assign(Alternativa=item.alternative_name)
                for item in risk_attributions
            ],
            ignore_index=True,
        )
        risk_download = risk_download[["Alternativa", *selected_risk.detail.columns]]
        st.download_button(
            "Descargar atribución de riesgo CSV",
            risk_download.to_csv(index=False).encode("utf-8-sig"),
            "atribucion_riesgo.csv",
            "text/csv",
        )

    if black_litterman_result is not None:
        with st.expander("Supuestos y resultados Black-Litterman", expanded=True):
            st.caption(
                f"Equilibrio: {black_litterman_source} · Aversión al riesgo: "
                f"{black_litterman_result.risk_aversion:.2f} · "
                f"Tau: {black_litterman_result.tau:.3f}."
            )
            black_litterman_view = black_litterman_result.detail.copy()
            black_litterman_view.insert(
                2, "Peso Black-Litterman", black_litterman_metrics.weights
            )
            for column in (
                "Peso de equilibrio", "Peso Black-Litterman", "Retorno de equilibrio",
                "Opinión", "Confianza", "Retorno posterior",
            ):
                black_litterman_view[column] = black_litterman_view[column].map(
                    lambda value: "N/D" if pd.isna(value) else f"{value:.2%}"
                )
            st.dataframe(black_litterman_view, hide_index=True, use_container_width=True)
            st.caption(
                "La alternativa maximiza Sharpe con los retornos posteriores y la misma "
                "covarianza histórica de las demás carteras. Una confianza mayor acerca el "
                "retorno posterior a la opinión declarada. Su retorno mostrado es una expectativa "
                "del modelo, no una media histórica ni evidencia de que la opinión sea correcta."
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
        if tariff_profile is not None:
            profile_recurring_cost = tariff_profile.assumptions.annual_recurring_cost(portfolio_value)
            st.info(
                f"Perfil contractual: {tariff_profile.intermediary} · {tariff_profile.product} · "
                f"{tariff_profile.market} · SHA-256 {tariff_fingerprint[:12]}. "
                f"Costo recurrente anual estimado: {profile_recurring_cost:,.2f} MXN. "
                "Los importes recurrentes se muestran por separado y no se descuentan de las métricas."
            )
        annual_recurring_cost = implementation_assumptions.annual_recurring_cost(portfolio_value)
        first_year_cost_by_alternative = {
            item.alternative_name: item.total_cost + annual_recurring_cost
            for item in implementation_estimates
        }
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
                "Costo recurrente anual": annual_recurring_cost,
                "Costo estimado primer año": first_year_cost_by_alternative[item.alternative_name],
                "Costo / capital": item.total_cost / portfolio_value if portfolio_value else np.nan,
                "Primer año / capital": (
                    first_year_cost_by_alternative[item.alternative_name] / portfolio_value
                    if portfolio_value else np.nan
                ),
            }
            for item in implementation_estimates
        ])
        st.dataframe(
            cost_summary.style.format({
                "Compras": "{:,.2f}", "Ventas": "{:,.2f}",
                "Nominal negociado": "{:,.2f}", "Comisión": "{:,.2f}",
                "IVA sobre comisión": "{:,.2f}", "Costo de mercado": "{:,.2f}",
                "Costo total": "{:,.2f}", "Costo / capital": "{:.3%}",
                "Costo recurrente anual": "{:,.2f}",
                "Costo estimado primer año": "{:,.2f}",
                "Primer año / capital": "{:.3%}",
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
            class_shocks = None
            shock_results = None
            shock_name = None
            shock_rationale = None
            asset_shock_enabled = st.checkbox("Añadir shock hipotético por activo")
            class_shock_enabled = st.checkbox("Añadir shock hipotético por clase")
            if asset_shock_enabled and class_shock_enabled:
                raise PortfolioError("Selecciona shocks por activo o por clase, no ambos.")
            if asset_shock_enabled or class_shock_enabled:
                shock_name_input = st.text_input(
                    "Nombre del escenario hipotético", "Escenario adverso manual"
                )
                shock_rationale_input = st.text_area(
                    "Fundamento del escenario",
                    "Supuesto definido por el equipo para análisis de sensibilidad.",
                    help="Describe brevemente la narrativa económica; máximo 240 caracteres.",
                )
                shock_name, shock_rationale = validate_scenario_metadata(
                    shock_name_input, shock_rationale_input
                )
                if asset_shock_enabled:
                    raw_shocks = st.text_input(
                        "Cambios por activo en %, en el mismo orden",
                        value=", ".join("-10" for _ in analysis_tickers),
                        help="Ejemplo para dos activos: -20, -5. El mínimo por activo es -100%.",
                    )
                    shocks_array = parse_asset_shocks(raw_shocks, len(analysis_tickers))
                else:
                    stress_classes = parse_asset_classes(
                        asset_classes_input, len(tickers)
                    ) + ("deuda_gubernamental",) * sum((
                        cetes_result is not None, bond_result is not None,
                    )) + (("efectivo",) if liquidity_result is not None else ())
                    stress_classes += (("fondo",) if fund_result is not None else ())
                    unique_classes = sorted(set(stress_classes))
                    raw_class_shocks = st.text_area(
                        "Cambios por clase: clase, shock %",
                        "\n".join(f"{name},-10" for name in unique_classes),
                        help="Incluye exactamente una línea por cada clase declarada.",
                    )
                    class_shocks, shocks_array = parse_class_shocks(
                        raw_class_shocks, stress_classes
                    )
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
                st.write(f"Resultado de **{shock_name}**:")
                st.caption(f"Fundamento: {shock_rationale}")
                if class_shocks is not None:
                    class_view = class_shocks.rename("Cambio hipotético").to_frame()
                    st.write("Shocks definidos por clase:")
                    st.dataframe(
                        class_view.style.format("{:.2%}"), use_container_width=True
                    )
                st.dataframe(shock_table, hide_index=True, use_container_width=True)
                contributions = pd.DataFrame({
                    name: result.contributions for name, result in shock_results.items()
                })
                st.write("Contribución de cada activo al cambio total:")
                st.dataframe(contributions.style.format("{:.2%}"), use_container_width=True)
                shock_export = pd.DataFrame({
                    "Activo": analysis_tickers,
                    "Clase": (
                        stress_classes if class_shocks is not None
                        else tuple("definido_por_activo" for _ in analysis_tickers)
                    ),
                    "Shock": shocks_array,
                })
                st.download_button(
                    "Descargar escenario hipotético CSV",
                    shock_export.to_csv(index=False).encode("utf-8-sig"),
                    "escenario_estres_hipotetico.csv", "text/csv",
                )
            stress_report = StressReport(
                stress_history, shocks, shock_results,
                class_shocks=class_shocks, shock_name=shock_name,
                shock_rationale=shock_rationale,
            )
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
                    current_weights=current_weights,
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
                        current_weights=current_weights,
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
                                current_weights=current_weights,
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
                        current_weights=current_weights,
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
                    current_weights=current_weights,
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
                        current_weights=current_weights,
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
                                current_weights=current_weights,
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
        benchmark_analyses=benchmark_analyses[:1],
        benchmark_source=benchmark_source,
        risk_attributions=risk_attributions[:1],
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
        benchmark_analyses=benchmark_analyses,
        benchmark_source=benchmark_source,
        risk_attributions=risk_attributions,
        black_litterman=black_litterman_result,
        black_litterman_source=black_litterman_source,
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
