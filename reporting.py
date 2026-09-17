"""PDF reporting for the portfolio optimizer."""

import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from implementation_costs import (
    ImplementationCostAssumptions,
    ImplementationCostEstimate,
)
from portfolio_core import PortfolioMetrics, RiskMetrics, validate_weights
from price_quality import PriceQualityIssue
from simulation import SimulationResult
from stress import ShockResult


@dataclass(frozen=True)
class PortfolioAlternative:
    name: str
    metrics: PortfolioMetrics
    risk: RiskMetrics


@dataclass(frozen=True)
class SimulationReport:
    alternative_name: str
    result: SimulationResult
    monthly_contribution: float
    monthly_withdrawal: float
    annual_fee: float
    transaction_cost_bps: float
    inflation_rate: float
    rebalance_months: int | None
    block_days: int


@dataclass(frozen=True)
class StressReport:
    historical: pd.DataFrame
    shocks: pd.Series | None = None
    shock_results: dict[str, ShockResult] | None = None


def _allocation_policy_story(policy: pd.DataFrame | None, styles) -> list:
    if policy is None:
        return []
    required = ["Clase", "Mínimo", "Máximo", "Activos"]
    if list(policy.columns) != required or policy.empty:
        raise ValueError("La política por clase no tiene el formato esperado.")
    numeric = policy[["Mínimo", "Máximo", "Activos"]].to_numpy(dtype=float)
    if (
        not np.isfinite(numeric).all()
        or (policy["Mínimo"] < 0).any()
        or (policy["Máximo"] > 1).any()
        or (policy["Mínimo"] > policy["Máximo"]).any()
        or (policy["Activos"] < 1).any()
        or policy["Clase"].astype(str).str.strip().eq("").any()
        or policy["Clase"].duplicated().any()
    ):
        raise ValueError("La política por clase contiene valores inválidos.")
    rows = [["Clase declarada", "Mínimo", "Máximo", "Activos"]] + [
        [
            Paragraph(escape(str(row.Clase)), styles["Normal"]),
            f"{row.Mínimo:.1%}", f"{row.Máximo:.1%}", str(int(row.Activos)),
        ]
        for row in policy.itertuples(index=False)
    ]
    table = Table(rows, colWidths=[70 * mm, 30 * mm, 30 * mm, 25 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [
        Spacer(1, 3 * mm),
        KeepTogether([
            Paragraph("Política por clase de activo", styles["Heading2"]),
            table,
            Paragraph(
                "La clasificación fue declarada por el usuario y no fue verificada contra una "
                "fuente externa. Las carteras optimizadas respetan estos intervalos.",
                styles["Normal"],
            ),
        ]),
    ]


def _implementation_cost_story(
    estimates: tuple[ImplementationCostEstimate, ...],
    assumptions: ImplementationCostAssumptions | None,
    portfolio_value: float,
    currency: str,
    source: str | None,
    source_date: date | None,
    styles,
) -> list:
    if not estimates:
        return []
    if assumptions is None:
        raise ValueError("Faltan los supuestos del costo de implementación.")
    if (
        not source or len(source) > 120 or any(ord(char) < 32 for char in source)
        or source_date is None or source_date > date.today()
    ):
        raise ValueError("Falta la referencia fechada del costo de implementación.")
    if not np.isfinite(portfolio_value) or portfolio_value < 0:
        raise ValueError("Capital inválido para el costo de implementación.")
    if len({item.alternative_name for item in estimates}) != len(estimates):
        raise ValueError("Las alternativas de costos deben tener nombres únicos.")
    for item in estimates:
        components = np.array([
            item.buy_notional, item.sell_notional, item.commission,
            item.vat, item.market_cost, item.total_cost,
        ])
        if (
            not np.isfinite(components).all() or (components < 0).any()
            or not np.isclose(
                item.total_cost, item.commission + item.vat + item.market_cost,
                atol=0.005, rtol=0,
            )
        ):
            raise ValueError("Estimación de costos inválida.")
    rows = [["Alternativa", "Compras", "Ventas", "Costo total", "% capital"]]
    for item in estimates:
        rows.append([
            Paragraph(escape(item.alternative_name), styles["Normal"]),
            f"{item.buy_notional:,.0f}", f"{item.sell_notional:,.0f}",
            f"{item.total_cost:,.2f}",
            f"{item.total_cost / portfolio_value:.3%}" if portfolio_value else "N/A",
        ])
    table = Table(rows, colWidths=[49 * mm, 34 * mm, 34 * mm, 38 * mm, 26 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
    ]))
    assumptions_text = (
        f"Referencia: {escape(source)}; consulta: {source_date.isoformat()}. "
        f"Moneda: {escape(currency)}. Comisión: {assumptions.commission_bps:.1f} pb por orden; "
        f"IVA sobre comisión: {assumptions.vat_rate:.2%}; costo de mercado: "
        f"{assumptions.market_cost_bps:.1f} pb sobre nominal; mínimo por orden: "
        f"{assumptions.minimum_commission:,.2f}."
    )
    section = [
        Paragraph("Costo estimado de implementación", styles["Heading2"]),
        Paragraph(assumptions_text, styles["Normal"]),
        Spacer(1, 2 * mm), table, Spacer(1, 1 * mm),
        Paragraph(
            "Cada compra y venta se cobra por separado. El costo se suma al nominal objetivo; "
            "no incluye lotes, impuestos sobre ganancias ni una ejecución autofinanciada.",
            styles["Normal"],
        ),
        Spacer(1, 3 * mm),
    ]
    return [KeepTogether(section)]


def _price_quality_story(
    issues: tuple[PriceQualityIssue, ...], styles, *, compact: bool = False
) -> list:
    story = [Paragraph("Revisión de precios originales", styles["Heading2"])]
    if compact:
        if issues:
            shown = "; ".join(
                f"{escape(issue.ticker)}: {escape(issue.kind)}"
                for issue in issues[:2]
            )
            story.append(Paragraph(
                f"En moneda de cotización: {len(issues)} alerta(s) ({shown}). "
                "Umbrales: 30% / 5 sesiones; no verifican ajustes. Detalle: CSV de la aplicación.",
                styles["Normal"],
            ))
        else:
            story.append(Paragraph(
                "En moneda de cotización: sin alertas con los umbrales 30% / 5 sesiones; "
                "esto no verifica ajustes.", styles["Normal"],
            ))
        return story
    if not issues:
        story.append(Paragraph(
            "En moneda de cotización: sin alertas con los umbrales 30% / 5 sesiones; "
            "esto no verifica ajustes.", styles["Normal"],
        ))
        return story
    if 0 < len(issues) <= 3:
        story.append(Paragraph(
            f"En moneda de cotización: {len(issues)} alerta(s). Umbrales 30% / 5 sesiones; "
            "ajustes no verificados.",
            styles["Normal"],
        ))
        for issue in issues:
            story.append(Paragraph(
                f"{escape(issue.ticker)}: {escape(issue.kind)}, "
                f"{issue.first_date} a {issue.last_date}, {escape(issue.detail)}.",
                styles["Normal"],
            ))
        return [KeepTogether(story), Spacer(1, 4 * mm)]
    story.append(Paragraph(
        "Cierres en moneda de cotización, antes del FX: cambio de al menos 30% o cinco "
        "sesiones consecutivas sin variar. Una alerta puede ser un evento real; su ausencia "
        "no verifica ajustes, moneda, integridad ni derechos de uso.", styles["Normal"],
    ))
    story.append(Paragraph(
        f"{len(issues)} alerta(s); hasta 12 visibles aquí. Listado completo: CSV de la aplicación.",
        styles["Normal"],
    ))
    rows = [["Activo", "Tipo", "Periodo", "Detalle"]]
    for issue in issues[:12]:
        rows.append([
            Paragraph(escape(issue.ticker), styles["Normal"]),
            Paragraph(escape(issue.kind), styles["Normal"]),
            Paragraph(f"{issue.first_date} a {issue.last_date}", styles["Normal"]),
            Paragraph(escape(issue.detail), styles["Normal"]),
        ])
    table = Table(rows, colWidths=[30 * mm, 42 * mm, 42 * mm, 67 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
    ]))
    return [KeepTogether(story + [Spacer(1, 2 * mm), table]), Spacer(1, 4 * mm)]


