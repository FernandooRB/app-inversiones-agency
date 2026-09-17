from datetime import date, timedelta

import pandas as pd
import pytest

from holdings import read_current_holdings_csv
from portfolio_core import PortfolioError


def test_holdings_are_reordered_and_normalized_to_weights():
    contents = (
        b"FechaCorte,Instrumento,ValorMXN\n"
        b"2026-01-15,BBB,30000\n"
        b"2026-01-15,AAA,60000\n"
        b"2026-01-15,LIQUIDEZ,10000\n"
    )
    result = read_current_holdings_csv(contents, ("AAA", "BBB", "LIQUIDEZ"))
    assert result.values.index.tolist() == ["AAA", "BBB", "LIQUIDEZ"]
    assert result.weights.tolist() == pytest.approx([0.6, 0.3, 0.1])
    assert result.total_value == pytest.approx(100_000)
    assert result.as_of == pd.Timestamp("2026-01-15")


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("2026-01-15,AAA,100\n", "faltan: BBB"),
        ("2026-01-15,AAA,100\n2026-01-15,BBB,100\n2026-01-15,CCC,1\n", "sobran: CCC"),
        ("2026-01-15,AAA,100\n2026-01-15,AAA,100\n", "una sola vez"),
        ("2026-01-15,AAA,-1\n2026-01-15,BBB,100\n", "no negativos"),
        ("2026-01-15,AAA,0\n2026-01-15,BBB,0\n", "total.*positivo"),
        ("2026-01-15,AAA,100\n2026-01-16,BBB,100\n", "una sola fecha"),
    ],
)
def test_holdings_reject_invalid_reconciliation(rows, message):
    contents = ("FechaCorte,Instrumento,ValorMXN\n" + rows).encode()
    with pytest.raises(PortfolioError, match=message):
        read_current_holdings_csv(contents, ("AAA", "BBB"))


def test_holdings_allow_zero_value_for_an_asset_in_the_analysis():
    contents = (
        b"FechaCorte,Instrumento,ValorMXN\n"
        b"2026-01-15,AAA,100\n"
        b"2026-01-15,BBB,0\n"
    )
    result = read_current_holdings_csv(contents, ("AAA", "BBB"))
    assert result.weights.tolist() == pytest.approx([1.0, 0.0])


def test_holdings_reject_extra_columns_to_avoid_importing_client_identifiers():
    contents = (
        b"FechaCorte,Instrumento,ValorMXN,Cuenta\n"
        b"2026-01-15,AAA,100,123456\n"
    )
    with pytest.raises(PortfolioError, match="únicamente"):
        read_current_holdings_csv(contents, ("AAA",))


def test_holdings_reject_future_cutoff_date():
    future = (date.today() + timedelta(days=1)).isoformat()
    contents = f"FechaCorte,Instrumento,ValorMXN\n{future},AAA,100\n".encode()
    with pytest.raises(PortfolioError, match="futuro"):
        read_current_holdings_csv(contents, ("AAA",))
