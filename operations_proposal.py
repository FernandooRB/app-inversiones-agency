"""Bounded portable proposals and reports. Saved results are historical, never consent."""

import base64
import csv
import json
import math
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from hashlib import sha256
from io import BytesIO, StringIO

from implementation_costs import ImplementationCostAssumptions, _validate_assumptions
from operations_comparison import validate_strategy
from portfolio_core import PortfolioError
from portfolio_exposure import _text

MAX_PROPOSAL_BYTES = 500_000
INPUT_FIELDS = {
    "currency",
    "date",
    "quote_source",
    "tariff_source",
    "tariff",
    "cash",
    "cash_floor",
    "max_turnover",
    "max_weight",
    "minimum_trade",
    "origin",
    "optimize",
    "book_origin",
    "target",
    "csv",
}
POSITION_FIELDS = {"Instrumento", "Cantidad", "Precio", "Lote", "PesoObjetivo"}
DETAIL_FIELDS = POSITION_FIELDS | {
    "Títulos a operar",
    "Importe firmado",
    "Comisión e IVA",
    "Costo de mercado",
    "Títulos finales",
    "Peso final sobre capital inicial",
}


def _number(value, low=0, high=1e15):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError
    return result


def _text_value(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or not _text(value.lstrip()):
        raise ValueError


def _close(left, right):
    if not math.isclose(float(left), float(right), abs_tol=1e-6, rel_tol=1e-10):
        raise ValueError


def proposal_positions(inputs):
    """Decode a bounded CSV, independently of pandas inference and spreadsheet formulas."""
    raw = base64.b64decode(inputs["csv"], validate=True)
    if not 0 < len(raw) <= 100_000:
        raise ValueError
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if set(fields) - POSITION_FIELDS - {"Clase"} or not POSITION_FIELDS.issubset(fields):
        raise ValueError
    if len(fields) != len(set(fields)):
        raise ValueError
    rows = []
    for row in reader:
        if len(rows) >= 25 or None in row or any(value is None for value in row.values()):
            raise ValueError
        _text_value(row["Instrumento"])
        if "Clase" in row:
            _text_value(row["Clase"])
        for field in ("Cantidad", "Precio", "Lote", "PesoObjetivo"):
            _number(row[field], high=1 if field == "PesoObjetivo" else 1e15)
        if float(row["Precio"]) <= 0 or float(row["Lote"]) <= 0:
            raise ValueError
        rows.append(row)
    if not rows or len({row["Instrumento"] for row in rows}) != len(rows):
        raise ValueError
    return rows


def validate_proposal(payload):
    """Validate structure, bounds and arithmetic without solving or importing approvals."""
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > MAX_PROPOSAL_BYTES:
            raise ValueError
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "kind", "inputs", "result"}
            or type(payload["schema"]) is not int
            or payload["schema"] not in {1, 2}
            or payload["kind"] != "sig.operations.proposal"
        ):
            raise ValueError
        inputs, result = payload["inputs"], payload["result"]
        if not isinstance(inputs, dict) or set(inputs) != INPUT_FIELDS | (
            {"strategy"} if payload["schema"] == 2 else set()
        ):
            raise ValueError
        if inputs["currency"] not in {"MXN", "USD"} or type(inputs["optimize"]) is not bool:
            raise ValueError
        if inputs["origin"] not in {"CSV manual", "Libro de movimientos"}:
            raise ValueError
        if (
            date.fromisoformat(inputs["date"]).isoformat() != inputs["date"]
            or date.fromisoformat(inputs["date"]) > date.today()
        ):
            raise ValueError
        for field in ("quote_source", "tariff_source"):
            _text_value(inputs[field])
        for field in ("cash", "cash_floor", "minimum_trade"):
            _number(inputs[field])
        if any(
            type(inputs[field]) not in (int, float)
            for field in ("cash", "cash_floor", "minimum_trade", "max_turnover", "max_weight")
        ):
            raise ValueError
        _number(inputs["max_turnover"], high=2)
        _number(inputs["max_weight"], low=0.01, high=1)
        if float(inputs["cash_floor"]) > float(inputs["cash"]):
            raise ValueError
        tariff = inputs["tariff"]
        if not isinstance(tariff, dict) or set(tariff) != set(asdict(ImplementationCostAssumptions())):
            raise ValueError
        for value in tariff.values():
            if type(value) not in (int, float):
                raise ValueError
            _number(value)
        costs = ImplementationCostAssumptions(**tariff)
        _validate_assumptions(costs)
        rows = proposal_positions(inputs)
        target = inputs["target"]
        if not isinstance(target, list) or len(target) != len(rows):
            raise ValueError
        if sum(_number(v, high=1) for v in target) > 1 + 1e-9:
            raise ValueError
        if payload["schema"] == 2:
            if inputs["optimize"]:
                raise ValueError
            validate_strategy(
                inputs["strategy"],
                [r["Instrumento"] for r in rows],
                inputs["date"],
                inputs["currency"],
                target,
            )
        origin = inputs["book_origin"]
        if inputs["origin"] == "Libro de movimientos":
            if not isinstance(origin, dict) or set(origin) != {
                "cash",
                "currency",
                "cutoff",
                "ledger_sha256",
                "quotes",
                "code_sha256",
            }:
                raise ValueError
            if origin["cutoff"] != inputs["date"] or origin["currency"] != inputs["currency"]:
                raise ValueError
            _close(origin["cash"], inputs["cash"])
            if (
                not isinstance(origin["ledger_sha256"], str)
                or len(bytes.fromhex(origin["ledger_sha256"])) != 32
            ):
                raise ValueError
            if not isinstance(origin["code_sha256"], dict) or not 1 <= len(origin["code_sha256"]) <= 16:
                raise ValueError
            for name, digest in origin["code_sha256"].items():
                _text_value(name)
                if not isinstance(digest, str) or len(bytes.fromhex(digest)) != 32:
                    raise ValueError
            if not isinstance(origin["quotes"], list) or len(origin["quotes"]) != len(rows):
                raise ValueError
            for row, quote in zip(rows, origin["quotes"], strict=True):
                if not isinstance(quote, dict) or set(quote) != {
                    "Instrumento",
                    "Fecha",
                    "Precio",
                    "Lote",
                    "PesoObjetivo",
                    "Fuente",
                }:
                    raise ValueError
                if quote["Instrumento"] != row["Instrumento"] or quote["Fecha"] != inputs["date"]:
                    raise ValueError
                _text_value(quote["Fuente"])
                for field in ("Precio", "Lote", "PesoObjetivo"):
                    _close(quote[field], row[field])
        elif origin is not None:
            raise ValueError
        if not isinstance(result, dict) or set(result) != {
            "detail",
            "cash",
            "cost",
            "turnover",
            "optimal",
            "basis",
        }:
            raise ValueError
        if type(result["optimal"]) is not bool:
            raise ValueError
        _text_value(result["basis"])
        detail = result["detail"]
        if not isinstance(detail, list) or len(detail) != len(rows):
            raise ValueError
        nav = float(inputs["cash"]) + sum(float(r["Cantidad"]) * float(r["Precio"]) for r in rows)
        if nav <= 0:
            raise ValueError
        signed_total, cost_total, traded = 0.0, 0.0, 0.0
        for index, (row, item) in enumerate(zip(rows, detail, strict=True)):
            if not isinstance(item, dict) or set(item) != DETAIL_FIELDS | (
                {"Clase"} if "Clase" in row else set()
            ):
                raise ValueError
            if item["Instrumento"] != row["Instrumento"] or (
                "Clase" in row and item["Clase"] != row["Clase"]
            ):
                raise ValueError
            for field in ("Cantidad", "Precio", "Lote"):
                _close(_number(item[field]), row[field])
            delta = _number(item["Títulos a operar"], low=-1e15)
            _close(delta / float(row["Lote"]), round(delta / float(row["Lote"])))
            notional = Decimal(str(abs(delta))) * Decimal(row["Precio"])
            notional = float(notional.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if notional and notional < float(inputs["minimum_trade"]) - 1e-5:
                raise ValueError
            signed = math.copysign(notional, delta) if delta else 0
            fee = (
                max(
                    Decimal(str(notional)) * Decimal(str(costs.commission_bps)) / Decimal(10000),
                    Decimal(str(costs.minimum_commission)),
                )
                if notional
                else Decimal(0)
            )
            fee = float(
                (fee * (Decimal(1) + Decimal(str(costs.vat_rate)))).quantize(
                    Decimal("0.01"), rounding=ROUND_CEILING
                )
            )
            market = float(
                (Decimal(str(notional)) * Decimal(str(costs.market_cost_bps)) / Decimal(10000)).quantize(
                    Decimal("0.01"), rounding=ROUND_CEILING
                )
            )
            final = float(row["Cantidad"]) + delta
            _close(item["Títulos finales"], final)
            if final < -1e-8 or final * float(row["Precio"]) > nav * float(inputs["max_weight"]) + 1e-5:
                raise ValueError
            for key, value in (
                ("PesoObjetivo", target[index]),
                ("Importe firmado", signed),
                ("Comisión e IVA", fee),
                ("Costo de mercado", market),
                ("Peso final sobre capital inicial", final * float(row["Precio"]) / nav),
            ):
                _close(item[key], value)
            signed_total += signed
            cost_total += fee + market
            traded += notional
        cash = float(inputs["cash"]) - signed_total - cost_total
        _close(_number(result["cash"]), cash)
        _close(_number(result["cost"]), cost_total)
        _close(_number(result["turnover"], high=2), traded / nav)
        if cash < float(inputs["cash_floor"]) - 1e-5 or traded / nav > float(inputs["max_turnover"]) + 1e-5:
            raise ValueError
        return deepcopy(payload)
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, csv.Error):
        raise PortfolioError("La propuesta guardada no supera la comprobación de formato y cifras.") from None


