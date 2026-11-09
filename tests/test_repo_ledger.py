"""Repo cash/asset conservation and fail-closed input checks; fictional contracts."""

import csv
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest

from portfolio_core import PortfolioError
from transaction_ledger import (
    COLUMNS,
    LEGACY_COLUMNS,
    Event,
    book_at,
    merge_events,
    read_ledger,
    read_repo_values,
    value_book,
)

D = date(2026, 1, 1)
NEXT = D + timedelta(days=1)


def origin(kind="REPO_START", **kwargs):
    return Event("repo-open", D, D, kind, amount=1000, reference="SIM-REPO-1", **kwargs)


def maturity(**kwargs):
    return Event(
        "repo-end", NEXT, NEXT, "REPO_MATURITY", amount=1010, interest=10,
        fee=1, tax=2, reference="SIM-REPO-1", **kwargs,
    )


def value(book, **kwargs):
    return value_book(book, {}, {}, raw_prices_confirmed=True, **kwargs)


def test_repo_principal_moves_from_cash_to_receivable_then_returns_only_net_income():
    events = [Event("cash", D, D, "OPEN_CASH", amount=2000), origin(), maturity()]
    invested = book_at(events, D)
    assert invested["positions"] == {}  # collateral is not a second owned investment
    assert invested["cash"] == {"MXN": 1000}
    assert invested["repos"] == {("SIM-REPO-1", "MXN"): 1000}
    assert value(invested, repo_values={("SIM-REPO-1", "MXN"): 1000})["nav"] == 2000
    closed = book_at(events, NEXT)
    assert not closed["repos"] and not closed["pending"]
    assert value(closed)["nav"] == 2007  # 10 interest - 1 fee - 2 tax, not 1010 profit


def test_opening_repo_has_no_second_cash_debit_or_external_contribution():
    events = [Event("cash", D, D, "OPEN_CASH", amount=50), origin("OPEN_REPO"), maturity()]
    opening = book_at(events, D)
    assert opening["cash"]["MXN"] == 50
    assert value(opening, repo_values={("SIM-REPO-1", "MXN"): 1003})["nav"] == 1053
    assert value(book_at(events, NEXT))["nav"] == 1057
    assert all(e.kind not in {"DEPOSIT", "WITHDRAWAL"} for e in events)


def test_start_and_maturity_settlement_do_not_duplicate_receivable_or_payable():
    start = replace(origin(), settled=NEXT)
    end = replace(maturity(), settled=NEXT + timedelta(days=1))
    events = [Event("cash", D, D, "OPEN_CASH", amount=2000), start, end]
    pending_start = book_at(events, D)
    assert pending_start["cash"]["MXN"] == 2000
    assert pending_start["pending"]["MXN"] == -1000
    assert value(pending_start, repo_values={("SIM-REPO-1", "MXN"): 1000})["nav"] == 2000
    pending_end = book_at(events, NEXT)
    assert not pending_end["repos"]
    assert pending_end["cash"]["MXN"] == 1000 and pending_end["pending"]["MXN"] == 1007
    assert value(pending_end)["nav"] == value(book_at(events, end.settled))["nav"] == 2007


def test_outstanding_repo_requires_explicit_total_value_and_currency_conversion():
    book = book_at([origin("OPEN_REPO", currency="USD")], D)
    with pytest.raises(PortfolioError, match="valuación documentada"):
        value(book)
    with pytest.raises(PortfolioError, match="tipo de cambio"):
        value(book, repo_values={("SIM-REPO-1", "USD"): "1003.25"})
    result = value_book(
        book, {}, {("USD", "MXN"): "20"}, raw_prices_confirmed=True,
        repo_values={("SIM-REPO-1", "USD"): "1003.25"},
    )
    assert result["nav"] == Decimal("20065.00")
    with pytest.raises(PortfolioError, match="sobran referencias"):
        value(book, repo_values={("OTHER", "USD"): 1000})
    with pytest.raises(PortfolioError, match="positiva"):
        value(book, repo_values={("SIM-REPO-1", "USD"): 0})


@pytest.mark.parametrize(
    "events, message",
    [
        ([maturity()], "apertura previa"),
        ([origin(), replace(origin(), id="duplicate")], "referencia única"),
        ([origin(), maturity(), replace(maturity(), id="twice")], "apertura previa"),
        ([origin(), maturity(), replace(origin(), id="reuse", day=NEXT, settled=NEXT)], "referencia única"),
        ([origin(), replace(maturity(), amount="1010.01")], "capital"),
        ([origin(), replace(maturity(), currency="USD")], "moneda"),
        ([origin(), replace(maturity(), asset="DIFFERENT")], "instrumento"),
        ([replace(origin(), settled=NEXT + timedelta(days=1)), maturity()], "antes de liquidar"),
        ([replace(maturity(), day=D, settled=D), origin()], "apertura previa"),
    ],
)
def test_lifecycle_rejects_orphans_duplicates_mismatches_and_wrong_sequence(events, message):
    with pytest.raises(PortfolioError, match=message):
        book_at(events, D)


