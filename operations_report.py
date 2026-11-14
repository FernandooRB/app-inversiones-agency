"""One current-run explanation shared by screen and on-demand PDF."""

import json
from hashlib import sha256
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def explain_performance(events, nav, result, flows, *, base):
    summary = {
        "base": base,
        "start": None,
        "end": None,
        "initial": None,
        "final": None,
        "contributions": None,
        "withdrawals": None,
        "gain": None,
        "twr": None,
        "xirr": None,
        "income": None,
        "fees": None,
        "tax": None,
        "unexplained": None,
        "state": "Borrador: faltan datos o confirmaciones",
    }
    if nav is not None:
        summary.update(
            start=nav.index[0].date().isoformat(),
            end=nav.index[-1].date().isoformat(),
            initial=float(nav.iloc[0]),
            final=float(nav.iloc[-1]),
        )
    if result is None:
        return summary
    summary.update(
        contributions=sum(max(flow.amount, 0) for flow in flows),
        withdrawals=-sum(min(flow.amount, 0) for flow in flows),
        gain=result["gain"],
        twr=result["twr"],
        xirr=result["xirr"],
        state="Cálculo con insumos confirmados; revisa los pendientes",
    )
    period = [e for e in events if summary["start"] < e.settled.isoformat() <= summary["end"]]
    if all(e.currency == base for e in period):
        income = sum(float(e.amount) for e in period if e.kind in {"DIVIDEND", "COUPON", "INTEREST"})
        income += sum(float(e.interest) for e in period if e.kind == "REPO_MATURITY")
        fees = sum(float(e.fee) for e in period) + sum(float(e.amount) for e in period if e.kind == "FEE")
        tax = sum(float(e.tax) for e in period) + sum(float(e.amount) for e in period if e.kind == "TAX")
        summary.update(income=income, fees=fees, tax=tax, unexplained=result["gain"] - income + fees + tax)
    return summary


def summary_lines(summary):
    currency = summary["base"]
    labels = (
        ("initial", "Patrimonio inicial"),
        ("final", "Patrimonio final"),
        ("contributions", "Aportaciones"),
        ("withdrawals", "Retiros"),
        ("gain", "Ganancia monetaria"),
        ("income", "Ingresos documentados"),
        ("fees", "Comisiones y cargos"),
        ("tax", "Impuestos registrados"),
        ("unexplained", "Variación no desglosada"),
    )
    rows = [
        [
            label,
            "Pendiente"
            if summary[key] is None
            else f"{0.0 if round(summary[key], 2) == 0 else summary[key]:,.2f} {currency}",
        ]
        for key, label in labels
    ]
    rows += [
        [
            label,
            "Pendiente"
            if summary[key] is None
            else f"{0.0 if round(summary[key] * 100, 2) == 0 else summary[key]:.2%}",
        ]
        for key, label in (("twr", "Rendimiento del periodo · TWR"), ("xirr", "XIRR anualizada"))
    ]
    return rows


def performance_pdf(snapshot):
    """Render bounded content from the same snapshot, without executing financial models."""
    summary = snapshot.get("performance_summary") or explain_performance(
        [], None, None, [], base=snapshot.get("base") or "MXN"
    )
    stream = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Evidence", fontSize=8, leading=11, textColor=colors.HexColor("#4b4d4f")))
    styles.add(ParagraphStyle(name="Money", parent=styles["BodyText"], alignment=2))

    def p(value, style="BodyText"):
        return Paragraph(escape(str(value)), styles[style])

    story = [
        p(("DEMO · " if snapshot.get("demo") else "") + "Cuánto gané y por qué", "Title"),
        p(str(snapshot.get("scope", "Sesión temporal"))[:240]),
        p(
            f"Periodo: {summary['start'] or 'Pendiente'} a {summary['end'] or 'Pendiente'} · "
            f"Moneda: {summary['base']}"
        ),
        p(summary["state"]),
        Spacer(1, 6 * mm),
    ]
    table = Table(
        [[p(label), p(value, "Money")] for label, value in summary_lines(summary)],
        colWidths=[110 * mm, 60 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#dddddd")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 5 * mm),
        p(
            "La ganancia separa la variación del patrimonio de las aportaciones y retiros. "
            "Los ingresos y cargos sólo se desglosan cuando la moneda del registro permite compararlos. "
            "La variación no desglosada conserva lo que aún no se ha atribuido."
        ),
        p(
            "Las cifras pendientes requieren datos o confirmaciones. "
            "XIRR es anualizada; TWR corresponde al periodo. "
            "Los pendientes de conciliación y evidencia se conservan en la página siguiente."
        ),
        PageBreak(),
        p("Pendientes y procedencia", "Heading1"),
    ]
    issues = snapshot.get("issues", [])
    story.append(
        p(
            f"{len(issues)} pendientes. El ZIP conserva el borrador y los insumos; "
            "el TXT contiene el detalle de esta revisión."
        )
    )
    for item in issues[:8]:
        story += [p(str(item["title"])[:100], "Heading3"), p(str(item["reason"])[:200], "Evidence")]
    if len(issues) > 8:
        story.append(
            p(
                f"Otros {len(issues) - 8} pendientes figuran en el resumen TXT de la misma revisión.",
                "Evidence",
            )
        )
    story += [Spacer(1, 3 * mm), p("Fuentes de esta ejecución", "Heading2")]
    for source in list(snapshot.get("inputs", {}).values())[:7]:
        story.append(p(f"{source['label']} · SHA-256 {source['sha256'][:20]}…", "Evidence"))
    story.append(
        p(
            "Huellas completas e incidencias: resumen TXT. Para continuar: paquete ZIP. "
            "Aprobación humana y cotejo independiente: pendientes.",
            "Evidence",
        )
    )
    digest = sha256(
        json.dumps(snapshot, sort_keys=True, default=str, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 12 * mm, f"SIG · Revisión {digest[:16]} · Página {doc.page}")

    SimpleDocTemplate(
        stream,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title="SIG · Rendimiento explicado",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
