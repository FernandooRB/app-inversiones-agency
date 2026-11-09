"""Closing controls must expose differences without silently resetting account history."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from ledger_reconciliation import ClosingControl, read_closing_controls, reconcile_book
from portfolio_core import PortfolioError
from transaction_ledger import Event, book_at

D = date(2026, 1, 1)


def control(kind, balance, item="", currency="MXN", day=D):
    return ClosingControl(day, kind, item, currency, balance, "Estado ficticio, página 2")


def test_cent_difference_carries_to_next_close_without_resetting_to_statement_opening():
    events = [Event("opening", D, D, "OPEN_CASH", amount=100)]
    book = book_at(events, D)
    original = deepcopy(book)
    july = reconcile_book(book, [control("CASH", "100.01")], cutoff=D)
    assert july["status"] == "REQUIERE_REVISION" and july["differences"] == 1
    assert july["rows"][0]["Diferencia"] == Decimal("-0.01")
    tomorrow = D + timedelta(days=1)
    events.append(Event("dividend", tomorrow, tomorrow, "DIVIDEND", amount=10))
    august = reconcile_book(
        book_at(events, tomorrow), [control("CASH", "110.01", day=tomorrow)], cutoff=tomorrow,
    )
    assert august["rows"][0]["Diferencia"] == Decimal("-0.01")
    assert july["postings_created"] == august["postings_created"] == 0
    assert july["human_approval"] is None and book == original


def test_settled_cash_pending_payable_and_titles_are_checked_separately():
    book = book_at([
        Event("opening", D, D, "OPEN_CASH", amount=1000),
        Event("buy", D, D + timedelta(days=1), "BUY", asset="SIM-A", quantity=2, price=100, amount=200),
    ], D)
    result = reconcile_book(book, [control("CASH", 1000), control("PENDING", -200),
                                   control("POSITION", 2, "SIM-A")], cutoff=D)
    assert result["status"] == "COINCIDENCIA_ARITMETICA" and result["exact"] == 3
    result = reconcile_book(book, [control("CASH", 800), control("POSITION", 2, "SIM-A")], cutoff=D)
    assert result["differences"] == 1 and result["missing"] == 1


def test_missing_control_is_unknown_even_for_zero_book_cash():
    book = book_at([Event("position", D, D, "OPEN_POSITION", asset="SIM-A", quantity=1)], D)
    result = reconcile_book(book, [control("POSITION", 1, "SIM-A")], cutoff=D)
    row = next(r for r in result["rows"] if r["Tipo"] == "CASH")
    assert row["Libro"] == 0 and row["Control"] is None and row["Diferencia"] is None
    assert row["Estado"] == "SIN_CONTROL" and result["status"] == "REQUIERE_REVISION"


def test_source_only_holdings_reveal_missing_positions_instead_of_being_ignored():
    book = book_at([Event("cash", D, D, "OPEN_CASH", amount=100)], D)
    result = reconcile_book(
        book, [control("CASH", 100), control("POSITION", "0.000001", "OMITTED")], cutoff=D,
    )
    row = next(r for r in result["rows"] if r["Tipo"] == "POSITION")
    assert row["Libro"] == 0 and row["Diferencia"] == Decimal("-0.000001")
    assert row["Unidad"] == "títulos" and row["Estado"] == "DIFERENCIA"


def test_currencies_are_not_netted_and_repo_principal_is_not_a_valuation():
    book = book_at([
        Event("mxn", D, D, "OPEN_CASH", amount=100),
        Event("usd", D, D, "OPEN_CASH", amount=100, currency="USD"),
        Event("repo", D, D, "OPEN_REPO", amount=500, reference="SIM-R"),
    ], D)
    result = reconcile_book(book, [control("CASH", 99), control("CASH", 101, currency="USD"),
                                   control("REPO", 500, "SIM-R")], cutoff=D)
    assert result["differences"] == 2 and result["exact"] == 1 and "nav" not in result
    assert sum(r["Diferencia"] for r in result["rows"]) == 0  # not a criterion for a match


@pytest.mark.parametrize(
    "kwargs", [
        {"kind": "UNKNOWN"}, {"currency": "EUR"}, {"source": " "},
        {"item": "SIM"}, {"kind": "POSITION", "balance": -1, "item": "SIM"},
        {"kind": "REPO", "item": ""}, {"balance": "NaN"}, {"source": "x\ny"},
    ],
)
def test_control_validation_rejects_ambiguous_units_and_unusable_evidence(kwargs):
    fields = dict(day=D, kind="CASH", item="", currency="MXN", balance=1, source="Synthetic")
    fields.update(kwargs)
    with pytest.raises(PortfolioError):
        ClosingControl(**fields)


def test_duplicate_or_wrong_cut_controls_are_rejected_not_summed():
    with pytest.raises(PortfolioError, match="duplicados"):
        reconcile_book({}, [control("CASH", 1), control("CASH", 1)], cutoff=D)
    with pytest.raises(PortfolioError, match="otro cierre"):
        reconcile_book({}, [control("CASH", 1, day=D + timedelta(days=1))], cutoff=D)


def test_control_csv_keeps_decimal_precision_and_requires_exact_cut_and_source():
    header = "Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente\n"
    raw = (header + f"{D},POSITION,SIM-A,MXN,0.123456789,Estado ficticio\n").encode("utf-8-sig")
    assert read_closing_controls(raw, D)[0].balance == Decimal("0.123456789")
    for bad in [header, header + f"{D},CASH,,MXN,1,\n", header + f"{D},CASH,,MXN,1,Source,extra\n"]:
        with pytest.raises(PortfolioError):
            read_closing_controls(bad.encode(), D)
    with pytest.raises(PortfolioError, match="cierre elegido"):
        read_closing_controls(raw, D + timedelta(days=1))
