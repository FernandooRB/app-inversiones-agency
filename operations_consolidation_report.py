"""Screen/download projections of one immutable consolidation execution."""

import csv
from decimal import Decimal
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def money(value, base):
    return "Pendiente" if value is None else f"{Decimal(value):,.2f} {base}"


def report_text(report):
    lines = [
        "Patrimonio de libros revisados",
        f"Corte: {report['cutoff']} · Moneda: {report['base']}",
        "Patrimonio completo: " + money(report["nav"], report["base"]),
        "Subtotal documentado: " + money(report["known_subtotal"], report["base"]),
        report["notice"],
        "Estado: " + report["state"],
        "Ejecución: " + report["input_sha256"],
    ]
    for row in report["accounts"]:
        lines.extend(
            [
                row["alias"] + ": " + money(row["nav"], report["base"]),
                "Fuente: " + row["source"],
                "Corte SHA-256: " + row["cut_sha256"],
            ]
        )
    lines += [
        "Pendientes y alcance:",
        *report["issues"],
        "Transferencias internas no se restan del patrimonio. "
        "Los originales PDF/XML quedan fuera del paquete.",
        "Detalle completo en JSON/CSV y paquete de propuestas. Reabrir exige nueva confirmación.",
    ]
    return "\n".join(lines) + "\n"


def report_csv(report):
    stream = StringIO(newline="")
    writer = csv.writer(stream)

    def numeric(value):
        return Decimal(value) if value is not None else None

    def row(values):
        writer.writerow(
            [
                "'" + str(v) if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )

    row(
        [
            "Corte",
            report["cutoff"],
            "Moneda",
            report["base"],
            "Patrimonio completo",
            numeric(report["nav"]),
            "Subtotal documentado",
            numeric(report["known_subtotal"]),
        ]
    )
    row(["Cuenta", "Fuente de pertenencia", "Corte SHA-256", "Patrimonio", "Subtotal"])
    for account in report["accounts"]:
        row(
            [account[k] for k in ("alias", "source", "cut_sha256")]
            + [numeric(account[k]) for k in ("nav", "known_subtotal")]
        )
    row(
        [
            "Cuenta",
            "Sección",
            "Instrumento",
            "Moneda",
            "Valor nativo",
            "FX",
            "Fuente FX",
            "Valor base",
            "Peso",
        ]
    )
    for item in report["detail"]:
        row(
            [item[k] for k in ("account", "section", "instrument", "currency")]
            + [numeric(item[k]) for k in ("native", "rate")]
            + [item["fx_source"], numeric(item["value"]), numeric(item["weight"])]
        )
    row(["Cuenta", "ID", "Tipo", "Estado", "Fuente del vínculo", "Motivo"])
    for item in report["transfers"]:
        row([item[k] for k in ("account", "id", "kind", "state", "source", "reason")])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def report_pdf(report):
    """Two bounded pages; full untruncated evidence remains in data exports."""
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontSize=8, leading=11, textColor=colors.HexColor("#444444")))

    def p(value, style="BodyText", limit=240):
        value = str(value)
        if len(value) > limit:
            value = value[: limit - 1] + "…"
        return Paragraph(escape(value), styles[style])

    story = [
        p("Patrimonio de libros revisados", "Title"),
        p(f"Corte {report['cutoff']} · {report['base']} · {report['state']}"),
        Spacer(1, 5 * mm),
        p("Patrimonio completo: " + money(report["nav"], report["base"]), "Heading2"),
        p("Subtotal documentado: " + money(report["known_subtotal"], report["base"])),
        p(report["notice"]),
        Spacer(1, 5 * mm),
    ]
    rows = [[p("Cuenta"), p("Patrimonio"), p("Subtotal documentado")]]
    rows += [
        [
            p(a["alias"], "Small", 60),
            p(money(a["nav"], report["base"]), "Small"),
            p(money(a["known_subtotal"], report["base"]), "Small"),
        ]
        for a in report["accounts"]
    ]
    table = Table(rows, colWidths=[55 * mm, 57 * mm, 58 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 5 * mm),
        p(
            "Las transferencias no se restan del patrimonio. Una coincidencia no acredita contraparte. "
            "Se conservan cargos, diferencias y datos desconocidos."
        ),
        PageBreak(),
        p("Fuentes, revisión y pendientes", "Heading1"),
    ]
    for a in report["accounts"]:
        story += [
            p(a["alias"] + " · " + a["source"], "Small", 150),
            p("Corte SHA-256: " + a["cut_sha256"], "Small", 100),
        ]
    pending = sum(t["state"] == "PENDING" for t in report["transfers"])
    story += [
        Spacer(1, 3 * mm),
        p(f"Transferencias pendientes: {pending} de {len(report['transfers'])}.", "Small"),
    ]
    for item in report["issues"][:5]:
        story.append(p(item, "Small", 160))
    if len(report["issues"]) > 5:
        story.append(p(f"Otros {len(report['issues']) - 5} avisos en JSON/TXT.", "Small"))
    story += [
        p(
            "El subtotal sólo suma valores documentados; "
            "no equivale al patrimonio completo cuando hay faltantes. "
            "Las incidencias del libro de origen requieren cotejo. "
            "Originales fuera del ZIP; al reabrir se renuevan confirmaciones.",
            "Small",
        ),
        p("Ejecución SHA-256: " + report["input_sha256"], "Small", 100),
    ]
    SimpleDocTemplate(
        output,
        pagesize=(210 * mm, 297 * mm),
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="SIG · Patrimonio consolidado",
    ).build(story)
    return output.getvalue()
