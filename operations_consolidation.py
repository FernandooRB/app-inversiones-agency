"""Read-only wealth from validated account cuts; no inferred counterparties or returns."""

import csv
import json
import re
from decimal import Decimal, localcontext
from hashlib import sha256
from io import StringIO
from pathlib import Path

import pandas as pd

from multi_currency_wealth import match_internal_flows
from operations_cuts import MAX_BYTES, cut_state
from portfolio_core import PortfolioError

MAX_ACCOUNTS = 10
MAX_INPUT_BYTES = 10_000_000
MAX_CSV_BYTES = 100_000
FX_COLUMNS = ("Fecha", "Moneda", "Base", "Tasa", "Fuente")
LINK_COLUMNS = ("CuentaSalida", "IDSalida", "CuentaEntrada", "IDEntrada", "Fuente")
ZERO = Decimal(0)
SOURCE_FILES = (
    "operations_consolidation.py",
    "operations_consolidation_bundle.py",
    "operations_consolidation_report.py",
    "operations_consolidation_ui.py",
    "operations_cuts.py",
    "transaction_ledger.py",
    "multi_currency_wealth.py",
)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def code_hashes():
    return {
        n: sha256(Path(__file__).with_name(n).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for n in SOURCE_FILES
    }


def text(value, limit=500):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise PortfolioError("Indica una fuente o referencia válida, sin controles y dentro del límite.")
    return value.strip()


def csv_rows(raw, columns):
    if not raw:
        return []
    try:
        if not isinstance(raw, bytes) or len(raw) > MAX_CSV_BYTES:
            raise ValueError
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig"), newline=""))
        if tuple(reader.fieldnames or ()) != tuple(columns):
            raise ValueError
        rows = list(reader)
        if len(rows) > 1000 or any(
            set(r) != set(columns) or any(v is None for v in r.values()) for r in rows
        ):
            raise ValueError
        return rows
    except (ValueError, UnicodeError, csv.Error):
        raise PortfolioError(
            "Revisa las columnas, codificación UTF-8 y límites del CSV de consolidación."
        ) from None


def prepare_accounts(entries, *, case_id=None, allowed_accounts=None):
    """All identity checks happen before a result or archive can be produced."""
    if not isinstance(entries, list) or not 2 <= len(entries) <= MAX_ACCOUNTS:
        raise PortfolioError("Carga entre dos y diez cortes de cuentas diferentes.")
    if any(not isinstance(e, dict) or not isinstance(e.get("cut"), bytes) for e in entries):
        raise PortfolioError("Cada cuenta requiere un corte JSON en bytes dentro de los límites.")
    if sum(len(e["cut"]) for e in entries) > MAX_INPUT_BYTES:
        raise PortfolioError("Los cortes superan el límite conjunto de 10 MB.")
    prepared, aliases, histories, accounts, days = [], set(), set(), set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"alias", "source", "cut"}:
            raise PortfolioError("Revisa el formato de cada cuenta de la consolidación.")
        alias = entry["alias"]
        if (
            not isinstance(alias, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,59}", alias)
            or alias.casefold() in aliases
        ):
            raise PortfolioError("Usa alias únicos de hasta 60 letras, números, guion o guion bajo.")
        aliases.add(alias.casefold())
        source = text(entry["source"])
        if not isinstance(entry["cut"], bytes) or len(entry["cut"]) > MAX_BYTES:
            raise PortfolioError("Cada corte JSON admite hasta 2 MB.")
        state = cut_state(entry["cut"])
        payload = state["cut"]["payload"]
        if case_id is None:
            valid_scope = payload["case_id"] is None and payload["account_id"] is None
        else:
            valid_scope = payload["case_id"] == case_id and payload["account_id"] in (
                allowed_accounts or set()
            )
        if not valid_scope:
            raise PortfolioError(
                "Los cortes deben pertenecer al expediente y a sus cuentas autorizadas; "
                "no mezcles revisiones temporales."
            )
        account_id = payload["account_id"]
        if account_id is not None:
            if account_id in accounts:
                raise PortfolioError("La misma cuenta aparece más de una vez.")
            accounts.add(account_id)
        # IDs and presentation labels do not make the same economic history a second account.
        history = sorted(
            canonical({k: v for k, v in e.items() if k != "id"}).decode() for e in payload["events"]
        )
        identity = sha256(canonical(history)).hexdigest()
        if identity in histories:
            raise PortfolioError(
                "Corte o libro repetido, incluso con otro alias. Revisa la pertenencia antes de consolidar."
            )
        histories.add(identity)
        days.add(payload["cutoff"])
        prepared.append(
            {**state, "alias": alias, "source": source, "cut_sha256": sha256(entry["cut"]).hexdigest()}
        )
    if len(days) != 1:
        raise PortfolioError(
            "Todas las cuentas requieren el mismo corte; no se propagan saldos entre fechas."
        )
    return prepared


