"""Unapproved GBM movement proposals with immutable source rows and explicit corrections."""

import csv
import json
import re
import unicodedata
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from io import StringIO
from uuid import uuid4

from gbm_documents import read_statement
from portfolio_core import PortfolioError
from scripts.inspect_gbm_intake import IntakeError, _money_values, _trade_quantity
from transaction_ledger import COLUMNS, Event, book_at, decimal, read_ledger

MAX_DRAFT_BYTES = 2_000_000
MAX_ROWS = 20000
DOC_FIELDS = {
    "sha256",
    "contract",
    "start",
    "end",
    "opening_cash",
    "cash",
    "opening_total",
    "closing_total",
    "warnings",
    "positions",
}
ROW_FIELDS = {
    "manual",
    "id",
    "document",
    "page",
    "line",
    "text",
    "text_sha256",
    "control",
    "suggested",
    "proposal",
    "changes",
}


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.upper()) if unicodedata.category(c) != "Mn")


def _blank(identifier):
    return dict(
        zip(
            COLUMNS,
            (identifier, "", "", "", "", "MXN", "0", "0", "", "0", "0", "", "UNKNOWN", "0"),
            strict=True,
        )
    )


def propose_row(text, identifier, start, end):
    """Printed day pairs are proposals, never evidence of a flow's time of day."""
    row = _blank(identifier)
    upper = _fold(text)
    match = re.match(r"^(\d{2})/(\d{2})\s", text)
    if match:
        first, second = map(int, match.groups())
        days = [
            start + timedelta(days=n)
            for n in range(1, (end - start).days + 1)
            if (start + timedelta(days=n)).day == first
        ]
        if len(days) == 1:
            row["Fecha"] = days[0].isoformat()
            settlements = [
                days[0] + timedelta(days=n) for n in range(11) if (days[0] + timedelta(days=n)).day == second
            ]
            if len(settlements) == 1:
                row["Liquidacion"] = settlements[0].isoformat()
    amounts = _money_values(text)
    if len(amounts) not in {5, 6}:
        return row
    commission, interest, tax, net, _ = amounts[-5:]
    if min(commission, interest, tax, net) < 0:
        return row
    row.update(Comision=str(commission), Impuesto=str(tax))
    if "COMPRA" in upper and "VENTA" in upper:
        return row
    if "REPORTO" in upper:
        if "COMPRA" in upper:
            row.update(Tipo="REPO_START", Importe=str(net - commission - tax) if interest == 0 else "")
        elif "VENCIMIENTO" in upper or "VENTA" in upper:
            row.update(Tipo="REPO_MATURITY", Importe=str(net + commission + tax), Interes=str(interest))
        # References must be matched explicitly; a printed folio is not a repo pairing.
    elif "COMPRA" in upper or "VENTA" in upper:
        if interest != 0:
            return row
        try:
            quantity = _trade_quantity(text)
            price = decimal(text.split()[-6].replace(",", ""))
            gross = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            row.update(
                Tipo="BUY" if "COMPRA" in upper else "SELL",
                Instrumento=" ".join(text.split()[3:-7]),
                Cantidad=str(quantity),
                Precio=str(price),
                Importe=str(gross),
            )
        except (IntakeError, PortfolioError, IndexError):
            pass
    elif "DIVIDENDO" in upper and any(w in upper for w in ("RETENC", "ISR", "IMPUESTO")):
        row.update(Tipo="TAX", Importe=str(net - commission - tax))
    elif "DIVIDENDO" in upper:
        row.update(Tipo="DIVIDEND", Importe=str(net + commission + tax))
    elif "COMISION" in upper:
        row.update(Tipo="FEE", Importe=str(net - commission - tax))
    elif "INTERES" in upper:
        row.update(Tipo="INTEREST", Importe=str(net + commission + tax))
    elif "DEPOSITO" in upper and "RETIRO" not in upper:
        row.update(Tipo="TRANSFER_IN", Importe=str(net + commission + tax))
    elif "RETIRO" in upper and "DEPOSITO" not in upper:
        row.update(Tipo="TRANSFER_OUT", Importe=str(net - commission - tax))
    return row