def portable_proposal(proposal):
    result = {**proposal["result"], "detail": proposal["result"]["detail"].to_dict("records")}
    return validate_proposal(
        {
            "schema": 2 if "strategy" in proposal["inputs"] else 1,
            "kind": "sig.operations.proposal",
            "inputs": proposal["inputs"],
            "result": result,
        }
    )


def reviewed_quote_defaults(raw, *, assets, cutoff, currency):
    """Only exact sourced quotes; prices do not establish lot sizes or target weights."""
    try:
        if not isinstance(raw, bytes) or len(raw) > 2_000_000:
            return {}
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        if not {"Fecha", "Instrumento", "Moneda", "Precio", "Fuente"}.issubset(reader.fieldnames or []):
            return {}
        result, seen = {}, set()
        for index, row in enumerate(reader):
            if index >= 20000:
                return {}
            if (
                row.get("Instrumento") not in assets
                or row.get("Moneda") != currency
                or row.get("Fecha") != str(cutoff)
            ):
                continue
            asset = row["Instrumento"]
            if asset in seen:
                result.pop(asset, None)
                continue
            seen.add(asset)
            try:
                _text_value(row["Fuente"])
                if _number(row["Precio"]) <= 0:
                    continue
            except (ValueError, TypeError):
                continue
            result[asset] = {"Precio": row["Precio"], "Fuente": row["Fuente"]}
        return result
    except (UnicodeError, csv.Error, TypeError):
        return {}


