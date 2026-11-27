"""Independent fictional cash and valuation cases for the MXN adapters."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from fixed_income import prepare_cetes_total_return, read_banxico_cetes_csv, read_bond_total_return_csv
from funds import prepare_fund_total_return
from liquidity import prepare_liquidity_accrual
from portfolio_core import PortfolioError
from transaction_ledger import Event, book_at, value_book


def test_cetes_loss_recovery_and_redemption_over_a_weekend():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    quotes = pd.DataFrame({"p": [9.98, 9.96, 10.0, 9.90], "d": [4, 1, 0, 28]}, index=dates)
    result = prepare_cetes_total_return(quotes, price_column="p", term_column="d")
    # A MXN 998 position in 100 certificates falls to 996 and redeems at 1,000.
    assert result.index.tolist() == pytest.approx([100, 99600 / 998, 100000 / 998, 100000 / 998])
    assert result.roll_dates == (dates[-1],)
    assert result.maturity_dates == (dates[-2],)


@pytest.mark.parametrize(
    ("prices", "terms", "message"),
    [
        ([9.98, 9.99, 9.99], [2, 1, 0], "valor nominal al vencimiento"),
        ([9.98, 9.99, 10], [25.00001, 24.00001, 23.00001], "días enteros"),
        ([9.98, 9.99, 10], [float("inf")] * 3, "días enteros"),
        ([9.98, 9.99, 10], [1e22] * 3, "días enteros"),
    ],
)
def test_cetes_rejects_inconsistent_settlement_or_term(prices, terms, message):
    quotes = pd.DataFrame(
        {"p": prices, "d": terms}, index=pd.date_range("2026-01-05", periods=3)
    )
    with pytest.raises(PortfolioError, match=message):
        prepare_cetes_total_return(quotes, price_column="p", term_column="d")


def test_cetes_crosscheck_uses_the_declared_nominal_value():
    csv = (
        b"Fecha,Precio,Plazo,Tasa\n2026-01-05,19.9004975,10,18\n"
        b"2026-01-06,19.9104032,9,18\n2026-01-07,19.9203187,8,18\n"
    )
    result = read_banxico_cetes_csv(
        csv, date_column="Fecha", price_column="Precio", term_column="Plazo", nominal_value=20,
    )
    assert result.prices.iloc[0] == 19.9004975


BOND_MATURITY = (
    b"Fecha,Emision,Vencimiento,PrecioLimpio,InteresDevengado,Cupon,Amortizacion\n"
    b"2026-01-05,SIM-1,2026-01-08,97,2,0,0\n"
    b"2026-01-06,SIM-1,2026-01-08,98,2.50,0,0\n"
    b"2026-01-07,SIM-1,2026-01-08,97,2.75,0,0\n"
    b"2026-01-08,SIM-1,2026-01-08,0,0,3,100\n"
)


def test_bond_maturity_returns_principal_and_coupon_once_and_retains_each_input():
    result = read_bond_total_return_csv(BOND_MATURITY)
    # Bought for 99, marked first at 100.50 then at 99.75, redeemed for 103 in cash.
    assert result.index.tolist() == pytest.approx([100, 10050 / 99, 9975 / 99, 10300 / 99])
    assert result.dirty_prices.iloc[-1] == 0
    assert result.coupons.iloc[-1] == 3
    assert result.amortizations.iloc[-1] == 100


@pytest.mark.parametrize(
    ("csv", "message"),
    [
        (
            b"\n".join(line.rsplit(b",", 1)[0] for line in BOND_MATURITY.splitlines())
            .replace(b",0,0,3", b",100,0,3"),
            "Amortizacion",
        ),
        (BOND_MATURITY.replace(b",0,0,3,100", b",0,0,3,99.99"), "valor nominal"),
        (BOND_MATURITY.replace(b",0,0,3,100", b",100,0,3,100"), "precio limpio"),
        (BOND_MATURITY.replace(b",97,2,0,0", b",97,2,0,1"), "antes del vencimiento"),
        (BOND_MATURITY.replace(b",97,2,0,0", b",97,2,0.000000001,0"), "primera observación"),
    ],
)
def test_bond_maturity_rejects_missing_or_double_counted_cash(csv, message):
    with pytest.raises(PortfolioError, match=message):
        read_bond_total_return_csv(csv)


def test_bond_cannot_use_one_column_as_both_coupon_and_principal():
    legacy = b"\n".join(line.rsplit(b",", 1)[0] for line in BOND_MATURITY.splitlines())
    with pytest.raises(PortfolioError, match="columnas distintas"):
        read_bond_total_return_csv(legacy, amortization_column="Cupon")


@pytest.mark.parametrize("preamble", [b"", b" \n\t\n"])
def test_bond_rejects_ambiguous_amortization_headers(preamble):
    lines = BOND_MATURITY.splitlines()
    ambiguous = [lines[0] + b",Amortizacion", *(row + b",0" for row in lines[1:-1]), lines[-1] + b",99.99"]
    with pytest.raises(PortfolioError, match="columnas duplicadas"):
        read_bond_total_return_csv(preamble + b"\n".join(ambiguous))


def fund(prices, distributions, dates=None):
    quotes = pd.DataFrame(
        {"nav": prices, "cash": distributions},
        index=dates if dates is not None else pd.date_range("2026-01-05", periods=3),
    )
    return prepare_fund_total_return(
        quotes, share_value_column="nav", distribution_column="cash",
        fund_id="SIM", series_id="A", currency="MXN",
    )


def test_fund_distribution_and_market_loss_are_both_reflected():
    result = fund([10, 8, 9], [0, 1, 0])
    # 100 units become 112.5 after reinvesting 100 at 8, worth 1,012.50 at 9.
    assert result.index.tolist() == pytest.approx([100, 90, 101.25])


def test_fund_cannot_discard_a_small_opening_distribution():
    with pytest.raises(PortfolioError, match="primera observación"):
        fund([10, 8, 9], [1e-9, 1, 0])


def test_fund_rejects_overflow_in_the_accumulated_index():
    with pytest.raises(PortfolioError, match="índice acumulado"):
        fund([1, 1, 1], [0, 1e200, 1e200])


def test_cetes_and_fund_reject_intraday_dates_for_daily_factors():
    dates = pd.date_range("2026-01-05 12:00", periods=3)
    with pytest.raises(PortfolioError, match="sin hora"):
        fund([10, 9, 8], [0, 0, 0], dates)
    quotes = pd.DataFrame({"p": [9.90, 9.95, 10.0], "d": [2, 1, 0]}, index=dates)
    with pytest.raises(PortfolioError, match="sin hora"):
        prepare_cetes_total_return(quotes, price_column="p", term_column="d")


@pytest.mark.parametrize(
    ("convention", "expected"),
    [
        ("nominal_360", [100, 100.3, 100.24985]),
        ("efectiva_365", [100, 100.2530467747, 100.1985538880]),
    ],
)
def test_liquidity_uses_the_previous_rate_across_weekend_and_sign_change(convention, expected):
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    rates = pd.DataFrame({"rate": [36, -18, 500]}, index=dates)
    result = prepare_liquidity_accrual(
        rates, rate_column="rate", vehicle="SIM", convention=convention, treatment="NETA",
    )
    assert result.index.tolist() == pytest.approx(expected, abs=1e-6)


def test_repo_with_fx_and_delayed_settlement_conserves_value_at_each_cut():
    def jan(day):
        return date(2026, 1, day)

    events = [
        Event("mxn", jan(2), jan(2), "OPEN_CASH", amount=100),
        Event("usd", jan(2), jan(2), "OPEN_CASH", currency="USD", amount=100),
        Event("open", jan(3), jan(5), "REPO_START", currency="USD", amount=40,
              fee="0.10", reference="SIM-USD"),
        Event("end", jan(6), jan(8), "REPO_MATURITY", currency="USD", amount="42.50",
              interest="2.50", fee="0.08", tax="0.17", reference="SIM-USD"),
    ]
    for day, price, fx, expected_cash, expected_pending, nav in [
        (3, "40.00", "20.00", "100.00", "-40.10", "2098.00"),
        (5, "41.25", "19.80", "59.90", "0.00", "2102.77"),
        (6, None, "19.80", "59.90", "42.25", "2122.57"),
        (8, None, "19.80", "102.15", "0.00", "2122.57"),
    ]:
        book = book_at(events, jan(day))
        assert book["cash"]["USD"] == Decimal(expected_cash)
        assert book["pending"].get("USD", 0) == Decimal(expected_pending)
        assert value_book(
            book, {}, {("USD", "MXN"): fx}, raw_prices_confirmed=True,
            repo_values={("SIM-USD", "USD"): price} if price else {},
        )["nav"] == Decimal(nav)