def make_draft(statements):
    """Deduplicate exact documents; retain each subsequent opening as a control only."""
    unique = {item["sha256"]: item for item in statements}
    if not unique or len(unique) > 60:
        raise PortfolioError("Selecciona entre uno y 60 estados GBM.")
    documents = sorted(unique.values(), key=lambda item: (item["start"], item["end"], item["sha256"]))
    if len({item["contract"] for item in documents}) != 1:
        raise PortfolioError("Los estados pertenecen a contratos distintos. Revisa una cuenta a la vez.")
    draft = {"schema": 1, "kind": "sig.gbm.movements", "documents": [], "rows": [], "notes": []}
    for index, document in enumerate(documents):
        draft["documents"].append({key: deepcopy(document[key]) for key in DOC_FIELDS})
        start, end = date.fromisoformat(document["start"]), date.fromisoformat(document["end"])
        for cash in document["cash_review"]:
            identifier = cash["ID"]
            opening = cash["Sentido"] == "APERTURA"
            proposal = propose_row(cash["TextoOriginal"], identifier, start, end)
            if opening:
                proposal.update(
                    Fecha=start.isoformat(),
                    Liquidacion=start.isoformat(),
                    Tipo="OPEN_CASH",
                    Importe=document["opening_cash"],
                )
            draft["rows"].append(
                {
                    "id": identifier,
                    "manual": False,
                    "document": document["sha256"],
                    "page": cash["Pagina"],
                    "line": cash["Fila"],
                    "text": cash["TextoOriginal"],
                    "text_sha256": cash["TextoSHA256"],
                    "control": bool(opening and index > 0),
                    "suggested": deepcopy(proposal),
                    "proposal": proposal,
                    "changes": [],
                }
            )
        if index == 0:
            for position in document["positions"]:
                if decimal(position["CantidadAnterior"]) <= 0:
                    continue
                identifier = sha256(
                    f"{document['sha256']}:position:{position['Pagina']}:{position['Fila']}".encode()
                ).hexdigest()
                text = "Posición inicial · " + position["Instrumento"]
                proposal = _blank(identifier)
                proposal.update(
                    Fecha=start.isoformat(),
                    Liquidacion=start.isoformat(),
                    Tipo="OPEN_POSITION",
                    Instrumento=position["Instrumento"],
                    Cantidad=position["CantidadAnterior"],
                    Importe="0",
                )
                draft["rows"].append(
                    {
                        "id": identifier,
                        "manual": False,
                        "document": document["sha256"],
                        "page": position["Pagina"],
                        "line": position["Fila"],
                        "text": text,
                        "text_sha256": sha256(text.encode()).hexdigest(),
                        "control": False,
                        "suggested": deepcopy(proposal),
                        "proposal": proposal,
                        "changes": [],
                    }
                )
    validate_draft(draft)
    return draft


def read_movement_documents(documents):
    if (
        not isinstance(documents, list)
        or not 1 <= len(documents) <= 60
        or any(not isinstance(raw, bytes) for raw in documents)
        or sum(map(len, documents)) > 30_000_000
    ):
        raise PortfolioError("Selecciona hasta 60 PDF; el lote no puede superar 30 MB.")
    return make_draft([read_statement(raw, movement_review=True) for raw in documents])


def _safe_text(value, limit=10000):
    return isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 for c in value)


def validate_draft(draft):
    """Validate portable input as data; nothing in a ZIP restores approval or trust."""
    try:
        if (
            not isinstance(draft, dict)
            or set(draft) != {"schema", "kind", "documents", "rows", "notes"}
            or type(draft["schema"]) is not int
            or draft["schema"] != 1
            or draft["kind"] != "sig.gbm.movements"
            or not isinstance(draft["documents"], list)
            or not 1 <= len(draft["documents"]) <= 60
            or not isinstance(draft["rows"], list)
            or not 1 <= len(draft["rows"]) <= MAX_ROWS
            or not isinstance(draft["notes"], list)
            or len(draft["notes"]) > 1000
            or any(not _safe_text(note, 500) for note in draft["notes"])
        ):
            raise ValueError
        hashes, contracts = set(), set()
        for doc in draft["documents"]:
            if not isinstance(doc, dict) or set(doc) != DOC_FIELDS:
                raise ValueError
            digest = doc["sha256"]
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or digest in hashes:
                raise ValueError
            hashes.add(digest)
            if not _safe_text(doc["contract"], 160) or not doc["contract"].strip():
                raise ValueError
            contracts.add(doc["contract"])
            start, end = (date.fromisoformat(doc[key]) for key in ("start", "end"))
            if start >= end or end > date.today() or (end - start).days > 366:
                raise ValueError
            for key in ("opening_cash", "cash", "opening_total", "closing_total"):
                decimal(doc[key])
            if (
                not isinstance(doc["warnings"], list)
                or len(doc["warnings"]) > 100
                or any(not _safe_text(item, 500) for item in doc["warnings"])
                or not isinstance(doc["positions"], list)
                or len(doc["positions"]) > MAX_ROWS
            ):
                raise ValueError
        if len(contracts) != 1:
            raise ValueError
        ids = set()
        for row in draft["rows"]:
            if (
                not isinstance(row, dict)
                or set(row) != ROW_FIELDS
                or row["document"] not in hashes
                or not isinstance(row["id"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["id"])
                or row["id"] in ids
                or type(row["control"]) is not bool
                or type(row["manual"]) is not bool
                or any(type(row[k]) is not int or not 1 <= row[k] <= 100000 for k in ("page", "line"))
                or not _safe_text(row["text"])
                or sha256(row["text"].encode()).hexdigest() != row["text_sha256"]
            ):
                raise ValueError
            ids.add(row["id"])
            for key in ("proposal", "suggested"):
                proposal = row[key]
                if (
                    not isinstance(proposal, dict)
                    or set(proposal) != set(COLUMNS)
                    or proposal["ID"] != row["id"]
                    or any(not _safe_text(v, 160) for v in proposal.values())
                ):
                    raise ValueError
            if not isinstance(row["changes"], list) or len(row["changes"]) > 100:
                raise ValueError
            for change in row["changes"]:
                if (
                    not isinstance(change, dict)
                    or set(change) != {"at", "reason", "source", "before", "after"}
                    or not _safe_text(change["reason"], 500)
                    or not change["reason"].strip()
                    or not _safe_text(change["source"], 500)
                    or not change["source"].strip()
                    or datetime.fromisoformat(change["at"]).utcoffset() is None
                ):
                    raise ValueError
                for key in ("before", "after"):
                    if (
                        not isinstance(change[key], dict)
                        or set(change[key]) != set(COLUMNS)
                        or any(not _safe_text(v, 160) for v in change[key].values())
                    ):
                        raise ValueError
        if len(json.dumps(draft, ensure_ascii=False, allow_nan=False).encode()) > MAX_DRAFT_BYTES:
            raise ValueError
        return draft
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, PortfolioError):
        raise PortfolioError(
            "El borrador GBM no supera la comprobación de estructura y procedencia."
        ) from None