def _simulation_chart(result: SimulationResult, withdrawal_mode: bool) -> Drawing:
    bands = result.bands()
    drawing = Drawing(180 * mm, 55 * mm)
    left, bottom, width, height = 18 * mm, 10 * mm, 155 * mm, 36 * mm
    maximum = max(float(bands["Percentil 95"].max()), float(bands["Capital aportado"].max()))
    maximum = max(maximum * 1.08, 1.0)
    months = len(bands) - 1

    def compact(value):
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f} M"
        if value >= 1_000:
            return f"{value / 1_000:.0f} k"
        return f"{value:.0f}"

    def point(month, value):
        return left + month / months * width, bottom + float(value) / maximum * height

    upper = [point(month, value) for month, value in enumerate(bands["Percentil 95"])]
    lower = [point(month, value) for month, value in enumerate(bands["Percentil 5"])]
    drawing.add(Polygon(
        [coordinate for pair in upper + lower[::-1] for coordinate in pair],
        fillColor=colors.HexColor("#DDEBF1"), strokeColor=None,
    ))
    for label, color, line_width in (
        ("Mediana", "#176B91", 2.0), ("Capital aportado", "#666666", 1.2),
    ):
        points = [point(month, value) for month, value in enumerate(bands[label])]
        drawing.add(PolyLine(
            [coordinate for pair in points for coordinate in pair],
            strokeColor=colors.HexColor(color), strokeWidth=line_width,
        ))
    drawing.add(Line(left, bottom, left + width, bottom, strokeColor=colors.HexColor("#8CA0AE")))
    drawing.add(Line(left, bottom, left, bottom + height, strokeColor=colors.HexColor("#8CA0AE")))
    drawing.add(String(left - 1 * mm, bottom - 5 * mm, "0", fontSize=8))
    drawing.add(String(1 * mm, bottom + height - 1 * mm, compact(maximum), fontSize=8))
    drawing.add(String(1 * mm, bottom + height / 2, compact(maximum / 2), fontSize=8))
    drawing.add(String(left + width - 14 * mm, bottom - 5 * mm, f"{months} meses", fontSize=8))
    drawing.add(String(left, bottom + height + 3 * mm, "Banda 5-95 %", fontSize=8))
    drawing.add(String(left + 46 * mm, bottom + height + 3 * mm, "Mediana", fontSize=8,
                       fillColor=colors.HexColor("#176B91")))
    capital_label = "Capital inicial" if withdrawal_mode else "Capital aportado"
    drawing.add(String(left + 80 * mm, bottom + height + 3 * mm, capital_label, fontSize=8,
                       fillColor=colors.HexColor("#666666")))
    return drawing


