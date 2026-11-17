"""One current-run explanation shared by screen and on-demand PDF."""

import json
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from operations_attribution import documented_amounts


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
        "by_instrument": [],
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
    summary["by_instrument"] = documented_amounts(events, summary["start"], summary["end"], base=base)
    if all(row["converted"] for row in summary["by_instrument"]):
        income, fees, tax = (
            sum(float(row[name]) for row in summary["by_instrument"]) for name in ("income", "fees", "tax")
        )
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
        ("unexplained", "Resto tras ingresos y cargos"),
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
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 5 * mm),
        p(
            "La ganancia separa la variación del patrimonio de las aportaciones y retiros. "
            "Los ingresos y cargos sólo se desglosan cuando la moneda del registro permite compararlos. "
            "El resto tras ingresos y cargos puede incluir precios, divisas y otras variaciones."
        ),
        p(
            "Las cifras pendientes requieren datos o confirmaciones. "
            "XIRR es anualizada; TWR corresponde al periodo. "
            "Los pendientes de conciliación y evidencia se conservan en la página siguiente."
        ),
    ]
    if comparison := snapshot.get("cut_comparison"):
        story += [
            p("Comparación de cortes", "Heading2"),
            p(f"{comparison['start']} a {comparison['end']} · {comparison['base']}", "Evidence"),
        ]
        for name, label in (
            ("wealth_change", "Cambio de patrimonio"),
            ("contributions", "Aportaciones"),
            ("withdrawals", "Retiros"),
            ("gain", "Ganancia monetaria"),
            ("price", "Precios"),
            ("income", "Ingresos documentados"),
            ("fees", "Comisiones y cargos"),
            ("tax", "Impuestos registrados"),
            ("fx", "Divisas"),
            ("repo", "Valuación de reportos"),
            ("unexplained", "Sin desglose"),
        ):
            value = comparison.get(name)
            story.append(
                p(
                    label
                    + ": "
                    + ("Pendiente" if value is None else f"{Decimal(value):,.2f} {comparison['base']}"),
                    "Evidence",
                )
            )
        component_labels = {
            "price": "Precios",
            "fx": "Divisas",
            "income": "Ingresos",
            "fees": "Cargos",
            "tax": "Impuestos",
            "repo": "Reportos",
        }
        partial = [
            f"{component_labels[name]}: {Decimal(value):,.2f}"
            for name, value in comparison.get("known_components", {}).items()
            if not comparison.get("coverage", {}).get(name, True)
        ]
        if partial:
            story.append(
                p("Subtotales documentados · " + comparison["base"] + ": " + "; ".join(partial), "Evidence")
            )
        story.append(
            p(
                f"{len(comparison['pending'])} pendientes de comparación. Detalle: CSV/TXT. "
                "El cambio de patrimonio incluye flujos; no equivale a rendimiento.",
                "Evidence",
            )
        )
    story += [PageBreak(), p("Pendientes y procedencia", "Heading1")]
    issues = snapshot.get("issues", [])
    policy = snapshot.get("policy_report")
    displayed_issues = 4 if policy else 8
    story.append(
        p(
            f"{len(issues)} pendientes. El ZIP conserva el borrador y los insumos; "
            "el TXT contiene el detalle de esta revisión."
        )
    )
    for item in issues[:displayed_issues]:
        story += [p(str(item["title"])[:100], "Heading3"), p(str(item["reason"])[:200], "Evidence")]
    if len(issues) > displayed_issues:
        story.append(
            p(
                f"Otros {len(issues) - displayed_issues} pendientes figuran en el resumen TXT "
                "de la misma revisión.",
                "Evidence",
            )
        )
    if policy:
        story += [
            p("Política de cartera", "Heading2"),
            p(
                f"Corte {policy['cutoff']} · {policy['counts']['deviations']} desvíos · "
                f"{policy['counts']['pending']} pendientes · Base {policy['basis']}",
                "Evidence",
            ),
        ]
        for item in sorted(policy["rows"], key=lambda r: r["state"] == "Dentro de límites")[:3]:
            observed = "Pendiente" if item["observed"] is None else f"{Decimal(item['observed']):.2%}"
            limit = "Pendiente" if item["limit"] is None else f"{Decimal(item['limit']) * 100:.2f}"
            label = {
                "drift": "Desvío de pesos",
                "max_weight": "Concentración individual",
                "cash": "Efectivo disponible",
            }[item["kind"]]
            unit = " pp" if item["kind"] == "drift" else "%"
            detail = f"Observado {observed} · Límite {limit}{unit}"
            if item["kind"] == "drift":
                target = "Pendiente" if item["target"] is None else f"{Decimal(item['target']):.2%}"
                difference = (
                    "Pendiente"
                    if item["difference"] is None
                    else f"{Decimal(item['difference']) * 100:.4f} pp"
                )
                detail += f" · Objetivo {target} · Diferencia {difference}"
            story += [
                p(f"{label} · {item['instrument'][:65]} · {item['state']}", "Evidence"),
                p(detail, "Evidence"),
                p(item["reason"][:140], "Evidence"),
            ]
        story.append(p("Fuente: " + policy["source"][:120] + " · " + policy["notice"], "Evidence"))
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