def correct_row(draft, identifier, proposal, *, reason, source):
    result = deepcopy(validate_draft(draft))
    row = next((item for item in result["rows"] if item["id"] == identifier), None)
    if row is None or row["control"]:
        raise PortfolioError("Selecciona un movimiento editable del borrador.")
    if not reason.strip() or not source.strip():
        raise PortfolioError("Indica motivo y fuente de la revisión.")
    if proposal != row["proposal"]:
        row["changes"].append(
            {
                "at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "source": source,
                "before": deepcopy(row["proposal"]),
                "after": deepcopy(proposal),
            }
        )
        row["proposal"] = deepcopy(proposal)
    validate_draft(result)
    return result


def ledger_bytes(rows):
    rows = list(rows)
    if any(
        row[key].lstrip().startswith(("=", "+", "-", "@"))
        for row in rows
        for key in ("ID", "Instrumento", "Referencia")
    ):
        raise PortfolioError("Los identificadores no admiten prefijos de fórmula de hoja de cálculo.")
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def original_rows_match(draft, originals):
    """Hashes identify files; re-extraction also prevents forged or omitted source rows in a ZIP."""
    expected = read_movement_documents(originals)
    keys = ("id", "document", "page", "line", "text", "text_sha256", "control", "suggested")
    return expected["documents"] == draft["documents"] and [
        {key: row[key] for key in keys} for row in expected["rows"]
    ] == [{key: row[key] for key in keys} for row in draft["rows"] if not row["manual"]]


def add_manual_row(draft, proposal, *, reason, source):
    result = deepcopy(validate_draft(draft))
    if not reason.strip() or not source.strip():
        raise PortfolioError("La entrada manual requiere motivo y fuente documental.")
    doc = min(result["documents"], key=lambda item: item["start"])
    identifier = sha256((doc["sha256"] + uuid4().hex).encode()).hexdigest()
    proposal = {**proposal, "ID": identifier}
    text = "Entrada manual respaldada · " + source
    result["rows"].append(
        {
            "id": identifier,
            "manual": True,
            "document": doc["sha256"],
            "page": 1,
            "line": 1,
            "text": text,
            "text_sha256": sha256(text.encode()).hexdigest(),
            "control": False,
            "suggested": deepcopy(proposal),
            "proposal": deepcopy(proposal),
            "changes": [
                {
                    "at": datetime.now(UTC).isoformat(),
                    "reason": reason,
                    "source": source,
                    "before": _blank(identifier),
                    "after": deepcopy(proposal),
                }
            ],
        }
    )
    validate_draft(result)
    return result


def proposal_event(proposal):
    if any(not proposal[k].strip() for k in ("Fecha", "Liquidacion", "Tipo", "Importe")):
        raise PortfolioError("Completa clasificación, fechas e importe bruto.")
    # Reuse the existing Decimal/event validation, including quantity, fees and reference checks.
    return read_ledger(ledger_bytes([proposal]))[0]