def _rates(raw, cutoff, base):
    rates = {base: (Decimal(1), "Moneda base; sin conversión")}
    seen = set()
    for row in csv_rows(raw, FX_COLUMNS):
        currency = row["Moneda"]
        if (
            row["Fecha"] != cutoff
            or currency not in {"MXN", "USD"}
            or row["Base"] != base
            or currency in seen
        ):
            raise PortfolioError(
                "FX requiere fecha exacta del corte, moneda/base válidas y una sola tasa por moneda."
            )
        seen.add(currency)
        if not re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,15})?", row["Tasa"]):
            raise PortfolioError("La tasa FX debe ser positiva, finita y decimal, con hasta 15 decimales.")
        rate = Decimal(row["Tasa"])
        if not 0 < rate <= Decimal("1e15") or (currency == base and rate != 1):
            raise PortfolioError("Revisa la tasa FX; la moneda base sólo admite tasa uno.")
        rates[currency] = rate, text(row["Fuente"])
    return rates


def _amount(value):
    # Bound representations as well as magnitude; hostile tiny exponents cannot consume resources.
    if not value.is_finite() or (value and not -30 <= value.as_tuple().exponent <= 30):
        raise PortfolioError(
            "El corte contiene una precisión monetaria fuera de los límites de consolidación."
        )
    return value


def _transfers(prepared, raw, confirmed):
    events, rows = {}, []
    for state in prepared:
        for event in state["events"]:
            if event.kind in {"TRANSFER_IN", "TRANSFER_OUT", "ASSET_IN", "ASSET_OUT"}:
                events[state["alias"], event.id] = event
                rows.append(
                    {
                        "account": state["alias"],
                        "id": event.id,
                        "kind": event.kind,
                        "day": event.day.isoformat(),
                        "settled": event.settled.isoformat(),
                        "currency": event.currency,
                        "amount": str(event.amount),
                        "fee": str(event.fee),
                        "tax": str(event.tax),
                        "reference": event.reference,
                        "timing": event.timing,
                        "state": "PENDING",
                        "source": "",
                        "counterpart": None,
                        "candidate": False,
                        "reason": "Falta vinculación documentada entre cuentas.",
                    }
                )
    hints = [
        r
        for r in rows
        if r["kind"] in {"TRANSFER_IN", "TRANSFER_OUT"} and r["reference"] and Decimal(r["amount"]) > 0
    ]
    if hints:
        matched = match_internal_flows(
            pd.DataFrame(
                [
                    {
                        "Fecha": r["day"],
                        "Cuenta": r["account"],
                        "Tipo": r["kind"],
                        "Moneda": r["currency"],
                        "Importe": r["amount"],
                        "Referencia": r["reference"],
                    }
                    for r in hints
                ]
            )
        )
        # Existing matcher is a hint only. Its historical label is never treated as user evidence.
        for original, (_, hint) in zip(hints, matched.iterrows(), strict=True):
            original["candidate"] = hint["Estado"] == "INTERNA_VERIFICADA"
    by_key = {(r["account"], r["id"]): r for r in rows}
    used = set()
    for link in csv_rows(raw, LINK_COLUMNS):
        source = text(link["Fuente"])
        out_key, in_key = (link["CuentaSalida"], link["IDSalida"]), (link["CuentaEntrada"], link["IDEntrada"])
        if out_key in used or in_key in used or out_key == in_key:
            raise PortfolioError("Una pata de transferencia no puede utilizarse más de una vez.")
        used.update((out_key, in_key))
        if out_key[0] == in_key[0]:
            raise PortfolioError("La vinculación debe relacionar dos cuentas diferentes.")
        out, incoming = events.get(out_key), events.get(in_key)
        valid = (
            out is not None
            and incoming is not None
            and out.kind == "TRANSFER_OUT"
            and incoming.kind == "TRANSFER_IN"
            and out.amount == incoming.amount
            and out.amount > 0
            and out.currency == incoming.currency
            and out.day == incoming.day
            and out.settled == incoming.settled
        )
        for key, counterpart in ((out_key, in_key), (in_key, out_key)):
            if key in by_key:
                row = by_key[key]
                row.update(source=source, counterpart=list(counterpart))
                row["state"] = "DOCUMENTED_INTERNAL" if valid and confirmed else "PENDING"
                row["reason"] = (
                    "Pares e importes cotejados; cargos conservados en cada libro."
                    if valid and confirmed
                    else "Falta confirmar la revisión."
                    if valid
                    else "Patas ausentes o diferencias de tipo, importe, moneda o fechas; "
                    "conserva la incidencia."
                )
        if out is None or incoming is None:
            rows.append(
                {
                    "account": out_key[0],
                    "id": out_key[1],
                    "kind": "LINK",
                    "state": "PENDING",
                    "source": source,
                    "counterpart": list(in_key),
                    "candidate": False,
                    "reason": "La vinculación contiene una pata ausente; revisa cuentas e identificadores.",
                }
            )
    return rows


