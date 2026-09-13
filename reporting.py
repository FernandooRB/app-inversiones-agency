"""PDF reporting for the portfolio optimizer."""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from portfolio_core import PortfolioMetrics, RiskMetrics


def create_pdf_report(
    tickers: tuple[str, ...],
    start_date: date,
    end_date: date,
    metrics: PortfolioMetrics,
    risk: RiskMetrics,
    portfolio_value: float,
) -> bytes:
    """Create a compact, methodology-first report."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=18 * mm, leftMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Agencia de Inversiones · Reporte cuantitativo V2", styles["Title"]),
        Paragraph(f"Generado: {date.today().isoformat()}", styles["Normal"]),
        Spacer(1, 8 * mm),
        Paragraph("Alcance", styles["Heading2"]),
        Paragraph(
            "Análisis histórico educativo. No es una recomendación personalizada "
            "ni una garantía de rendimiento futuro.",
            styles["Normal"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Parámetros", styles["Heading2"]),
        Paragraph(f"Activos válidos: {', '.join(tickers)}", styles["Normal"]),
        Paragraph(f"Periodo efectivo: {start_date.isoformat()} a {end_date.isoformat()}", styles["Normal"]),
        Spacer(1, 5 * mm),
    ]
    rows = [
        ["Métrica", "Estimación", "Importe"],
        ["Media histórica anualizada", f"{metrics.annual_return:.2%}", "—"],
        ["Volatilidad anualizada", f"{metrics.annual_volatility:.2%}", "—"],
        ["Sharpe histórico", f"{metrics.sharpe_ratio:.2f}", "—"],
        [
            f"VaR histórico ({risk.confidence_level:.1%})",
            f"{risk.historical_var:.2%}",
            f"{portfolio_value * risk.historical_var:,.2f}",
        ],
        ["CVaR histórico", f"{risk.historical_cvar:.2%}", f"{portfolio_value * risk.historical_cvar:,.2f}"],
    ]
    table = Table(rows, colWidths=[75 * mm, 40 * mm, 40 * mm])
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
            Spacer(1, 7 * mm),
            Paragraph("Metodología", styles["Heading2"]),
            Paragraph(
                "Precios ajustados, rendimientos aritméticos diarios y 252 sesiones por año. "
                "La optimización es long-only con límite de concentración. "
                "VaR y CVaR son magnitudes positivas "
                f"de pérdida para un horizonte de {risk.horizon_days} día(s).",
                styles["Normal"],
            ),
            Spacer(1, 4 * mm),
            Paragraph(
                "Limitaciones: no incluye costos, impuestos, liquidez, conversión de moneda, "
                "situación financiera del cliente ni cambios estructurales futuros.",
                styles["Normal"],
            ),
        ]
    )
    document.build(story)
    return buffer.getvalue()
