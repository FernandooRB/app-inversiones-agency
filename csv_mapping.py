"""Explicit, data-only CSV correspondence. Original bytes are never rewritten."""

import csv
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from portfolio_core import PortfolioError
from transaction_ledger import COLUMNS, KINDS, Event, book_at, read_ledger

MAX_SOURCE = 2_000_000
MAX_METADATA = 100_000
NUMBERS = {"Cantidad", "Precio", "Importe", "Comision", "Impuesto", "Interes"}
ENUMS = {"Tipo": KINDS, "Moneda": {"MXN", "USD"}, "MomentoFlujo": {"BOD", "EOD", "UNKNOWN"}}
CONFIG_KEYS = {
    "schema",
    "delimiter",
    "encoding",
    "date_format",
    "decimal",
    "thousands",
    "fields",
    "values",
    "basis",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _fail(message="La correspondencia CSV no cumple el formato permitido."):
    raise PortfolioError(message)


def _text(value, limit, *, empty=True):
    return (
        isinstance(value, str)
        and len(value) <= limit
        and (empty or bool(value.strip()))
        and not any(ord(c) < 32 for c in value)
    )


def read_source(raw, delimiter=",", encoding="utf-8-sig"):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE:
        _fail("El CSV está vacío o excede 2 MB.")
    if (
        not isinstance(delimiter, str)
        or not isinstance(encoding, str)
        or delimiter not in {",", ";", "\t"}
        or encoding not in {"utf-8-sig", "cp1252"}
    ):
        _fail()
    try:
        text = raw.decode(encoding)
        if "\0" in text:
            _fail("El CSV contiene caracteres no admitidos.")
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        headers = next(reader)
        if (
            not 1 <= len(headers) <= 40
            or any(not _text(h, 120, empty=False) for h in headers)
            or len({h.strip().casefold() for h in headers}) != len(headers)
        ):
            _fail("Los encabezados deben ser únicos, no vacíos y de hasta 120 caracteres.")
        rows = []
        end = reader.line_num
        for cells in reader:
            start = end + 1
            end = reader.line_num
            if len(rows) >= 20_000 or len(cells) != len(headers) or any(len(c) > 2000 for c in cells):
                _fail("El CSV tiene filas, columnas o celdas fuera de los límites.")
            rows.append(
                {
                    "row": len(rows) + 1,
                    "line_start": start,
                    "line_end": end,
                    "original": dict(zip(headers, cells, strict=True)),
                }
            )
        if not rows:
            _fail("El CSV no contiene movimientos.")
        return {"headers": headers, "rows": rows, "sha256": sha(raw), "size": len(raw)}
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise PortfolioError("No se pudo leer el CSV con la codificación y separador declarados.") from exc


def blank_mapping(headers):
    return {
        "schema": 1,
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "date_format": "ISO",
        "decimal": ".",
        "thousands": "",
        "fields": {f: {"mode": "missing", "value": "", "transform": "identity"} for f in COLUMNS},
        "values": {key: {} for key in ENUMS},
        "basis": "",
    }


def _config(config, headers):
    if (
        not isinstance(config, dict)
        or set(config) != CONFIG_KEYS
        or type(config["schema"]) is not int
        or config["schema"] != 1
    ):
        _fail()
    if not all(
        isinstance(config[k], str) for k in ("delimiter", "encoding", "date_format", "decimal", "thousands")
    ):
        _fail()
    if (
        config["delimiter"] not in {",", ";", "\t"}
        or config["encoding"] not in {"utf-8-sig", "cp1252"}
        or config["date_format"] not in {"ISO", "DMY", "MDY"}
        or config["decimal"] not in {".", ","}
        or config["thousands"] not in {"", ".", ",", " "}
        or config["decimal"] == config["thousands"]
        or not _text(config["basis"], 1000)
    ):
        _fail()
    fields, values = config["fields"], config["values"]
    if (
        not isinstance(fields, dict)
        or set(fields) != set(COLUMNS)
        or not isinstance(values, dict)
        or set(values) != set(ENUMS)
    ):
        _fail()
    for field, rule in fields.items():
        if not isinstance(rule, dict) or set(rule) != {"mode", "value", "transform"}:
            _fail()
        mode, value, transform = rule["mode"], rule["value"], rule["transform"]
        if (
            not isinstance(mode, str)
            or not isinstance(transform, str)
            or mode not in {"missing", "column", "constant", "row"}
            or not _text(value, 2000)
            or transform not in {"identity", "magnitude"}
            or (transform == "magnitude" and field not in {"Cantidad", "Importe", "Comision", "Impuesto"})
            or (mode == "row" and field != "ID")
            or (mode in {"row", "missing"} and value)
            or (mode == "column" and value not in headers)
        ):
            _fail()
    for field, rules in values.items():
        if not isinstance(rules, dict) or len(rules) > 100:
            _fail()
        for raw, canonical in rules.items():
            if (
                not _text(raw, 2000, empty=False)
                or not isinstance(canonical, str)
                or canonical not in ENUMS[field]
            ):
                _fail()
    _dump(config)


def _decisions(decisions, count):
    if not isinstance(decisions, dict) or len(decisions) > 100:
        _fail("Las decisiones exceden el formato o límite de 100 filas.")
    for key, decision in decisions.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[1-9][0-9]{0,4}", key)
            or int(key) > count
            or not isinstance(decision, dict)
            or set(decision) != {"action", "reason", "source"}
            or not isinstance(decision["action"], str)
            or decision["action"] not in {"include", "exclude"}
            or not _text(decision["reason"], 1000, empty=False)
            or not _text(decision["source"], 1000, empty=False)
        ):
            _fail("Cada decisión requiere fila válida, acción, motivo y fuente.")