def draft_issues(draft):
    validate_draft(draft)
    issues = []
    documents = sorted(draft["documents"], key=lambda item: (item["start"], item["end"]))
    for previous, current in zip(documents, documents[1:], strict=False):
        if previous["end"] != current["start"]:
            issues.append({"id": current["sha256"], "reason": "Periodos solapados o discontinuos."})
        if decimal(previous["closing_total"]) != decimal(current["opening_total"]):
            issues.append({"id": current["sha256"], "reason": "El patrimonio no continúa entre estados."})
        if decimal(previous["cash"]) != decimal(current["opening_cash"]):
            issues.append({"id": current["sha256"], "reason": "El efectivo no continúa entre estados."})
    for row in draft["rows"]:
        if row["control"]:
            continue
        try:
            # Repo maturities need the whole sequence, not a standalone merge.
            proposal = row["proposal"]
            doc = next(item for item in documents if item["sha256"] == row["document"])
            suggested_kind = row["suggested"]["Tipo"]
            day = date.fromisoformat(proposal["Fecha"])
            if suggested_kind in {"OPEN_CASH", "OPEN_POSITION", "OPEN_REPO"}:
                if proposal["Tipo"] != suggested_kind or proposal["Fecha"] != documents[0]["start"]:
                    raise PortfolioError("La apertura debe conservar su tipo y fecha inicial.")
            elif not date.fromisoformat(doc["start"]) < day <= date.fromisoformat(doc["end"]):
                if not row["manual"] or not (
                    date.fromisoformat(documents[0]["start"])
                    < day
                    <= date.fromisoformat(documents[-1]["end"])
                ):
                    raise PortfolioError("La operación debe pertenecer al periodo de su estado.")
            elif proposal["Tipo"].startswith("OPEN_"):
                raise PortfolioError("La apertura se registra una sola vez al inicio del libro.")
            if proposal["Tipo"] == "REPO_MATURITY":
                if any(not proposal[k] for k in ("Fecha", "Liquidacion", "Referencia", "Importe", "Interes")):
                    raise PortfolioError("Completa fechas, referencia, bruto e interés del reporto.")
                Event(
                    proposal["ID"],
                    date.fromisoformat(proposal["Fecha"]),
                    date.fromisoformat(proposal["Liquidacion"]),
                    proposal["Tipo"],
                    proposal["Instrumento"],
                    proposal["Moneda"],
                    *(proposal[k] for k in ("Cantidad", "Precio", "Importe", "Comision", "Impuesto")),
                    proposal["Referencia"],
                    proposal["MomentoFlujo"],
                    proposal["Interes"],
                )
            else:
                proposal_event(proposal)
        except (PortfolioError, ValueError):
            issues.append(
                {
                    "id": row["id"],
                    "reason": "Revisa clasificación, fechas, instrumento, referencia e importes.",
                }
            )
    return issues


def materialize_draft(draft):
    if draft_issues(draft):
        raise PortfolioError(
            "El borrador conserva movimientos o periodos por resolver; puedes descargarlo y continuar."
        )
    raw = ledger_bytes([row["proposal"] for row in draft["rows"] if not row["control"]])
    events = read_ledger(raw)
    if sum(e.kind == "OPEN_CASH" for e in events) != 1:
        raise PortfolioError("El libro GBM requiere una sola apertura de efectivo.")
    openings = [(e.asset, e.currency) for e in events if e.kind == "OPEN_POSITION"]
    if len(set(openings)) != len(openings):
        raise PortfolioError("Revisa las posiciones iniciales duplicadas.")
    book_at(events, date.fromisoformat(max(doc["end"] for doc in draft["documents"])))
    return raw


def draft_controls(draft):
    """Closing balances are controls; never overwrite openings or fabricate adjustments."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Tipo", "InstrumentoReferencia", "Moneda", "Saldo", "Fuente"])
    last = max(draft["documents"], key=lambda doc: doc["end"])
    source = "Documento SHA-256 " + last["sha256"]
    writer.writerow([last["end"], "CASH", "", "MXN", last["cash"], source])
    mapping = {}
    for row in draft["rows"]:
        original, proposed = row["suggested"]["Instrumento"], row["proposal"]["Instrumento"]
        if original and proposed:
            mapping.setdefault(original, set()).add(proposed)
    for position in last["positions"]:
        symbols = mapping.get(position["Instrumento"], {position["Instrumento"]})
        if len(symbols) != 1:
            raise PortfolioError("La correspondencia de títulos del control requiere una revisión única.")
        if next(iter(symbols)).lstrip().startswith(("=", "+", "-", "@")):
            raise PortfolioError("El instrumento del control requiere una correspondencia segura.")
        writer.writerow([last["end"], "POSITION", next(iter(symbols)), "MXN", position["Cantidad"], source])
    return output.getvalue().encode()
