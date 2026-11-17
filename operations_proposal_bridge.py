"""Explicit, source-backed transfer from a ledger to an executable proposal, never orders."""

from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd

from portfolio_core import PortfolioError
from portfolio_exposure import _text
from transaction_ledger import book_at, decimal, read_ledger


def proposal_code_fingerprints():
    root = Path(__file__).resolve().parent
    return {
        name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in (
            "operations_proposal_bridge.py",
            "operations_proposal_ui.py",
            "executable_allocation.py",
            "implementation_costs.py",
        )
    }


def proposal_book(raw, cutoff, currency):
    if type(cutoff) is not date or cutoff > date.today() or currency not in {"MXN", "USD"}:
        raise PortfolioError("Selecciona un cierre y una moneda MXN/USD para la propuesta.")
    if not isinstance(raw, bytes):
        raise PortfolioError("Importa un libro normalizado válido antes de preparar una propuesta.")
    events = read_ledger(raw)
    book = book_at(events, cutoff)
    if any(event.day <= cutoff < event.settled for event in events):
        raise PortfolioError(
            "Hay liquidaciones pendientes. Revisa el cierre antes de preparar una propuesta."
        )
    if book["repos"]:
        raise PortfolioError("Hay reportos vigentes; su valor no es efectivo disponible para esta propuesta.")
    if any(amount and other != currency for other, amount in book["cash"].items()) or any(
        other != currency for _, other in book["positions"]
    ):
        raise PortfolioError(
            "Esta conexión requiere una sola moneda; no convierte saldos ni títulos con FX supuesto."
        )
    if book["cash"].get(currency, decimal(0)) < 0:
        raise PortfolioError(
            "El libro tiene efectivo negativo; revisa el saldo antes de preparar una propuesta."
        )
    return book


def proposal_inputs(raw, *, cutoff, currency, market_rows, confirmed=False):
    if confirmed is not True:
        raise PortfolioError(
            "Coteja el libro, los precios, los lotes y los pesos antes de preparar la propuesta."
        )
    book = proposal_book(raw, cutoff, currency)
    required = {"Instrumento", "Fecha", "Precio", "Lote", "PesoObjetivo", "Fuente"}
    if not isinstance(market_rows, list) or not 1 <= len(market_rows) <= 25:
        raise PortfolioError("Completa de uno a 25 instrumentos para la propuesta.")
    rows, quotes, assets = [], [], set()
    target_total = decimal(0)
    for entry in market_rows:
        if (
            not isinstance(entry, dict)
            or set(entry) != required
            or any(
                not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value)
                for value in entry.values()
            )
        ):
            raise PortfolioError("Completa los datos de cada instrumento con su fecha y fuente.")
        asset = entry["Instrumento"]
        if not _text(asset) or asset != asset.strip() or asset in assets:
            raise PortfolioError(
                "Cada instrumento requiere una etiqueta segura y única, sin espacios exteriores."
            )
        if entry["Fecha"] != cutoff.isoformat():
            raise PortfolioError("Las cotizaciones deben corresponder exactamente al cierre elegido.")
        source = entry["Fuente"].strip()
        if not source or source.startswith(("=", "+", "-", "@")):
            raise PortfolioError("Cada cotización y lote requiere una fuente verificable.")
        price, lot, weight = (decimal(entry[key]) for key in ("Precio", "Lote", "PesoObjetivo"))
        if price <= 0 or lot <= 0 or not 0 <= weight <= 1:
            raise PortfolioError("Declara precio y lote positivos y pesos entre 0 y 1.")
        target_total += weight
        assets.add(asset)
        rows.append(
            {
                "Instrumento": asset,
                "Cantidad": str(book["positions"].get((asset, currency), decimal(0))),
                "Precio": str(price),
                "Lote": str(lot),
                "PesoObjetivo": str(weight),
            }
        )
        quotes.append(dict(entry))
    # Calculated float targets can serialize just above one (e.g. 1 + 9e-17).
    # Keep every supplied weight and money amount unchanged; tolerate only this
    # numeric noise in the dimensionless objective, never in cash or quantities.
    if target_total > 1 + decimal("0.000000000001"):
        raise PortfolioError("Los pesos objetivo no pueden sumar más de 1; el resto corresponde al efectivo.")
    if {asset for asset, _ in book["positions"]} - assets:
        raise PortfolioError(
            "Incluye todos los títulos del libro, también los que tengan peso objetivo cero."
        )
    return {
        "positions": pd.DataFrame(rows),
        "cash": str(book["cash"].get(currency, decimal(0))),
        "currency": currency,
        "cutoff": cutoff.isoformat(),
        "ledger_sha256": sha256(raw).hexdigest(),
        "quotes": quotes,
        "code_sha256": proposal_code_fingerprints(),
    }
