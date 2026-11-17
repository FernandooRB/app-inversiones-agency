"""Bounded, data-only historical cuts and conservative documentary attribution.

Hashes check integrity, not authorship. Opening a cut never authorizes its use.
No historical TWR/XIRR subtraction, implicit FX or balancing entries.
"""

import json
from dataclasses import asdict, fields
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from operations_attribution import documented_amounts
from portfolio_core import PortfolioError
from transaction_ledger import Event, book_at, decimal, merge_events

MAX_BYTES = 2_000_000
ZERO = Decimal(0)
EXTERNAL = {"DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT", "ASSET_IN", "ASSET_OUT"}
PAYLOAD_FIELDS = {
    "case_id",
    "account_id",
    "cutoff",
    "base",
    "events",
    "valuation",
    "historical_result",
    "sources",
    "issues",
    "engine",
}


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _day(value):
    day = date.fromisoformat(value)
    if day.isoformat() != value or day > date.today():
        raise ValueError
    return day


def _text(value, limit=240):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError
    return value


def _events(payload):
    rows = payload["events"]
    if not isinstance(rows, list) or len(rows) > 20000:
        raise ValueError
    decoded = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {f.name for f in fields(Event)}:
            raise ValueError
        event = Event(**{**row, "day": _day(row["day"]), "settled": date.fromisoformat(row["settled"])})
        if event.day > _day(payload["cutoff"]) or event.settled.isoformat() != row["settled"]:
            raise ValueError
        decoded.append(event)
    merged = merge_events(decoded)
    if len(merged) != len(decoded) or list(merged) != decoded:
        raise ValueError
    return merged


def _values(payload):
    valuation = payload["valuation"]
    if valuation is None:
        return None
    if set(valuation) != {"nav", "detail", "base"} or valuation["base"] != payload["base"]:
        raise ValueError
    book = book_at(_events(payload), _day(payload["cutoff"]))
    expected = set(book["positions"])
    for section in ("cash", "pending"):
        expected.update((section, currency) for currency in book[section])
    expected.update(("Reporto · " + ref, currency) for ref, currency in book["repos"])
    rows = valuation["detail"]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError
    result, rates = {}, {}
    for row in rows:
        if set(row) != {"Instrumento", "Moneda", "ValorOrigen", "FX", "ValorBase"}:
            raise ValueError
        key = row["Instrumento"], row["Moneda"]
        if key not in expected or key in result:
            raise ValueError
        native, rate, value = (decimal(row[n]) for n in ("ValorOrigen", "FX", "ValorBase"))
        if rate <= 0 or native * rate != value or (key[1] == payload["base"] and rate != 1):
            raise ValueError
        if key[1] in rates and rates[key[1]] != rate:
            raise ValueError
        if key[0] in {"cash", "pending"}:
            if native != book[key[0]][key[1]]:
                raise ValueError
        elif native <= 0:
            raise ValueError
        rates[key[1]] = rate
        result[key] = (native, rate, value)
    if sum((row[2] for row in result.values()), ZERO) != decimal(valuation["nav"]):
        raise ValueError
    return result


def _validate(payload):
    if (
        not isinstance(payload, dict)
        or set(payload) != PAYLOAD_FIELDS
        or payload["base"] not in {"MXN", "USD"}
    ):
        raise ValueError
    _day(payload["cutoff"])
    if (payload["case_id"] is None) != (payload["account_id"] is None):
        raise ValueError
    for name in ("case_id", "account_id"):
        if payload[name] is not None and not _text(payload[name], 160):
            raise ValueError
    _events(payload)
    _values(payload)
    summary = payload["historical_result"]
    if summary is not None:
        if not isinstance(summary, dict) or set(summary) != {"start", "end", "gain", "twr", "xirr"}:
            raise ValueError
        if not _day(summary["start"]) <= _day(summary["end"]) <= _day(payload["cutoff"]):
            raise ValueError
        for name in ("gain", "twr", "xirr"):
            if summary[name] is not None:
                decimal(summary[name])
    for name, limit in (("sources", 7), ("engine", 10)):
        if not isinstance(payload[name], dict) or len(payload[name]) > limit:
            raise ValueError
        for key, value in payload[name].items():
            _text(key, 100)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError
    if not isinstance(payload["issues"], list) or len(payload["issues"]) > 1000:
        raise ValueError
    for row in payload["issues"]:
        if not isinstance(row, dict) or set(row) != {"id", "title", "state", "reason"}:
            raise ValueError
        for name, value in row.items():
            _text(value, 4000 if name == "reason" else 240)