def _number(text, config):
    point, group = config["decimal"], config["thousands"]
    integer = r"[0-9]+"
    if group:
        integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(group)}[0-9]{{3}})+)"
    if not re.fullmatch(rf"[+-]?{integer}(?:{re.escape(point)}[0-9]+)?", text):
        raise ValueError("Número vacío o incompatible con el formato decimal declarado.")
    value = Decimal((text.replace(group, "") if group else text).replace(point, "."))
    if not value.is_finite() or value.copy_abs() > Decimal("1e15"):
        raise ValueError("Número fuera de los límites del libro.")
    return value


def _cell(field, rule, row, config, source):
    if rule["mode"] == "missing":
        raise ValueError("Falta declarar una columna o un valor acreditado.")
    text = (row["original"][rule["value"]] if rule["mode"] == "column" else rule["value"]).strip()
    if rule["mode"] == "row":
        text = f"csv-{source['sha256'][:16]}-{row['row']}"
    if field in ENUMS:
        text = config["values"][field].get(text, text)
        if text not in ENUMS[field]:
            raise ValueError("Valor sin correspondencia explícita con los valores del libro.")
    elif field in {"Fecha", "Liquidacion"}:
        formats = {
            "ISO": (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "%Y-%m-%d"),
            "DMY": (r"[0-9]{2}/[0-9]{2}/[0-9]{4}", "%d/%m/%Y"),
            "MDY": (r"[0-9]{2}/[0-9]{2}/[0-9]{4}", "%m/%d/%Y"),
        }
        pattern, fmt = formats[config["date_format"]]
        if not re.fullmatch(pattern, text):
            raise ValueError("Fecha incompatible con el formato declarado.")
        text = datetime.strptime(text, fmt).date().isoformat()
    elif field in NUMBERS:
        number = _number(text, config)
        if rule["transform"] == "magnitude":
            number = number.copy_abs()
        text = format(number, "f")
    elif not _text(text, 160) or (text and text[0] in "=+-@"):
        raise ValueError(
            "Identificador no admitido o con apariencia de fórmula; conserva y revisa el original."
        )
    return text