def proposal_pdf(payload, snapshot=None):
    """Two-page maximum, on demand; same validated execution as screen and CSV."""
    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    data = validate_proposal(payload)
    inputs, result = data["inputs"], data["result"]
    stream, styles = BytesIO(), getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontSize=8, leading=10))

    def p(value, style="Small"):
        return Paragraph(escape(str(value)), styles[style])

    story = [
        p("Propuesta de cartera", "Title"),
        p(f"Corte {inputs['date']} · {inputs['currency']} · {inputs['origin']}"),
        p("Estimación pendiente de revisión. Ninguna operación fue ejecutada."),
        Spacer(1, 4 * mm),
        p(f"Efectivo inicial: {inputs['cash']:,.2f} · Efectivo final: {result['cash']:,.2f}"),
        p(f"Cargos estimados: {result['cost']:,.2f} · Rotación: {result['turnover']:.2%}"),
        p(f"Reserva mínima: {inputs['cash_floor']:,.2f} · Concentración máxima: {inputs['max_weight']:.2%}"),
        Spacer(1, 3 * mm),
    ]
    rows = [[p(v) for v in ("Instrumento", "Actual", "Cambio", "Final", "Cargos")]]
    for row in result["detail"][:12]:
        rows.append(
            [
                p(row["Instrumento"][:50]),
                p(f"{float(row['Cantidad']):,.6g}"),
                p(f"{row['Títulos a operar']:+,.6g}"),
                p(f"{row['Títulos finales']:,.6g}"),
                p(f"{row['Comisión e IVA'] + row['Costo de mercado']:,.2f}"),
            ]
        )
    table = Table(rows, colWidths=[60 * mm, 25 * mm, 28 * mm, 28 * mm, 28 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.grey),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    if len(result["detail"]) > 12:
        story.append(p(f"Otros {len(result['detail']) - 12} instrumentos: CSV y ZIP de esta propuesta."))
    story += [
        PageBreak(),
        p("Fuentes, límites y pendientes", "Heading1"),
        p("Cotizaciones y lotes: " + inputs["quote_source"]),
        p("Tarifas y vigencia: " + inputs["tariff_source"]),
        p(
            f"Comisión {inputs['tariff']['commission_bps']:g} pb · "
            f"Mínimo {inputs['tariff']['minimum_commission']:g} · "
            f"IVA {inputs['tariff']['vat_rate']:.2%} · "
            f"Mercado {inputs['tariff']['market_cost_bps']:g} pb"
        ),
        p(result["basis"]),
        p(
            "La propuesta no modifica el rendimiento histórico ni acredita la aprobación del libro. "
            "El ZIP conserva insumos completos para revisar y recalcular."
        ),
    ]
    origin = inputs["book_origin"]
    strategy = inputs.get("strategy")
    if strategy:
        story += [
            p("Estrategia: " + strategy["name"][:80]),
            p(
                f"Historia {strategy['sample_start']} a {strategy['sample_end']} · "
                f"Ejecución {strategy['run_id'][:12]}"
            ),
            p(
                "Procedencia completa y huellas del análisis: ZIP. "
                "La estrategia conserva los pendientes de revisión de sus fuentes."
            ),
        ]
    if origin:
        story += [p("Libro SHA-256 " + origin["ledger_sha256"])]
        for row in origin["quotes"][:8]:
            story.append(p(f"{row['Instrumento'][:50]}: {row['Fuente'][:80]}"))
        if len(origin["quotes"]) > 8:
            story.append(p("Fuentes adicionales por instrumento: ZIP de la misma ejecución."))
    if snapshot:
        issues = snapshot.get("issues", [])
        story.append(p(f"Pendientes del libro: {len(issues)}"))
        for issue in issues[:3]:
            story.append(p(f"{issue['title'][:70]}: {issue['reason'][:120]}"))
    digest = sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 12 * mm, f"SIG · Propuesta {digest[:16]} · Página {doc.page}")

    SimpleDocTemplate(
        stream,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title="SIG · Propuesta de cartera",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
