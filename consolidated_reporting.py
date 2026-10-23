"""Readable internal statement of a reconciled MXN valuation consolidation."""

from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from portfolio_core import PortfolioError


def create_consolidation_pdf(result: dict) -> bytes:
    if result.get("currency") != "MXN" or result.get("client_delivery_allowed") is not False:
        raise PortfolioError("Este informe sólo admite un consolidado interno MXN.")
    accounts = result["accounts"]
    totals = result["totals"]
    fields = ("positions", "cash_outside", "pending_settlement", "other_outside", "total")
    if any(sum(Decimal(row[field]) for row in accounts) != Decimal(totals[field]) for field in fields):
        raise PortfolioError("Los totales del informe no concilian con las cuentas.")
    if sum(Decimal(row["value"]) for row in result["positions"]) != Decimal(totals["positions"]):
        raise PortfolioError("Las posiciones del informe no concilian con su subtotal.")
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=17 * mm,
    )
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 17
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 12
    styles["Heading2"].fontSize = 12

    numeric_style = styles["Normal"].clone("Numeric", alignment=2)

    def table(rows, widths, numeric_from):
        cells = [
            [
                Paragraph(escape(str(cell)), numeric_style if index >= numeric_from else styles["Normal"])
                for index, cell in enumerate(row)
            ]
            for row in rows
        ]
        item = Table(cells, colWidths=widths, repeatRows=1)
        item.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#D1D5DB")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return item

    story = [
        Paragraph("Stochastics Investment Group", styles["Title"]),
        Paragraph("Consolidado de posiciones | Revisión interna", styles["Heading2"]),
        Paragraph(
            "No autorizado para entrega a clientes. Corte: " + escape(result["as_of"]), styles["Normal"]
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            f"Total declarado: <b>{Decimal(totals['total']):,.2f} MXN</b>. "
            f"Posiciones analizadas: {Decimal(totals['positions']):,.2f} MXN. "
            f"Efectivo fuera del análisis: {Decimal(totals['cash_outside']):,.2f} MXN.",
            styles["Normal"],
        ),
        Paragraph("Desglose por cuenta", styles["Heading2"]),
        table(
            [["Cuenta", "Posiciones MXN", "Efectivo externo", "Por liquidar", "Otras partidas", "Total MXN"]]
            + [[row["alias"], *[f"{Decimal(row[field]):,.2f}" for field in fields]] for row in accounts],
            [59 * mm] + [38 * mm] * 5,
            1,
        ),
        Spacer(1, 3 * mm),
        Paragraph("Posiciones agregadas por identidad y mercado", styles["Heading2"]),
        table(
            [["Símbolo", "ISIN", "Mercado", "Valor MXN", "Peso en posiciones"]]
            + [
                [
                    row["symbol"],
                    row["isin"],
                    row["market"],
                    f"{Decimal(row['value']):,.2f}",
                    f"{Decimal(row['weight_in_analyzed_positions']):.2%}",
                ]
                for row in result["positions"]
            ],
            [45 * mm, 65 * mm, 35 * mm, 55 * mm, 49 * mm],
            3,
        ),
        Spacer(1, 3 * mm),
        Paragraph("Alcance y revisión", styles["Heading2"]),
        Paragraph(escape(result["limits"]), styles["Normal"]),
        Paragraph(
            "La pertenencia de cada archivo a una cuenta, su corte e identidad requieren "
            "cotejo humano. Las huellas completas y el desglose se conservan en el JSON "
            "del paquete. Este informe no reconstruye rendimientos ni formula una asignación.",
            styles["Normal"],
        ),
    ]

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, 9 * mm, "Consolidado de valuaciones | Uso interno")
        canvas.drawRightString(264 * mm, 9 * mm, f"Página {doc.page}")

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