def _project(raw, config, decisions, *, financial):
    if not isinstance(config, dict):
        _fail()
    source = read_source(raw, config.get("delimiter", ","), config.get("encoding", "utf-8-sig"))
    _config(config, source["headers"])
    _decisions(decisions, len(source["rows"]))
    issues, rows, included = [], [], []

    def issue(row, field, code, reason):
        issues.append({"row": row, "field": field, "code": code, "reason": reason})

    if financial and not config["basis"].strip():
        issue(0, "Fuente", "MISSING", "Declara fuente y motivo de la correspondencia.")
    for original in source["rows"]:
        row = deepcopy(original)
        decision = decisions.get(str(row["row"]), {})
        row["excluded"] = decision.get("action") == "exclude"
        mapped = {}
        if not row["excluded"]:
            for field, rule in config["fields"].items():
                try:
                    mapped[field] = _cell(field, rule, row, config, source)
                except (ValueError, InvalidOperation) as exc:
                    issue(row["row"], field, "MISSING_OR_INVALID", str(exc))
            if len(mapped) == len(COLUMNS):
                included.append(row)
                if financial:
                    try:
                        Event(
                            mapped["ID"],
                            date.fromisoformat(mapped["Fecha"]),
                            date.fromisoformat(mapped["Liquidacion"]),
                            mapped["Tipo"],
                            mapped["Instrumento"],
                            mapped["Moneda"],
                            *(
                                Decimal(mapped[k])
                                for k in ("Cantidad", "Precio", "Importe", "Comision", "Impuesto")
                            ),
                            mapped["Referencia"],
                            mapped["MomentoFlujo"],
                            Decimal(mapped["Interes"]),
                        )
                        if date.fromisoformat(mapped["Fecha"]) > date.today():
                            issue(
                                row["row"],
                                "Fecha",
                                "FUTURE",
                                "La operación tiene fecha futura; revisa el original.",
                            )
                    except PortfolioError as exc:
                        issue(row["row"], "Fila", "LEDGER", str(exc))
        row["mapped"] = mapped
        rows.append(row)
    if not included:
        issue(0, "Libro", "EMPTY", "No hay movimientos incluidos y completos.")
    if financial:
        ids = Counter(r["mapped"]["ID"] for r in included)

        def economic_key(row):
            return tuple(Decimal(row[f]) if f in NUMBERS else row[f] for f in COLUMNS if f != "ID")

        economic = Counter(economic_key(r["mapped"]) for r in included)
        for row in included:
            if ids[row["mapped"]["ID"]] > 1:
                issue(
                    row["row"],
                    "ID",
                    "DUPLICATE_ID",
                    "ID repetido; declara otro ID acreditado o excluye la fila.",
                )
            key = economic_key(row["mapped"])
            if economic[key] > 1 and decisions.get(str(row["row"]), {}).get("action") != "include":
                issue(
                    row["row"],
                    "Fila",
                    "DUPLICATE",
                    "Movimiento coincidente: documenta su inclusión o exclusión.",
                )
    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(row["mapped"] for row in included)
    candidate = (
        out.getvalue().encode("utf-8")
        if included and all(r["excluded"] or len(r["mapped"]) == len(COLUMNS) for r in rows)
        else None
    )
    if candidate and len(candidate) > MAX_SOURCE:
        issue(
            0,
            "Libro",
            "LIMIT",
            "El libro normalizado excede 2 MB; divide la fuente con periodos y aperturas acreditadas.",
        )
    if financial and candidate and not issues:
        try:
            events = read_ledger(candidate)
            book_at(events, max(e.day for e in events))
        except PortfolioError as exc:
            issue(0, "Libro", "LEDGER", str(exc))
    return {
        "source": source,
        "rows": rows,
        "issues": issues,
        "excluded": sum(r["excluded"] for r in rows),
        "normalized_candidate": candidate,
        "ready": not issues and bool(candidate),
        "ledger": candidate if not issues else None,
    }


