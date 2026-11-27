"""Compare market evidence without filling or updating account inputs."""

import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from unicodedata import normalize

from csv_mapping import read_source
from portfolio_core import PortfolioError

MARKET_COLUMNS = (
    "Tipo",
    "Fecha",
    "Serie",
    "Mercado",
    "Moneda",
    "Unidad",
    "Metodo",
    "Corte",
    "PlazoDias",
    "BaseDias",
    "Valor",
    "Proveedor",
    "Origen",
    "Evidencia",
)
TYPES = {"PRECIO": "Precio", "FX": "Tipo de cambio", "TASA": "Tasa"}
STATES = {
    "DIFERENCIA": "Fuera del umbral",
    "NO_COMPARABLE": "Convención u origen por revisar",
    "FALTA_REFERENCIA": "Falta referencia",
    "FALTA_PRINCIPAL": "Falta principal",
    "DENTRO": "Dentro del umbral",
    "IGUAL": "Igual",
}
COMPARE_FIELDS = ("Mercado", "Moneda", "Unidad", "Metodo", "PlazoDias", "BaseDias")
UNKNOWN_TEXT = {
    "",
    "?",
    "nd",
    "n/d",
    "n.a.",
    "na",
    "n/a",
    "null",
    "none",
    "s/d",
    "s/i",
    "sin dato",
    "sin datos",
    "sin evidencia",
    "no disponible",
    "desconocido",
    "desconocida",
    "pendiente",
    "por confirmar",
}
NUMBER = re.compile(r"-?[0-9]{1,12}(?:\.[0-9]{1,12})?", re.ASCII)
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-5][0-9])")


def fingerprint():
    return sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _normal(text):
    return " ".join(normalize("NFKC", text).casefold().split())


def _number(text):
    if not isinstance(text, str) or not NUMBER.fullmatch(text):
        raise ValueError
    return Decimal(text)


