"""PDF reporting for the portfolio optimizer."""

import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

import numpy as np
from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from portfolio_core import PortfolioMetrics, RiskMetrics, validate_weights
from simulation import SimulationResult


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
    annual_fee: float
    transaction_cost_bps: float
    inflation_rate: float
    rebalance_months: int | None
    block_days: int


def _simulation_chart(result: SimulationResult) -> Drawing:
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
    drawing.add(String(left + 80 * mm, bottom + height + 3 * mm, "Capital aportado", fontSize=8,
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
        Paragraph("Resultados comparables", styles["Heading2"]),
        Paragraph(
            "Todas las alternativas usan los mismos activos, fechas, moneda y parámetros de riesgo. "
            "Las medias son históricas anualizadas; no son rendimientos previstos.",
            styles["Normal"],
        ),
        Spacer(1, 2 * mm),
    ]

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
        Spacer(1, 5 * mm),
        Paragraph("Método y límites", styles["Heading2"]),
        Paragraph(
            f"Fuente: {escape(data_source)}. "
            "Retornos aritméticos diarios y anualización con 252 sesiones. Máximo Sharpe y mínima "
            "volatilidad se optimizan con posiciones largas y el límite de concentración elegido. "
            "La cartera actual, si aparece, es una referencia ingresada por el usuario y puede superar "
            "ese límite. El cálculo histórico de riesgo supone rebalanceo diario.",
            styles["Normal"],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            "No se incluyen comisiones, diferenciales, impuestos ni restricciones de liquidez. "
            "Los resultados usan la misma muestra con la que se estimaron los pesos optimizados; "
            "no son una prueba fuera de muestra ni una recomendación personalizada. "
            "La entrega a terceros requiere revisión legal de su contenido y contexto.",
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
        assumptions = [
            ["Escenario", escape(simulation.alternative_name)],
            ["Método", method],
            ["Muestra para calibración",
             f"{start_date.isoformat()} a {end_date.isoformat()} | {observations:,} retornos"],
            ["Horizonte y trayectorias", f"{months} meses | {values.shape[1]:,} trayectorias"],
            ["Semilla y bloque", f"{simulation.result.seed} | {simulation.block_days} sesiones"],
            ["Aportación mensual", f"{simulation.monthly_contribution:,.2f} {base_currency}"],
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
            ["Capital aportado", f"{final['Capital aportado']:,.0f} {base_currency}"],
            ["Trayectorias bajo capital aportado",
             f"{simulation.result.probability_below_contributions:.1%}"],
        ]

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
            _simulation_chart(simulation.result),
            Spacer(1, 2 * mm),
            Paragraph(
                "La banda muestra percentiles entre trayectorias en cada mes. El valor real "
                "descuenta la inflación supuesta; la comisión se aplica diariamente y el costo "
                "de operación a compras y rebalanceos. La frecuencia bajo capital aportado no "
                "es una probabilidad calibrada. Se reutiliza la muestra histórica, que puede "
                "omitir cambios de régimen. No incluye retiros, impuestos, diferenciales ni liquidez.",
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
            "Fuente: Yahoo Finance mediante yfinance; precios ajustados y FX histórico.",
            styles["Normal"],
        ),
        Spacer(1, 3 * mm),
    ]
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
                "Limitaciones: no incluye costos, impuestos, liquidez, "
                "situación financiera del cliente ni cambios estructurales futuros.",
                styles["Normal"],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(190 * mm, 12 * mm, f"V2 | Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