def consolidate_books(
    entries, *, base="MXN", fx=b"", links=b"", confirmed=False, case_id=None, allowed_accounts=None
):
    confirmed = confirmed is True
    if base not in {"MXN", "USD"}:
        raise PortfolioError("Selecciona MXN o USD como moneda base.")
    prepared = prepare_accounts(entries, case_id=case_id, allowed_accounts=allowed_accounts)
    cutoff = prepared[0]["cut"]["payload"]["cutoff"]
    rates = _rates(fx, cutoff, base)
    report = {
        "schema": 1,
        "kind": "sig.operations.consolidation.result",
        "cutoff": cutoff,
        "base": base,
        "case_id": case_id,
        "state": "REVIEWED" if confirmed else "PENDING_REVIEW",
        "nav": None,
        "known_subtotal": None,
        "accounts": [],
        "detail": [],
        "transfers": _transfers(prepared, links, confirmed),
        "issues": [],
        "engine": code_hashes(),
        "notice": "Patrimonio al corte. No es rendimiento global; no se suman TWR ni XIRR de cuentas.",
    }
    total, complete = ZERO, bool(confirmed)
    with localcontext() as ctx:
        ctx.prec = 100
        for state in prepared:
            payload, values, book = state["cut"]["payload"], state["values"], state["book"]
            subtotal, account_complete = ZERO, bool(confirmed)
            for section in ("positions", "cash", "pending", "repos"):
                for key, quantity in book[section].items():
                    asset, currency = (section, key) if section in {"cash", "pending"} else key
                    value_key = ("Reporto · " + asset if section == "repos" else asset, currency)
                    native = (
                        _amount(quantity)
                        if section in {"cash", "pending"}
                        else _amount(values[value_key][0])
                        if values is not None
                        else None
                    )
                    rate, source = rates.get(currency, (None, ""))
                    converted = (
                        native * rate if native is not None and rate is not None and confirmed else None
                    )
                    if converted is None:
                        account_complete = False
                    else:
                        subtotal += converted
                    report["detail"].append(
                        {
                            "account": state["alias"],
                            "section": section,
                            "instrument": asset,
                            "currency": currency,
                            "native": str(native) if native is not None else None,
                            "rate": str(rate) if rate is not None else None,
                            "fx_source": source,
                            "value": str(converted) if converted is not None else None,
                            "weight": None,
                        }
                    )
            if values is None:
                account_complete = False
            report["accounts"].append(
                {
                    "alias": state["alias"],
                    "account_id": payload["account_id"],
                    "source": state["source"],
                    "cut_sha256": state["cut_sha256"],
                    "cut_sources": payload["sources"],
                    "cut_issues": payload["issues"],
                    "nav": str(subtotal) if account_complete else None,
                    "known_subtotal": str(subtotal) if confirmed else None,
                    "historical_result": payload["historical_result"],
                    "original_base": payload["base"],
                }
            )
            total += subtotal
            complete &= account_complete
            if not account_complete:
                report["issues"].append(f"{state['alias']}: revisa confirmación, valuaciones y FX del corte.")
            if payload["issues"]:
                report["issues"].append(
                    f"{state['alias']}: conserva {len(payload['issues'])} incidencias del libro de origen."
                )
        report["known_subtotal"] = str(total) if confirmed else None
        report["nav"] = str(total) if complete else None
        if complete and total > 0:
            for row in report["detail"]:
                row["weight"] = str(Decimal(row["value"]) / total)
        elif complete:
            report["issues"].append("Patrimonio no positivo: pesos pendientes; revisa saldos y obligaciones.")
    if any(t["state"] == "PENDING" for t in report["transfers"]):
        report["issues"].append(
            "Hay transferencias sin vínculo acreditado; no se calcula rendimiento global."
        )
    report["input_sha256"] = sha256(
        canonical(
            {
                "entries": [
                    {"alias": e["alias"], "source": e["source"], "sha256": sha256(e["cut"]).hexdigest()}
                    for e in entries
                ],
                "base": base,
                "fx": sha256(fx).hexdigest(),
                "links": sha256(links).hexdigest(),
                "engine": report["engine"],
            }
        )
    ).hexdigest()
    return report
