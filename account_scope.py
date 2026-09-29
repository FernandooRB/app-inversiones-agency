"""Bind one analysis to one non-identifying account scope and its input files."""

import csv
import re
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import StringIO

from holdings import CurrentHoldings
from implementation_costs import OrderCostRule
from portfolio_core import PortfolioError

ACCOUNT_SCOPE_COLUMNS = (
    "AliasCuenta", "Intermediario", "PuntoPartida", "FechaCorte", "FechaRevision",
    "HuellaCarteraSHA256", "HuellaTarifasSHA256", "FuenteAlcance",
)


@dataclass(frozen=True)
class AccountScope:
    alias: str
    intermediary: str
    starting_point: str
    holdings_as_of: date | None
    reviewed_on: date
    holdings_fingerprint: str | None
    tariff_fingerprint: str
    source: str


def _text(value: str, label: str, maximum: int) -> str:
    value = value.strip()
    if (
        not value or len(value) > maximum or value[0] in "=+-@"
        or value.upper().startswith("EDITAR")
        or any(ord(character) < 32 for character in value)
    ):
        raise PortfolioError(f"{label} debe tener entre 1 y {maximum} caracteres válidos.")
    return value


def _date(value: str, label: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PortfolioError(f"{label} debe usar YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PortfolioError(f"{label} debe ser una fecha válida.") from exc


def read_account_scope_csv(
    contents: bytes,
    *,
    holdings_contents: bytes,
    tariff_contents: bytes,
    holdings: CurrentHoldings | None,
    order_rules: tuple[OrderCostRule, ...],
    as_of: date | None = None,
) -> AccountScope:
    """Verify declared single-account scope against exact holdings and tariff bytes.

    A matching digest prevents accidental file substitution; it cannot prove that
    the documents actually belong to one account or establish contract eligibility.
    """
    if not isinstance(contents, bytes) or not contents or len(contents) > 10_000:
        raise PortfolioError("El manifiesto de alcance debe ser un CSV de hasta 10 KB.")
    if not isinstance(tariff_contents, bytes) or not tariff_contents or not order_rules:
        raise PortfolioError("El alcance de cuenta requiere reglas de tarifas importadas.")
    if as_of is not None and type(as_of) is not date:
        raise PortfolioError("La fecha del análisis de cuenta no es válida.")
    analysis_date = as_of or date.today()
    try:
        records = list(csv.reader(StringIO(contents.decode("utf-8-sig")), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PortfolioError("No se pudo leer el manifiesto de alcance de cuenta.") from exc
    if len(records) != 2 or tuple(records[0]) != ACCOUNT_SCOPE_COLUMNS:
        raise PortfolioError("El alcance de cuenta requiere la plantilla exacta y una sola fila.")
    if len(records[1]) != len(ACCOUNT_SCOPE_COLUMNS):
        raise PortfolioError("La fila del alcance de cuenta está incompleta.")
    row = dict(zip(ACCOUNT_SCOPE_COLUMNS, records[1], strict=True))
    alias = _text(row["AliasCuenta"], "AliasCuenta", 60)
    intermediary = _text(row["Intermediario"], "Intermediario", 80)
    source = _text(row["FuenteAlcance"], "FuenteAlcance", 120)
    if any(re.search(r"\d{8,}|\S+@\S+", value) for value in (alias, source)):
        raise PortfolioError("El alias y la fuente no deben incluir cuentas ni correos personales.")
    if any(
        not isinstance(rule, OrderCostRule)
        or rule.intermediary.strip().casefold() != intermediary.casefold()
        for rule in order_rules
    ):
        raise PortfolioError("Las reglas por orden no pertenecen al intermediario declarado.")
    starting_point = row["PuntoPartida"].strip().upper()
    if starting_point not in {"CARTERA", "EFECTIVO"}:
        raise PortfolioError("PuntoPartida debe ser CARTERA o EFECTIVO.")
    reviewed_on = _date(row["FechaRevision"].strip(), "FechaRevision")
    if reviewed_on > analysis_date:
        raise PortfolioError("La revisión del alcance no puede ser posterior al análisis.")
    tariff_fingerprint = row["HuellaTarifasSHA256"].strip().lower()
    if (
        not re.fullmatch(r"[0-9a-f]{64}", tariff_fingerprint)
        or tariff_fingerprint != sha256(tariff_contents).hexdigest()
    ):
        raise PortfolioError("La huella de tarifas no coincide con el CSV cargado.")

    holdings_as_of = None
    holdings_fingerprint = None
    if starting_point == "CARTERA":
        if not isinstance(holdings, CurrentHoldings) or not holdings_contents:
            raise PortfolioError("El alcance CARTERA requiere una cartera valuada importada.")
        holdings_as_of = holdings.as_of.date()
        if row["FechaCorte"].strip() != holdings_as_of.isoformat():
            raise PortfolioError("FechaCorte no coincide con la cartera importada.")
        if reviewed_on < holdings_as_of:
            raise PortfolioError("La revisión del alcance precede al corte de la cartera.")
        holdings_fingerprint = row["HuellaCarteraSHA256"].strip().lower()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", holdings_fingerprint)
            or holdings_fingerprint != sha256(holdings_contents).hexdigest()
        ):
            raise PortfolioError("La huella de cartera no coincide con el CSV cargado.")
    elif (
        holdings is not None or holdings_contents
        or row["FechaCorte"].strip() or row["HuellaCarteraSHA256"].strip()
    ):
        raise PortfolioError("El alcance EFECTIVO no debe incluir cartera ni fecha de corte.")
    return AccountScope(
        alias, intermediary, starting_point, holdings_as_of, reviewed_on,
        holdings_fingerprint, tariff_fingerprint, source,
    )
