"""Dated identity catalogue; issuer IDs survive changes to ticker or display name."""

from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError
from portfolio_exposure import ASSET_KINDS, _text

COLUMNS = (
    "Instrumento",
    "ISIN",
    "Mercado",
    "EmisorID",
    "Emisor",
    "Tipo",
    "Sector",
    "Pais",
    "Moneda",
    "Lote",
    "Fecha",
    "Fuente",
)


def read_catalogue(raw: bytes, *, cutoff=None):
    try:
        if not 0 < len(raw) <= 2_000_000:
            raise ValueError
        frame = pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False)
        if tuple(frame.columns) != COLUMNS or not 0 < len(frame) <= 10000:
            raise ValueError
        if not all(frame[key].map(_text).all() for key in COLUMNS if key != "Lote"):
            raise ValueError
        if (
            frame["Instrumento"].duplicated().any()
            or frame.duplicated(["ISIN", "Mercado"]).any()
            or not frame["ISIN"].str.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]").all()
            or not frame["EmisorID"].str.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{2,79}").all()
            or not set(frame["Tipo"]).issubset(ASSET_KINDS)
            or not set(frame["Moneda"]).issubset({"MXN", "USD"})
        ):
            raise ValueError
        # ISIN uses the ISO 6166 Luhn check digit after expanding letters.
        for isin in frame["ISIN"]:
            digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in isin)
            expanded = [int(c) * (2 if i % 2 else 1) for i, c in enumerate(reversed(digits))]
            if sum(value // 10 + value % 10 for value in expanded) % 10:
                raise ValueError
        frame["Lote"] = pd.to_numeric(frame["Lote"], errors="raise")
        dates = pd.to_datetime(frame["Fecha"], format="%Y-%m-%d", errors="raise")
        if (
            (dates.dt.date > (cutoff or date.today())).any()
            or not np.isfinite(frame["Lote"]).all()
            or (frame["Lote"] <= 0).any()
        ):
            raise ValueError
        return frame
    except (ValueError, TypeError, UnicodeError, pd.errors.ParserError):
        raise PortfolioError(
            "Catálogo inválido: verifica ISIN, mercado, emisor estable, lote, fecha y fuente."
        ) from None


def catalogue_changes(previous, current):
    before = previous.set_index("Instrumento")
    after = current.set_index("Instrumento")
    rows = []
    for asset in sorted(before.index.union(after.index)):
        if asset not in before.index:
            change = "Alta"
        elif asset not in after.index:
            change = "Baja"
        else:
            changed = [
                key for key in before.columns if str(before.loc[asset, key]) != str(after.loc[asset, key])
            ]
            if not changed:
                continue
            change = "Cambió: " + ", ".join(changed)
        rows.append({"Instrumento": asset, "Cambio": change})
    return pd.DataFrame(rows, columns=["Instrumento", "Cambio"])