def build_cut(
    events,
    *,
    cutoff,
    base,
    case_id=None,
    account_id=None,
    valuation=None,
    summary=None,
    sources=None,
    issues=(),
):
    """Take copies of normalized data. Sources contain hashes, never original documents."""
    payload = {
        "case_id": case_id,
        "account_id": account_id,
        "cutoff": cutoff,
        "base": base,
        "events": [asdict(e) for e in merge_events(events) if e.day.isoformat() <= cutoff],
        "valuation": valuation,
        "historical_result": {n: summary.get(n) for n in ("start", "end", "gain", "twr", "xirr")}
        if summary and summary.get("start") and summary.get("end") and summary.get("end") <= cutoff
        else None,
        "sources": sources or {},
        "issues": [{k: row[k] for k in ("id", "title", "state", "reason")} for row in issues],
        "engine": {
            name: sha256(Path(__file__).with_name(name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in (
                "operations_cuts.py",
                "operations_attribution.py",
                "transaction_ledger.py",
                "operations_report.py",
            )
        },
    }
    # Decimal/date serialisation is explicit data, with no Python module/class references.
    payload = json.loads(json.dumps(payload, default=str, allow_nan=False))
    envelope = {
        "schema": 1,
        "kind": "sig-operation-cut",
        "payload": payload,
        "sha256": sha256(_json(payload)).hexdigest(),
    }
    raw = _json(envelope)
    read_cut(raw)
    return raw


def read_cut(raw, *, case_id=None, account_id=None):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            raise ValueError
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if (
            set(envelope) != {"schema", "kind", "payload", "sha256"}
            or type(envelope["schema"]) is not int
            or envelope["schema"] != 1
            or envelope["kind"] != "sig-operation-cut"
        ):
            raise ValueError
        payload = envelope["payload"]
        if sha256(_json(payload)).hexdigest() != envelope["sha256"]:
            raise ValueError
        _validate(payload)
        if (case_id is not None or account_id is not None) and (
            payload["case_id"],
            payload["account_id"],
        ) != (case_id, account_id):
            raise ValueError
        return envelope
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError, PortfolioError):
        raise PortfolioError(
            "El corte no es válido: revisa formato, integridad, límites y cuenta. No se modificó la revisión."
        ) from None


def _balances(payload):
    book = book_at(_events(payload), _day(payload["cutoff"]))
    rows = {}
    for section in ("positions", "cash", "pending", "repos"):
        for key, value in book[section].items():
            item, currency = ("", key) if section in {"cash", "pending"} else key
            rows[(section, item, currency)] = value
    return rows


def cut_state(contents):
    """Validated data for local read-only checks; no saved consent is consumed."""
    cut = read_cut(contents if isinstance(contents, bytes) else _json(contents))
    payload = cut["payload"]
    events = _events(payload)
    return {
        "cut": cut,
        "events": events,
        "book": book_at(events, _day(payload["cutoff"])),
        "values": _values(payload),
    }


def _position_value(values, key):
    return values.get(key, (ZERO, None, ZERO))[0]


def compare_cuts(previous, current, *, confirmed=False):
    """Descriptive diffs always; monetary attribution only after fresh confirmation."""
    cuts = [read_cut(c if isinstance(c, bytes) else _json(c)) for c in (previous, current)]
    before, after = [c["payload"] for c in cuts]
    if (before["case_id"], before["account_id"], before["base"]) != (
        after["case_id"],
        after["account_id"],
        after["base"],
    ):
        raise PortfolioError("Compara cortes de la misma cuenta y moneda.")
    if before["cutoff"] > after["cutoff"]:
        raise PortfolioError("El corte anterior debe preceder al actual o tener la misma fecha.")
    balances = [_balances(c) for c in (before, after)]
    values = [_values(c) for c in (before, after)]
    navs = [decimal(c["valuation"]["nav"]) if c["valuation"] else None for c in (before, after)]
    rows = []
    for section, item, currency in sorted(set(balances[0]) | set(balances[1])):
        key = section, item, currency
        quantities = [b.get(key, ZERO) for b in balances]
        value_key = (
            item if section == "positions" else "Reporto · " + item if section == "repos" else section,
            currency,
        )
        row_values = [v.get(value_key, (ZERO, None, ZERO))[2] if v is not None else None for v in values]
        rows.append(
            {
                "section": section,
                "instrument": item,
                "currency": currency,
                "before": str(quantities[0]),
                "after": str(quantities[1]),
                "change": str(quantities[1] - quantities[0]),
                "weight_before": str(row_values[0] / navs[0])
                if row_values[0] is not None and navs[0] and navs[0] > 0
                else None,
                "weight_after": str(row_values[1] / navs[1])
                if row_values[1] is not None and navs[1] and navs[1] > 0
                else None,
            }
        )
    result = {
        "schema": 1,
        "mode": "version" if before["cutoff"] == after["cutoff"] else "period",
        "start": before["cutoff"],
        "end": after["cutoff"],
        "base": after["base"],
        "cut_ids": [c["sha256"] for c in cuts],
        "balances": rows,
        "historical_results": [c["historical_result"] for c in (before, after)],
        "issues_before": before["issues"],
        "issues_after": after["issues"],
        "source_changes": sorted(
            k
            for k in set(before["sources"]) | set(after["sources"])
            if before["sources"].get(k) != after["sources"].get(k)
        ),
        "wealth_change": str(navs[1] - navs[0]) if all(n is not None for n in navs) else None,
        **dict.fromkeys(
            (
                "gain",
                "contributions",
                "withdrawals",
                "price",
                "fx",
                "income",
                "fees",
                "tax",
                "repo",
                "unexplained",
            )
        ),
        "by_instrument": [],
        "documented": [],
        "pending": [],
    }
    if confirmed is not True:
        result["pending"].append(
            "Coteja ambos cortes, la cuenta y sus fuentes; confirma de nuevo para atribuir resultados."
        )
        return result
    if result["mode"] == "version":
        result["pending"].append(
            "Misma fecha: se comparan versiones; la diferencia no constituye rendimiento temporal."
        )
        return result
    history = [e for e in after["events"] if e["day"] <= before["cutoff"]]
    if history != before["events"]:
        result["pending"].append(
            "Cambió el historial previo; revisa las versiones antes de atribuir rendimiento."
        )
        return result
    events = [e for e in _events(after) if before["cutoff"] < e.day.isoformat() <= after["cutoff"]]
    result["documented"] = documented_amounts(events, before["cutoff"], after["cutoff"], base=after["base"])
    if any(e.kind.startswith("OPEN_") for e in events):
        result["pending"].append("Hay una apertura posterior al corte inicial; revisa continuidad y flujos.")
        return result
    external = [e for e in events if e.kind in EXTERNAL]
    if any(e.currency != after["base"] for e in external):
        result["pending"].append(
            "Falta FX fechado de flujos externos; no se atribuye ganancia en la moneda base."
        )
    else:
        contributions, withdrawals = ZERO, ZERO
        for event in external:
            amount = event.quantity * event.price if event.kind.startswith("ASSET_") else event.amount
            if event.kind in {"WITHDRAWAL", "TRANSFER_OUT", "ASSET_OUT"}:
                withdrawals += amount
            else:
                contributions += amount
        result.update(contributions=str(contributions), withdrawals=str(withdrawals))
        if result["wealth_change"] is not None:
            result["gain"] = str(decimal(result["wealth_change"]) - contributions + withdrawals)
    if any(v is None for v in values):
        result["pending"].append(
            "Falta una valuación completa y documentada de algún corte, incluidos reportos y FX."
        )
        return result
    base = after["base"]
    rates = [{c: row[1] for (_, c), row in v.items()} | {base: Decimal(1)} for v in values]
    active_foreign = {e.currency for e in events if e.currency != base and (e.cash or e.kind in EXTERNAL)}
    totals = dict.fromkeys(("price", "fx", "income", "fees", "tax", "repo"), ZERO)
    coverage = dict.fromkeys(totals, True)
    for name in ("income", "fees", "tax"):
        totals[name] = sum(
            (decimal(row[name]) for row in result["documented"] if row["currency"] == base), ZERO
        )
        if any(row["currency"] != base and decimal(row[name]) for row in result["documented"]):
            result["pending"].append("Ingresos o cargos en divisa sin FX fechado de la operación.")
            coverage[name] = False
    books = [book_at(_events(c), _day(c["cutoff"])) for c in (before, after)]
    securities = (
        set(books[0]["positions"])
        | set(books[1]["positions"])
        | {(e.asset, e.currency) for e in events if e.kind in {"BUY", "SELL", "ASSET_IN", "ASSET_OUT"}}
    )
    for key in sorted(securities):
        native = _position_value(values[1], key) - _position_value(values[0], key)
        for e in events:
            if (e.asset, e.currency) != key:
                continue
            if e.kind in {"BUY", "ASSET_IN"}:
                native -= e.quantity * e.price if e.kind == "ASSET_IN" else e.amount
            elif e.kind in {"SELL", "ASSET_OUT"}:
                native += e.quantity * e.price if e.kind == "ASSET_OUT" else e.amount
        currency = key[1]
        covered = currency not in active_foreign and currency in rates[0] and currency in rates[1]
        price = native * rates[1][currency] if covered else None
        if price is None:
            coverage["price"] = False
        else:
            totals["price"] += price
        result["by_instrument"].append(
            {
                "instrument": key[0],
                "currency": currency,
                "price_native": str(native),
                "price_base": str(price) if price is not None else None,
            }
        )
    for currency in set(rates[0]) | set(rates[1]):
        if currency == base:
            continue
        if currency in active_foreign or currency not in rates[0] or currency not in rates[1]:
            coverage["fx"] = False
            result["pending"].append(
                "FX pendiente: hubo movimientos en divisa o falta una tasa documentada de los cortes."
            )
        else:
            native_initial = sum((row[0] for (_, c), row in values[0].items() if c == currency), ZERO)
            totals["fx"] += native_initial * (rates[1][currency] - rates[0][currency])
    repo_keys = (
        set(books[0]["repos"])
        | set(books[1]["repos"])
        | {(e.reference, e.currency) for e in events if e.kind in {"REPO_START", "REPO_MATURITY"}}
    )
    for ref, currency in repo_keys:
        key = ("Reporto · " + ref, currency)
        native = _position_value(values[1], key) - _position_value(values[0], key)
        for e in events:
            if (e.reference, e.currency) == (ref, currency):
                if e.kind == "REPO_START":
                    native -= e.amount
                elif e.kind == "REPO_MATURITY":
                    native += e.amount - e.interest
        if currency in active_foreign or currency not in rates[1]:
            coverage["repo"] = False
        else:
            totals["repo"] += native * rates[1][currency]
    result["coverage"] = coverage
    result["known_components"] = {k: str(v) for k, v in totals.items()}
    result.update({k: str(v) if coverage[k] else None for k, v in totals.items()})
    if result["gain"] is not None:
        # Only subtract covered components. Unknown contributions remain in the residual.
        explained = sum((v for k, v in totals.items() if k not in {"fees", "tax"}), ZERO)
        explained -= totals["fees"] + totals["tax"]
        result["unexplained"] = str(decimal(result["gain"]) - explained)
    result["pending"] = list(dict.fromkeys(result["pending"]))
    return result
