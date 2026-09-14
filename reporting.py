"""PDF reporting for the portfolio optimizer."""

import io
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from portfolio_core import PortfolioMetrics, RiskMetrics, validate_weights


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
        Paragraph("Agencia de Inversiones · Reporte cuantitativo V2", styles["Title"]),
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