def _print(number):
    # Avoid scientific notation and extra trailing zeroes. Preserve exact input strings separately.
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _metadata(row, field):
    value = normalize("NFKC", row[field]).strip()
    if (
        _normal(value) in UNKNOWN_TEXT
        or value == "—"
        or len(value) > 200
        or value[0] in "=+-@"
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(field)


def _validate(row, now):
    for field in ("Serie", "Mercado", "Metodo", "Proveedor", "Origen", "Evidencia"):
        _metadata(row, field)
    if row["Serie"] != row["Serie"].strip():
        raise ValueError("Serie")
    kind = row["Tipo"]
    if kind not in TYPES:
        raise ValueError("Tipo")
    if row["Moneda"] not in {"MXN", "USD"}:
        raise ValueError("Moneda")
    unit = row["Unidad"]
    if kind == "PRECIO" and unit != "POR_TITULO":
        raise ValueError("Unidad")
    if kind == "FX" and (
        row["Serie"] != "USD/MXN" or unit != {"MXN": "MXN_POR_USD", "USD": "USD_POR_MXN"}[row["Moneda"]]
    ):
        raise ValueError("Serie o Unidad")
    if kind == "TASA":
        if unit != "PORCENTAJE_ANUAL":
            raise ValueError("Unidad")
        if not re.fullmatch(r"[1-9][0-9]{0,4}", row["PlazoDias"]):
            raise ValueError("PlazoDias")
        if row["BaseDias"] not in {"360", "365"}:
            raise ValueError("BaseDias")
    elif row["PlazoDias"] or row["BaseDias"]:
        raise ValueError("PlazoDias o BaseDias")
    try:
        day = date.fromisoformat(row["Fecha"])
        if day.isoformat() != row["Fecha"]:
            raise ValueError
    except ValueError:
        raise ValueError("Fecha") from None
    try:
        if not STAMP.fullmatch(row["Corte"]) or row["Corte"].endswith("-00:00"):
            raise ValueError
        stamp = datetime.fromisoformat(row["Corte"])
        if stamp.date() != day or stamp > now or abs(stamp.utcoffset()) > timedelta(hours=14):
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError("Corte") from None
    try:
        number = _number(row["Valor"])
        if (kind != "TASA" and number <= 0) or (kind == "TASA" and not -100 <= number <= 1000):
            raise ValueError
    except ValueError:
        raise ValueError("Valor") from None
    return stamp, number


def _read(raw, label, now):
    try:
        source = read_source(raw)
    except PortfolioError as error:
        raise PortfolioError(f"{label}: {error}") from None
    if tuple(source["headers"]) != MARKET_COLUMNS:
        raise PortfolioError(f"{label}: usa los encabezados de la plantilla de cotejo.")
    result = {}
    for record in source["rows"]:
        line = record["line_start"]
        original = record["original"]
        try:
            stamp, number = _validate(original, now)
        except ValueError as error:
            raise PortfolioError(f"{label}, fila {line}: revisa {error}.") from None
        key = original["Tipo"], original["Fecha"], original["Serie"]
        if key in result:
            raise PortfolioError(f"{label}, fila {line}: observación repetida para tipo, fecha y serie.")
        result[key] = (original, stamp, number, line)
    return result, source["sha256"]


def _differences(left, right):
    first, first_time, *_ = left
    second, second_time, *_ = right
    reasons = [key for key in COMPARE_FIELDS if first[key] != second[key]]
    if first_time != second_time:
        reasons.append("Corte")
    for field in ("Proveedor", "Origen", "Evidencia"):
        if _normal(first[field]) == _normal(second[field]):
            reasons.append(field)
    return reasons


def _compare_row(key, left, right, threshold):
    kind, day, _ = key
    row = {
        "type": kind,
        "date": day,
        "series": (left or right)[0]["Serie"],
        "primary": left[0] if left else None,
        "reference": right[0] if right else None,
        "primary_line": left[3] if left else None,
        "reference_line": right[3] if right else None,
        "delta": None,
        "bps": None,
        "reasons": [],
    }
    if left is None or right is None:
        return {**row, "state": "FALTA_PRINCIPAL" if left is None else "FALTA_REFERENCIA"}
    reasons = _differences(left, right)
    if reasons:
        return {**row, "state": "NO_COMPARABLE", "reasons": reasons}
    primary, reference = left[2], right[2]
    with localcontext() as ctx:
        ctx.prec = 70  # The reader bounds input to 24 decimal digits.
        delta = primary - reference
        numerator, denominator = (delta * 100, Decimal(1)) if kind == "TASA" else (delta * 10000, reference)
        outside = abs(numerator) > threshold * denominator
        bps = (numerator / denominator).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)
    state = "IGUAL" if not delta else "DIFERENCIA" if outside else "DENTRO"
    return {**row, "state": state, "delta": _print(delta), "bps": _print(bps) if bps else "0"}


def compare_observations(primary, reference, tolerances):
    """Join exact dates/series and calculate deltas only between comparable observations."""
    try:
        if not isinstance(tolerances, dict) or set(tolerances) != set(TYPES):
            raise ValueError
        thresholds = {kind: _number(text) for kind, text in tolerances.items()}
        if any(not 0 <= value <= 10000 for value in thresholds.values()):
            raise ValueError
    except ValueError:
        raise PortfolioError("Declara un umbral entre 0 y 10,000 puntos base para cada tipo.") from None
    now = datetime.now(UTC)
    left, left_hash = _read(primary, "Principal", now)
    right, right_hash = _read(reference, "Referencia", now)
    rows = [
        _compare_row(key, left.get(key), right.get(key), thresholds[key[0]])
        for key in sorted(left.keys() | right.keys())
    ]
    rank = {state: i for i, state in enumerate(STATES)}
    rows.sort(key=lambda row: rank[row["state"]])
    coverage = {kind: {"union": 0, "paired": 0, "comparable": 0} for kind in TYPES}
    for row in rows:
        counter = coverage[row["type"]]
        counter["union"] += 1
        counter["paired"] += row["primary"] is not None and row["reference"] is not None
        counter["comparable"] += row["delta"] is not None
    return {
        "schema": 1,
        "kind": "sig.market.comparison",
        "review_state": "PENDIENTE_COTEJO_HUMANO",
        "inputs": {"primary_sha256": left_hash, "reference_sha256": right_hash},
        "tolerances_bps": {kind: _print(value) for kind, value in thresholds.items()},
        "counts": dict(Counter(row["state"] for row in rows)),
        "coverage": coverage,
        "rows": rows,
    }
