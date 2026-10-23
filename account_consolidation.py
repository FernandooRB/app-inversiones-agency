"""MXN snapshot consolidation after individual account checks, without performance claims."""

import re
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from holdings import CurrentHoldings, read_current_holdings_csv
from holdings_control import HoldingsCoverageControl, read_holdings_coverage_csv
from instrument_identity import InstrumentIdentityProfile, read_instrument_identity_csv
from portfolio_core import PortfolioError


@dataclass(frozen=True)
class AccountSnapshot:
    alias: str
    holdings: CurrentHoldings
    coverage: HoldingsCoverageControl
    identity: InstrumentIdentityProfile
    fingerprints: dict[str, str]


def prepare_account_snapshot(alias, assets, files):
    if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,59}", alias):
        raise PortfolioError("Usa un alias neutro de cuenta, sin identificadores personales.")
    if set(files) != {"holdings", "coverage", "identity"}:
        raise PortfolioError("Cada cuenta requiere posiciones, cobertura e identidad.")
    holdings = read_current_holdings_csv(files["holdings"], assets)
    coverage = read_holdings_coverage_csv(files["coverage"], holdings)
    identity = read_instrument_identity_csv(files["identity"], assets, dict.fromkeys(assets, "MXN"))
    if identity.proxy_assets:
        raise PortfolioError("El consolidado inicial requiere identidades locales en MXN.")
    return AccountSnapshot(
        alias,
        holdings,
        coverage,
        identity,
        {role: sha256(value).hexdigest() for role, value in files.items()},
    )


def consolidate_snapshots(accounts: tuple[AccountSnapshot, ...]) -> dict:
    if len(accounts) < 2 or len({item.alias for item in accounts}) != len(accounts):
        raise PortfolioError("El consolidado requiere al menos dos cuentas distintas.")
    if len({item.holdings.as_of for item in accounts}) != 1:
        raise PortfolioError("Todas las cuentas deben tener el mismo corte.")
    if len({item.fingerprints["holdings"] for item in accounts}) != len(accounts):
        raise PortfolioError("Hay posiciones duplicadas; comprobar pertenencia antes de sumar.")
    positions, account_rows, symbols = {}, [], {}
    totals = dict.fromkeys(
        ("positions", "cash_outside", "pending_settlement", "other_outside", "total"), Decimal("0.00")
    )
    for item in accounts:
        amount = Decimal("0.00")
        identities = item.identity.detail.set_index("Instrumento")
        for ticker, value in item.holdings.values.items():
            money = Decimal(str(value))
            if money != money.quantize(Decimal("0.01")):
                raise PortfolioError("Las valuaciones del consolidado deben expresarse al centavo.")
            identity = identities.loc[ticker]
            key = (identity.ISIN, identity.MercadoNegociacion)
            if ticker in symbols and symbols[ticker] != key:
                raise PortfolioError("Una etiqueta de instrumento tiene identidades incompatibles.")
            symbols[ticker] = key
            entry = positions.setdefault(
                key,
                {
                    "isin": key[0],
                    "market": key[1],
                    "symbol": identity.SimboloNegociacion,
                    "value": Decimal("0.00"),
                },
            )
            if entry["symbol"] != identity.SimboloNegociacion:
                raise PortfolioError("La misma serie tiene símbolos de negociación incompatibles.")
            entry["value"] += money
            amount += money
        if amount != item.coverage.analyzed_value:
            raise PortfolioError("Las posiciones no coinciden con la cobertura declarada.")
        coverage = item.coverage
        row = {
            "positions": amount,
            "cash_outside": coverage.outside_cash,
            "pending_settlement": coverage.pending_settlement,
            "other_outside": coverage.other_outside,
            "total": coverage.account_total,
        }
        for key, value in row.items():
            totals[key] += value
        account_rows.append(
            {
                "alias": item.alias,
                **{key: str(value) for key, value in row.items()},
                "fingerprints": item.fingerprints,
            }
        )
    if sum(value for key, value in totals.items() if key != "total") != totals["total"]:
        raise PortfolioError("El consolidado no reconcilia con sus cuentas.")
    return {
        "as_of": accounts[0].holdings.as_of.date().isoformat(),
        "currency": "MXN",
        "client_delivery_allowed": False,
        "human_review_pending": True,
        "totals": {key: str(value) for key, value in totals.items()},
        "accounts": account_rows,
        "positions": [
            {
                **row,
                "value": str(row["value"]),
                "weight_in_analyzed_positions": str(row["value"] / totals["positions"]),
            }
            for row in positions.values()
        ],
        "limits": "Consolida valuaciones al corte, no rendimiento ni idoneidad. Efectivo externo "
        "se muestra separado. Tarifas, impuestos y optimización se revisan por cuenta; "
        "no se calcula un tramo de comisión con el patrimonio agregado.",
    }
