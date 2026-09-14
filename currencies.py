"""Explicit quote currencies and historical FX conversion, without filling gaps."""

import numpy as np

from portfolio_core import PortfolioError, download_adjusted_prices

SUPPORTED = {"USD", "MXN", "EUR", "GBP", "CAD", "JPY", "CHF"}


def currency_map(tickers, text):
    if any(value.strip() in {"GBp", "GBX", "ZAc"} for value in text.split(",")):
        raise PortfolioError("Las cotizaciones en subunidades no están soportadas.")
    values = [value.strip().upper() for value in text.split(",")]
    if len(values) != len(tickers) or any(value not in SUPPORTED for value in values):
        raise PortfolioError("Indica una moneda por ticker: USD, MXN, EUR, GBP, CAD, JPY o CHF.")
    return dict(zip(tickers, values, strict=True))


def convert_prices(prices, quotes, base, rates):
    if base not in SUPPORTED or set(prices.columns) - set(quotes):
        raise PortfolioError("Moneda base o monedas de cotización incompletas.")
    converted = prices.copy()
    for ticker in prices:
        quote = quotes[ticker]
        if quote not in SUPPORTED:
            raise PortfolioError("Moneda de cotización no soportada.")
        if quote == base:
            continue
        pair = f"{quote}{base}=X"
        if pair not in rates:
            raise PortfolioError(f"Falta la serie cambiaria {pair}.")
        fx = rates[pair].reindex(prices.index)
        if (fx.dropna() <= 0).any() or not np.isfinite(fx.dropna()).all():
            raise PortfolioError("Serie cambiaria inválida.")
        converted[ticker] = prices[ticker] * fx
    return converted.dropna(how="any")


def download_fx(quotes, base, start, end):
    pairs = sorted({f"{quote}{base}=X" for quote in quotes.values() if quote != base})
    if not pairs:
        return {}
    result = download_adjusted_prices(pairs, start, end)
    if result.rejected_tickers:
        raise PortfolioError("No se pudieron descargar todas las divisas requeridas.")
    return {pair: result.prices[pair] for pair in pairs}