def test_two_same_day_contracts_do_not_match_by_amount_or_collateral_alone():
    first = origin()
    second = replace(first, id="other", reference="SIM-REPO-2")
    second_end = replace(maturity(), reference="SIM-REPO-2")
    events = [first, second, second_end]
    assert book_at(events, NEXT)["repos"] == {("SIM-REPO-1", "MXN"): 1000}
    assert len(merge_events(events, events)) == 3


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"reference": " "}, "referencia"),
        ({"amount": 0}, "capital"),
        ({"interest": 1}, "sólo al vencimiento"),
        ({"quantity": 1}, "títulos ni precio"),
        ({"price": 100}, "títulos ni precio"),
        ({"kind": "OPEN_REPO", "fee": 1}, "no mueve efectivo"),
        ({"kind": "OPEN_REPO", "settled": NEXT}, "no mueve efectivo"),
    ],
)
def test_repo_row_rejects_unsupported_or_ambiguous_fields(changes, message):
    with pytest.raises(PortfolioError, match=message):
        replace(origin(), **changes)


def test_interest_breakdown_is_not_available_on_other_cash_events():
    with pytest.raises(PortfolioError, match="sólo para desglosar"):
        Event("bad", D, D, "DEPOSIT", amount=1000, interest=10)
    with pytest.raises(PortfolioError, match="capital"):
        replace(maturity(), interest=1010)


def csv_bytes(columns, rows):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def test_legacy_books_remain_readable_and_new_books_preserve_interest_precision():
    row = ["cash", str(D), str(D), "OPEN_CASH", "", "MXN", "0", "0", "1000", "0", "0", "", "UNKNOWN"]
    assert read_ledger(csv_bytes(LEGACY_COLUMNS, [row]))[0].cash == 1000
    start = ["open", str(D), str(D), "OPEN_REPO", "", "MXN", "0", "0", "1000", "0", "0", "R", "UNKNOWN"]
    end = [
        "end", str(NEXT), str(NEXT), "REPO_MATURITY", "", "MXN", "0", "0", "1000.012345",
        "0", "0", "R", "UNKNOWN",
    ]
    events = read_ledger(csv_bytes(COLUMNS, [[*start, "0"], [*end, "0.012345"]]))
    assert events[-1].interest == Decimal("0.012345")
    assert book_at(events, NEXT)["cash"]["MXN"] == Decimal("1000.012345")
    with pytest.raises(PortfolioError, match="columna Interes"):
        read_ledger(csv_bytes(LEGACY_COLUMNS, [start]))
    with pytest.raises(PortfolioError, match="Declara Interes"):
        read_ledger(csv_bytes(COLUMNS, [[*start, "0"], [*end, ""]]))


@pytest.mark.parametrize(
    "row, message",
    [
        ([str(NEXT), "R", "MXN", "1003.25", "statement"], "fecha del cierre"),
        ([str(D), "R", "MXN", "1003.25", " "], "fuente"),
        ([str(D), "R", "EUR", "1003.25", "statement"], "moneda"),
        ([str(D), "", "MXN", "1003.25", "statement"], "referencia"),
        ([str(D), "R", "MXN", "NaN", "statement"], "inválidos"),
        ([str(D), "R", "MXN", "-1", "statement"], "positiva"),
    ],
)
def test_repo_valuations_require_exact_cut_source_reference_and_positive_value(row, message):
    with pytest.raises(PortfolioError, match=message):
        read_repo_values(csv_bytes(("Fecha", "Referencia", "Moneda", "Valor", "Fuente"), [row]), D)


def test_repo_valuation_parser_does_not_round_or_accept_duplicate_rows():
    columns = ("Fecha", "Referencia", "Moneda", "Valor", "Fuente")
    row = [str(D), "R", "MXN", "1000.012345", "statement"]
    assert read_repo_values(csv_bytes(columns, [row]), D) == {("R", "MXN"): Decimal("1000.012345")}
    with pytest.raises(PortfolioError, match="duplicadas"):
        read_repo_values(csv_bytes(columns, [row, row]), D)