def preview(raw, mapping, decisions):
    return _project(raw, mapping, decisions, financial=True)


def _dump(obj):
    raw = json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_METADATA:
        _fail("La correspondencia excede 100 KB.")
    return raw


def _load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("El JSON contiene claves repetidas.")
            result[key] = value
        return result

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_METADATA:
        _fail("El JSON está vacío o excede 100 KB.")
    try:
        obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: _fail())
        if not isinstance(obj, dict):
            _fail()
        return obj
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PortfolioError("No se pudo leer la correspondencia JSON.") from exc


def write_template(config, source):
    _config(config, source["headers"])
    return _dump(
        {
            "kind": "sig.csv.mapping",
            "schema": 1,
            "mapping": config,
            "headers": source["headers"],
            "last_source_sha256": source["sha256"],
            "review_state": "PENDING_REVIEW",
        }
    )


def read_template(blob, raw_source):
    obj = _load(blob)
    if (
        set(obj) != {"kind", "schema", "mapping", "headers", "last_source_sha256", "review_state"}
        or obj["kind"] != "sig.csv.mapping"
        or type(obj["schema"]) is not int
        or obj["schema"] != 1
        or obj["review_state"] != "PENDING_REVIEW"
        or not _hash(obj["last_source_sha256"])
    ):
        _fail()
    config = obj["mapping"]
    if not isinstance(config, dict):
        _fail()
    source = read_source(raw_source, config.get("delimiter", ","), config.get("encoding", "utf-8-sig"))
    if obj["headers"] != source["headers"]:
        _fail("Las columnas de la plantilla no corresponden al CSV actual.")
    _config(config, source["headers"])
    if source["sha256"] != obj["last_source_sha256"]:
        config["basis"] = ""
    return config


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _scope(scope):
    if not isinstance(scope, dict) or set(scope) != {"case_id", "account_id"}:
        _fail()
    values = list(scope.values())
    if values != [None, None] and not all(_text(v, 160, empty=False) for v in values):
        _fail("El origen CSV requiere expediente y cuenta coherentes.")


def pack_import(proposal):
    if not isinstance(proposal, dict) or set(proposal) != {
        "source",
        "mapping",
        "decisions",
        "scope",
        "applied_ledger_sha256",
    }:
        _fail()
    _scope(proposal["scope"])
    # Lexical projection only: reopening does not depend on current financial engine rules.
    result = _project(proposal["source"], proposal["mapping"], proposal["decisions"], financial=False)
    applied = proposal["applied_ledger_sha256"]
    if applied is not None and (
        not _hash(applied)
        or result["normalized_candidate"] is None
        or sha(result["normalized_candidate"]) != applied
    ):
        _fail("La procedencia CSV no reproduce el libro declarado.")
    obj = {k: v for k, v in proposal.items() if k != "source"}
    obj.update(
        {
            "kind": "sig.csv.import",
            "schema": 1,
            "source_sha256": sha(proposal["source"]),
            "review_state": "PENDING_REVIEW",
        }
    )
    return _dump(obj), proposal["source"]


def unpack_import(metadata, source, case_id=None, account_id=None):
    obj = _load(metadata)
    if (
        set(obj)
        != {
            "kind",
            "schema",
            "source_sha256",
            "review_state",
            "mapping",
            "decisions",
            "scope",
            "applied_ledger_sha256",
        }
        or obj["kind"] != "sig.csv.import"
        or type(obj["schema"]) is not int
        or obj["schema"] != 1
        or obj["review_state"] != "PENDING_REVIEW"
        or not isinstance(source, bytes)
        or obj["source_sha256"] != sha(source)
        or obj["scope"] != {"case_id": case_id, "account_id": account_id}
    ):
        _fail("El origen CSV no corresponde a su huella o cuenta.")
    result = {k: obj[k] for k in ("mapping", "decisions", "scope", "applied_ledger_sha256")}
    result["source"] = source
    pack_import(result)
    return result