def create_comparison_pdf_report(
    tickers: tuple[str, ...],
    start_date: date,
    end_date: date,
    alternatives: tuple[PortfolioAlternative, ...],
    portfolio_value: float,
    *,
    base_currency: str,
    risk_free_rate: float,
    observations: int,
    quotes: dict[str, str],
    data_source: str = "Yahoo Finance mediante yfinance; precios ajustados y FX histórico",
    simulation: SimulationReport | None = None,
    stress: StressReport | None = None,
    price_quality_issues: tuple[PriceQualityIssue, ...] = (),
    implementation_costs: tuple[ImplementationCostEstimate, ...] = (),
    implementation_cost_assumptions: ImplementationCostAssumptions | None = None,
    implementation_cost_source: str | None = None,
    implementation_cost_source_date: date | None = None,
    allocation_policy: pd.DataFrame | None = None,
) -> bytes:
    """Compare historical portfolio alternatives on one sample and set of assumptions."""
    if not 2 <= len(alternatives) <= 4 or len({item.name for item in alternatives}) != len(alternatives):
        raise ValueError("Se requieren de dos a cuatro alternativas con nombres únicos.")
    if not tickers or observations < 1 or not np.isfinite(portfolio_value) or portfolio_value < 0:
        raise ValueError("Parámetros inválidos para el comparativo.")
    first_risk = alternatives[0].risk
    for item in alternatives:
        validate_weights(item.metrics.weights, len(tickers))
        if (item.risk.confidence_level, item.risk.horizon_days) != (
            first_risk.confidence_level, first_risk.horizon_days
        ):
            raise ValueError("Todas las alternativas deben usar el mismo horizonte y confianza.")
    alternative_names = {item.name for item in alternatives}
    if any(item.alternative_name not in alternative_names for item in implementation_costs):
        raise ValueError("El costo de implementación no pertenece al comparativo.")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=17 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#17365D")
    styles["Title"].fontSize = 17
    styles["Title"].leading = 20
    styles["Heading2"].textColor = colors.HexColor("#17365D")
    story = [
        Paragraph("Comparativo de carteras", styles["Title"]),
        Paragraph("Análisis histórico para revisión del equipo", styles["Normal"]),
        Spacer(1, 5 * mm),
        Paragraph(
            f"Generado: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} | "
            f"Periodo efectivo: {start_date.isoformat()} a {end_date.isoformat()} | "
            f"Moneda: {escape(base_currency)}",
            styles["Normal"],
        ),
        Paragraph(
            f"Capital de referencia: {portfolio_value:,.2f} {escape(base_currency)} | "
            f"Tasa libre de riesgo supuesta: {risk_free_rate:.2%} | "
            f"Retornos diarios comunes: {observations:,}",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
    ]
    story.extend(_allocation_policy_story(allocation_policy, styles))
    story.extend([
        Paragraph("Resultados comparables", styles["Heading2"]),
        Paragraph(
            "Todas las alternativas usan los mismos activos, fechas, moneda y parámetros de riesgo. "
            "Las medias son históricas anualizadas; no son rendimientos previstos.",
            styles["Normal"],
        ),
        Spacer(1, 2 * mm),
    ])

    def comparison_row(label, getter, formatter):
        return [label] + [formatter(getter(item)) for item in alternatives]

    rows = [["Métrica"] + [Paragraph(escape(item.name), styles["Normal"]) for item in alternatives]]
    rows += [
        comparison_row("Media anualizada", lambda item: item.metrics.annual_return, lambda x: f"{x:.2%}"),
        comparison_row(
            "Volatilidad anualizada", lambda item: item.metrics.annual_volatility, lambda x: f"{x:.2%}"
        ),
        comparison_row("Sharpe histórico", lambda item: item.metrics.sharpe_ratio, lambda x: f"{x:.2f}"),
        comparison_row("VaR histórico", lambda item: item.risk.historical_var, lambda x: f"{x:.2%}"),
        comparison_row("CVaR histórico", lambda item: item.risk.historical_cvar, lambda x: f"{x:.2%}"),
        comparison_row(
            f"VaR en {base_currency}",
            lambda item: item.risk.historical_var * portfolio_value,
            lambda x: f"{x:,.0f}",
        ),
    ]
    width = (185 * mm - 50 * mm) / len(alternatives)
    main_table = Table(rows, colWidths=[50 * mm] + [width] * len(alternatives), repeatRows=1)
    main_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([
        main_table,
        Spacer(1, 2 * mm),
        Paragraph(
            f"VaR y CVaR: pérdida histórica estimada al {first_risk.confidence_level:.1%} "
            f"para {first_risk.horizon_days} sesión(es). No son pérdidas máximas posibles.",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Asignación por instrumento", styles["Heading2"]),
    ])
    allocation_rows = [["Activo"] + [Paragraph(escape(item.name), styles["Normal"]) for item in alternatives]]
    for index, ticker in enumerate(tickers):
        label = f"{escape(ticker)} ({escape(quotes.get(ticker, base_currency))})"
        allocation_rows.append([Paragraph(label, styles["Normal"])] + [
            f"{item.metrics.weights[index]:.2%}" for item in alternatives
        ])
    allocation_table = Table(
        allocation_rows, colWidths=[50 * mm] + [width] * len(alternatives), repeatRows=1
    )
    allocation_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        allocation_table,
        Spacer(1, 2 * mm),
    ])
    story.extend(_price_quality_story(price_quality_issues, styles, compact=True))
    story.extend(_implementation_cost_story(
        implementation_costs, implementation_cost_assumptions,
        portfolio_value, base_currency,
        implementation_cost_source, implementation_cost_source_date, styles,
    ))
    story.extend([
        Paragraph("Método y límites", styles["Heading2"]),
        Paragraph(
            f"Fuente: {escape(data_source)}. "
            "Retornos diarios anualizados con 252 sesiones. Se optimizan pesos largos con el "
            "límite elegido. La cartera actual es una referencia ingresada y el riesgo histórico "
            "supone rebalanceo diario.",
            styles["Normal"],
        ),
        Paragraph(
            "Las métricas anteriores no descuentan comisiones, diferenciales ni impuestos, y no "
            "modelan liquidez. Los pesos usan la misma "
            "muestra que los resultados: no es una prueba fuera de muestra ni una recomendación "
            "personalizada. La entrega a terceros requiere revisión legal.",
            styles["Normal"],
        ),
    ])

    if simulation is not None:
        if simulation.alternative_name not in {item.name for item in alternatives}:
            raise ValueError("La asignación simulada no pertenece al comparativo.")
        values = simulation.result.monthly_values
        if (values.ndim != 2 or len(values) < 2 or values.shape[1] < 1
                or not np.isfinite(values).all()):
            raise ValueError("La simulación no contiene trayectorias válidas.")
        if simulation.result.method not in {"bootstrap_blocks", "lognormal"}:
            raise ValueError("Método de simulación no reconocido.")
        bands = simulation.result.bands()
        final = bands.iloc[-1]
        months = len(values) - 1
        method = (
            "Remuestreo de bloques históricos"
            if simulation.result.method == "bootstrap_blocks"
            else "Modelo lognormal correlacionado"
        )
        rebalance = (
            "Sin rebalanceo" if simulation.rebalance_months is None
            else f"Cada {simulation.rebalance_months} meses"
        )
        cash_flow_amount = simulation.monthly_withdrawal or simulation.monthly_contribution
        cash_flow_label = "Retiro mensual" if simulation.monthly_withdrawal > 0 else "Aportación mensual"
        assumptions = [
            ["Escenario", escape(simulation.alternative_name)],
            ["Método", method],
            ["Muestra para calibración",
             f"{start_date.isoformat()} a {end_date.isoformat()} | {observations:,} retornos"],
            ["Horizonte y trayectorias", f"{months} meses | {values.shape[1]:,} trayectorias"],
            ["Semilla y bloque", f"{simulation.result.seed} | {simulation.block_days} sesiones"],
            [cash_flow_label, f"{cash_flow_amount:,.2f} {base_currency}"],
            ["Comisión anual", f"{simulation.annual_fee:.2%}"],
            ["Costo por operación", f"{simulation.transaction_cost_bps:.1f} puntos base"],
            ["Inflación anual", f"{simulation.inflation_rate:.2%}"],
            ["Rebalanceo", rebalance],
        ]
        results = [
            ["Percentil 5 final nominal", f"{final['Percentil 5']:,.0f} {base_currency}"],
            ["Mediana final nominal", f"{final['Mediana']:,.0f} {base_currency}"],
            ["Percentil 95 final nominal", f"{final['Percentil 95']:,.0f} {base_currency}"],
            ["Mediana final real",
             f"{np.median(simulation.result.real_terminal_values):,.0f} {base_currency}"],
        ]
        if simulation.monthly_withdrawal > 0:
            results.extend([
                ["Retiros programados", f"{simulation.monthly_withdrawal * months:,.0f} {base_currency}"],
                ["Mediana efectivamente retirada",
                 f"{np.median(simulation.result.total_withdrawn):,.0f} {base_currency}"],
                ["Trayectorias con retiro no cubierto",
                 f"{simulation.result.probability_of_shortfall:.1%}"],
            ])
        else:
            results.extend([
                ["Capital aportado", f"{final['Capital aportado']:,.0f} {base_currency}"],
                ["Trayectorias bajo capital aportado",
                 f"{simulation.result.probability_below_contributions:.1%}"],
            ])
        if simulation.monthly_withdrawal > 0:
            flow_note = (
                "Si falta dinero para un retiro, se vende lo disponible y se marca la trayectoria "
                "como insuficiente; no hay deuda ni saldo negativo. "
            )
        else:
            flow_note = (
                "La frecuencia bajo capital aportado no es una probabilidad calibrada. "
                "No incluye retiros. "
            )

        def simple_table(rows):
            table = Table(rows, colWidths=[86 * mm, 99 * mm])
            table.setStyle(TableStyle([
                ("ROWBACKGROUNDS", (0, 0), (-1, -1),
                 [colors.white, colors.HexColor("#F4F7FA")]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7E0E5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]))
            return table

        story.extend([
            PageBreak(),
            Paragraph("Escenarios Monte Carlo", styles["Title"]),
            Paragraph(
                "Distribución hipotética del patrimonio para una asignación del comparativo. "
                "Las cifras no son rendimientos previstos ni límites garantizados.",
                styles["Normal"],
            ),
            Spacer(1, 4 * mm),
            Paragraph("Supuestos", styles["Heading2"]),
            simple_table(assumptions),
            Spacer(1, 4 * mm),
            Paragraph("Patrimonio al final del horizonte", styles["Heading2"]),
            simple_table(results),
            Spacer(1, 4 * mm),
            _simulation_chart(simulation.result, simulation.monthly_withdrawal > 0),
            Spacer(1, 2 * mm),
            Paragraph(
                flow_note + "La banda muestra percentiles entre trayectorias por mes. "
                "El valor real descuenta "
                "inflación supuesta; comisión diaria y costos de operación afectan los resultados. "
                "La muestra puede omitir cambios de régimen. No incluye impuestos ni liquidez.",
                styles["Normal"],
            ),
        ])

    if stress is not None:
        required = {"Escenario", "Horizonte", "Inicio", "Fin", "Peor retorno"}
        if stress.historical.empty or not required.issubset(stress.historical.columns):
            raise ValueError("El estrés histórico no contiene las columnas requeridas.")
        stress_rows = [["Escenario", "Ventana", "Inicio", "Fin", "Peor retorno"]]
        for row in stress.historical.to_dict("records"):
            stress_rows.append([
                Paragraph(escape(str(row["Escenario"])), styles["Normal"]),
                f"{row['Horizonte']} sesión(es)",
                pd.Timestamp(row["Inicio"]).date().isoformat(),
                pd.Timestamp(row["Fin"]).date().isoformat(),
                f"{row['Peor retorno']:.2%}",
            ])
        stress_table = Table(
            stress_rows, colWidths=[48 * mm, 32 * mm, 34 * mm, 34 * mm, 32 * mm],
            repeatRows=1,
        )
        stress_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FA")]),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        story.extend([
            PageBreak(),
            Paragraph("Pruebas de estrés", styles["Title"]),
            Paragraph(
                "Las peores ventanas corresponden a hechos observados en la muestra. Se calculan "
                "con pesos constantes al cierre de cada sesión y rendimientos compuestos.",
                styles["Normal"],
            ),
            Spacer(1, 2 * mm),
            Paragraph("Peores ventanas históricas", styles["Heading2"]),
            stress_table,
        ])
        if stress.shocks is not None and stress.shock_results:
            shock_rows = [["Activo", "Cambio hipotético"]] + [
                [escape(str(label)), f"{value:.2%}"] for label, value in stress.shocks.items()
            ]
            outcome_rows = [["Escenario", "Cambio", f"Valor ({base_currency})", "Pérdida"]] + [
                [
                    Paragraph(escape(name), styles["Normal"]),
                    f"{result.portfolio_return:.2%}",
                    f"{result.stressed_value:,.0f}",
                    f"{result.loss_amount:,.0f}",
                ]
                for name, result in stress.shock_results.items()
            ]
            shock_table = Table(shock_rows, colWidths=[90 * mm, 90 * mm], repeatRows=1)
            outcome_table = Table(
                outcome_rows, colWidths=[60 * mm, 35 * mm, 48 * mm, 42 * mm], repeatRows=1,
            )
            for table in (shock_table, outcome_table):
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDEBF1")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#F4F7FA")]),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D2DD")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]))
            story.extend([
                Spacer(1, 3 * mm),
                Paragraph("Shock hipotético simultáneo", styles["Heading2"]),
                Paragraph(
                    "Cambios definidos por activo sobre posiciones valuadas en la moneda base. "
                    "Es un cálculo estático de un paso; no asigna probabilidad ni modela recuperación.",
                    styles["Normal"],
                ),
                Spacer(1, 1 * mm), shock_table, Spacer(1, 2 * mm), outcome_table,
            ])
        story.extend([
            Spacer(1, 2 * mm),
            Paragraph(
                "Una pérdida histórica no es la máxima posible. El resultado depende del periodo, "
                "los instrumentos y el rebalanceo; no incorpora liquidez, suspensiones ni incumplimientos.",
                styles["Normal"],
            ),
        ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#C7D2DD"))
        canvas.line(15 * mm, 14 * mm, 200 * mm, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, 10 * mm, "Comparativo histórico | Revisión interna")
        canvas.drawRightString(200 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def create_pdf_report(
    tickers: tuple[str, ...],
    start_date: date,
    end_date: date,
    metrics: PortfolioMetrics,
    risk: RiskMetrics,
    portfolio_value: float,
    *,
    base_currency: str = "USD",
    risk_free_rate: float = 0.0,
    max_weight: float = 1.0,
    observations: int | None = None,
    quotes: dict | None = None,
    data_source: str = "Yahoo Finance mediante yfinance; precios ajustados y FX histórico",
    price_quality_issues: tuple[PriceQualityIssue, ...] = (),
    implementation_costs: tuple[ImplementationCostEstimate, ...] = (),
    implementation_cost_assumptions: ImplementationCostAssumptions | None = None,
    implementation_cost_source: str | None = None,
    implementation_cost_source_date: date | None = None,
    allocation_policy: pd.DataFrame | None = None,
) -> bytes:
    """Create a compact, methodology-first report."""
    validate_weights(metrics.weights, len(tickers), max_weight)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Reporte cuantitativo V2", styles["Title"]),
        Paragraph(f"Generado: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]),
        Spacer(1, 3 * mm),
        Paragraph("Alcance", styles["Heading2"]),
        Paragraph(
            "Análisis histórico educativo. No es una recomendación personalizada "
            "ni una garantía de rendimiento futuro.",
            styles["Normal"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("Parámetros", styles["Heading2"]),
        Paragraph(f"Activos válidos: {escape(', '.join(tickers))}", styles["Normal"]),
        Paragraph(f"Periodo efectivo: {start_date.isoformat()} a {end_date.isoformat()}", styles["Normal"]),
        Paragraph(
            f"Moneda base: {escape(base_currency)} | Capital: {portfolio_value:,.2f}<br/>"
            f"Tasa libre de riesgo: {risk_free_rate:.2%} | Peso máximo: {max_weight:.2%}<br/>"
            f"Observaciones de retornos: {observations if observations is not None else 'No indicadas'}<br/>"
            f"Fuente: {escape(data_source)}.",
            styles["Normal"],
        ),
        Spacer(1, 3 * mm),
    ]
    story.extend(_allocation_policy_story(allocation_policy, styles))
    rows = [
        ["Métrica", "Estimación", "Importe"],
        ["Media histórica anualizada", f"{metrics.annual_return:.2%}", "—"],
        ["Volatilidad anualizada", f"{metrics.annual_volatility:.2%}", "—"],
        ["Sharpe histórico", f"{metrics.sharpe_ratio:.2f}", "—"],
        ["VaR paramétrico", f"{risk.parametric_var:.2%}", f"{portfolio_value * risk.parametric_var:,.2f}"],
        [
            f"VaR histórico ({risk.confidence_level:.1%})",
            f"{risk.historical_var:.2%}",
            f"{portfolio_value * risk.historical_var:,.2f}",
        ],
        ["CVaR histórico", f"{risk.historical_cvar:.2%}", f"{portfolio_value * risk.historical_cvar:,.2f}"],
    ]
    rows[0][2] = f"Importe ({base_currency})"
    table = Table(rows, colWidths=[75 * mm, 40 * mm, 40 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 3 * mm),
            Paragraph("Asignación de máximo Sharpe", styles["Heading2"]),
            Table(
                [["Activo", "Cotización", "Peso", f"Importe ({base_currency})"]]
                + [
                    [
                        ticker,
                        (quotes or {}).get(ticker, base_currency),
                        f"{weight:.2%}",
                        f"{weight * portfolio_value:,.2f}",
                    ]
                    for ticker, weight in zip(tickers, metrics.weights, strict=True)
                ],
                colWidths=[40 * mm, 35 * mm, 30 * mm, 50 * mm],
                repeatRows=1,
                style=[
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ],
            ),
            Spacer(1, 3 * mm),
            Paragraph("Metodología", styles["Heading2"]),
            Paragraph(
                "Precios ajustados, rendimientos aritméticos diarios y 252 sesiones por año. "
                "La optimización es long-only con límite de concentración. "
                "VaR y CVaR son magnitudes positivas "
                f"de pérdida para un horizonte de {risk.horizon_days} día(s).",
                styles["Normal"],
            ),
            Spacer(1, 3 * mm),
            Paragraph(
                "La conversión multiplica precios por unidades de moneda base por unidad de cotización; "
                "se descartan fechas sin FX, sin rellenarlas. No constituye cobertura cambiaria. "
                "El riesgo histórico capitaliza retornos con rebalanceo diario y ventanas solapadas; "
                "el paramétrico usa una aproximación normal aditiva. "
                "Las métricas anteriores no descuentan costos ni impuestos, y no modelan liquidez, "
                "situación financiera del cliente o cambios estructurales futuros.",
                styles["Normal"],
            ),
        ]
    )

    story.extend(_price_quality_story(price_quality_issues, styles))
    story.extend(_implementation_cost_story(
        implementation_costs, implementation_cost_assumptions,
        portfolio_value, base_currency,
        implementation_cost_source, implementation_cost_source_date, styles,
    ))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(190 * mm, 12 * mm, f"V2 | Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
