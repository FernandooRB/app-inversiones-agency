import json
from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from operations_report import explain_performance
from portfolio_core import PortfolioError
from realized_performance import performance
from transaction_ledger import Event, book_at, value_book


def test_documented_income_is_grouped_by_asset_currency_and_trade_date():
    events = [
        Event("a", date(2026, 1, 5), date(2026, 2, 1), "DIVIDEND", asset="AAA", amount=10, fee=1, tax=2),
        Event("b", date(2025, 12, 30), date(2026, 1, 5), "DIVIDEND", asset="BBB", amount=30),
    ]
    nav = pd.Series([100, 107], index=pd.to_datetime(["2026-01-01", "2026-01-10"]))
    summary = explain_performance(events, nav, performance(nav, []), [], base="MXN")
    assert summary["income"] == 10
    assert summary["fees"] == 1 and summary["tax"] == 2
    assert summary["unexplained"] == 0
    assert summary["by_instrument"] == [
        {
            "instrument": "AAA",
            "currency": "MXN",
            "income": "10",
            "fees": "1",
            "tax": "2",
            "net": "7",
            "event_ids": ["a"],
            "converted": True,
        }
    ]


def test_foreign_income_is_visible_in_native_currency_without_fake_fx():
    day = date(2026, 1, 5)
    nav = pd.Series([100, 107], index=pd.to_datetime(["2026-01-01", "2026-01-10"]))
    summary = explain_performance(
        [Event("d", day, day, "DIVIDEND", asset="USD-FUND", currency="USD", amount=D("1.01"))],
        nav,
        performance(nav, []),
        [],
        base="MXN",
    )
    assert summary["income"] is None
    assert summary["by_instrument"][0]["net"] == "1.01"
    assert summary["by_instrument"][0]["converted"] is False


def test_repo_income_is_only_interest_and_cent_residual_remains_visible():
    day = date(2026, 1, 5)
    nav = pd.Series([100, 103.01], index=pd.to_datetime(["2026-01-01", "2026-01-10"]))
    summary = explain_performance(
        [Event("r", day, day, "REPO_MATURITY", asset="BONO", amount=103, interest=3, reference="r")],
        nav,
        performance(nav, []),
        [],
        base="MXN",
    )
    assert summary["by_instrument"][0]["income"] == "3"
    assert abs(summary["unexplained"] - 0.01) < 1e-10


def cut(events, day, *, quotes=None, fx=None, repos=None, base="MXN", valued=True, **kwargs):
    from operations_cuts import build_cut, read_cut

    book = book_at(events, date.fromisoformat(day))
    valuation = (
        value_book(book, quotes or {}, fx or {}, base=base, raw_prices_confirmed=True, repo_values=repos)
        if valued
        else None
    )
    return read_cut(
        build_cut(
            events,
            cutoff=day,
            base=base,
            case_id="case-fake",
            account_id="account-fake",
            valuation=valuation,
            **kwargs,
        )
    )


def compare(before, after, **kwargs):
    from operations_cuts import compare_cuts

    return compare_cuts(before, after, **kwargs)


def opening(currency="MXN"):
    return Event("open", date(2026, 1, 1), date(2026, 1, 1), "OPEN_CASH", currency=currency, amount=100)


def test_deposit_is_not_profit_and_input_snapshots_are_immutable():
    events = [opening(), Event("dep", date(2026, 1, 5), date(2026, 1, 5), "DEPOSIT", amount=50, timing="EOD")]
    before, after = cut(events, "2026-01-01"), cut(events, "2026-01-10")
    original = json.dumps([before, after], sort_keys=True)
    result = compare(before, after, confirmed=True)
    assert result["wealth_change"] == "50" and result["gain"] == "0"
    assert result["contributions"] == "50" and result["unexplained"] == "0"
    assert json.dumps([before, after], sort_keys=True) == original


def test_settlement_is_not_another_gain_and_price_income_costs_reconcile():
    events = [
        opening(),
        Event(
            "buy",
            date(2026, 1, 2),
            date(2026, 1, 4),
            "BUY",
            asset="AAA",
            quantity=2,
            price=10,
            amount=20,
            fee=1,
        ),
        Event(
            "sell", date(2026, 1, 5), date(2026, 1, 12), "SELL", asset="AAA", quantity=2, price=12, amount=24
        ),
        Event("div", date(2026, 1, 6), date(2026, 1, 13), "DIVIDEND", asset="AAA", amount=3, tax=D(".3")),
    ]
    result = compare(cut(events, "2026-01-01"), cut(events, "2026-01-10"), confirmed=True)
    assert result["gain"] == "5.7" and result["price"] == "4"
    assert result["income"] == "3" and result["fees"] == "1" and result["tax"] == "0.3"
    assert result["unexplained"] == "0.0"
    settled = compare(cut(events, "2026-01-10"), cut(events, "2026-01-15"), confirmed=True)
    assert D(settled["gain"]) == 0 and D(settled["income"]) == 0


def test_split_and_in_kind_transfer_do_not_invent_profit():
    events = [
        opening(),
        Event("pos", date(2026, 1, 1), date(2026, 1, 1), "OPEN_POSITION", asset="AAA", quantity=10),
        Event("split", date(2026, 1, 3), date(2026, 1, 3), "SPLIT", asset="AAA", quantity=2),
        Event(
            "gift",
            date(2026, 1, 5),
            date(2026, 1, 5),
            "ASSET_IN",
            asset="AAA",
            quantity=2,
            price=5,
            reference="documented",
        ),
    ]
    result = compare(
        cut(events, "2026-01-01", quotes={("AAA", "MXN"): 10}),
        cut(events, "2026-01-10", quotes={("AAA", "MXN"): 5}),
        confirmed=True,
    )
    assert D(result["gain"]) == 0 and D(result["price"]) == 0
    assert result["contributions"] == "10"


def test_foreign_static_holding_separates_price_from_fx():
    events = [
        Event(
            "pos",
            date(2026, 1, 1),
            date(2026, 1, 1),
            "OPEN_POSITION",
            asset="AAA",
            currency="USD",
            quantity=10,
        )
    ]
    result = compare(
        cut(events, "2026-01-01", quotes={("AAA", "USD"): 10}, fx={("USD", "MXN"): 20}),
        cut(events, "2026-01-10", quotes={("AAA", "USD"): 12}, fx={("USD", "MXN"): 21}),
        confirmed=True,
    )
    assert result["gain"] == "520" and result["price"] == "420" and result["fx"] == "100"
    assert D(result["unexplained"]) == 0


def test_foreign_trade_does_not_invent_transaction_fx():
    events = [
        opening("USD"),
        Event(
            "buy",
            date(2026, 1, 5),
            date(2026, 1, 5),
            "BUY",
            currency="USD",
            asset="AAA",
            quantity=2,
            price=10,
            amount=20,
        ),
    ]
    result = compare(
        cut(events, "2026-01-01", fx={("USD", "MXN"): 20}),
        cut(events, "2026-01-10", quotes={("AAA", "USD"): 12}, fx={("USD", "MXN"): 21}),
        confirmed=True,
    )
    assert result["gain"] == "184" and result["price"] is None and result["fx"] is None
    assert result["by_instrument"][0]["price_native"] == "4"
    assert result["unexplained"] == "184"
    assert any("FX" in s for s in result["pending"])


def test_missing_repo_valuation_remains_pending_and_principal_is_not_income():
    events = [
        opening(),
        Event("repo", date(2026, 1, 1), date(2026, 1, 1), "OPEN_REPO", amount=100, reference="repo"),
        Event(
            "maturity",
            date(2026, 1, 5),
            date(2026, 1, 5),
            "REPO_MATURITY",
            amount=103,
            interest=3,
            reference="repo",
        ),
    ]
    start = cut(events, "2026-01-01", repos={("repo", "MXN"): D("101")})
    result = compare(start, cut(events, "2026-01-10"), confirmed=True)
    assert result["gain"] == "2" and result["income"] == "3" and result["repo"] == "-1"
    assert D(result["unexplained"]) == 0
    partial = compare(cut(events, "2026-01-01", valued=False), cut(events, "2026-01-10"), confirmed=True)
    assert partial["gain"] is None and partial["pending"]


def test_cent_difference_from_documented_closing_value_is_not_erased():
    before, after = cut([opening()], "2026-01-01"), cut([opening()], "2026-01-10")
    # Same book; an external NAV discrepancy remains in historical summary, not a new price.
    assert D(compare(before, after, confirmed=True)["gain"]) == 0


def test_changed_history_and_same_cut_version_do_not_claim_period_gain():
    before = cut([opening()], "2026-01-01")
    changed = cut([Event("open", date(2026, 1, 1), date(2026, 1, 1), "OPEN_CASH", amount=101)], "2026-01-10")
    assert compare(before, changed, confirmed=True)["gain"] is None
    result = compare(before, cut([opening()], "2026-01-01"), confirmed=True)
    assert result["mode"] == "version" and result["gain"] is None


def test_cut_never_restores_confirmation_or_equates_metrics_with_other_periods():
    before, after = cut([opening()], "2026-01-01"), cut([opening()], "2026-01-10")
    assert compare(before, after)["gain"] is None
    result = compare(before, after, confirmed=True)
    assert "twr" not in result and "xirr" not in result
    assert result["historical_results"] == [None, None]


@pytest.mark.parametrize(
    "change", ["digest", "duplicate", "oversize", "scope", "valuation", "future", "fields"]
)
def test_cut_rejects_corruption_limits_scope_and_inconsistent_values(change):
    from hashlib import sha256

    from operations_cuts import read_cut

    before = cut([opening()], "2026-01-01")
    if change == "digest":
        before["sha256"] = "0" * 64
    elif change == "duplicate":
        with pytest.raises(PortfolioError):
            read_cut(b'{"schema":1,"schema":1}')
        return
    elif change == "oversize":
        with pytest.raises(PortfolioError):
            read_cut(b" " * 2_000_001)
        return
    elif change == "scope":
        with pytest.raises(PortfolioError):
            read_cut(json.dumps(before).encode(), case_id="other", account_id="other")
        return
    elif change == "valuation":
        before["payload"]["valuation"]["nav"] = "101"
    elif change == "future":
        before["payload"]["cutoff"] = "2999-01-01"
    elif change == "fields":
        before["payload"]["approved"] = True
    if change != "digest":
        before["sha256"] = sha256(
            json.dumps(
                before["payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    with pytest.raises(PortfolioError):
        read_cut(json.dumps(before).encode())


def test_report_preserves_exact_comparison_and_has_two_pages():
    from io import BytesIO

    from pypdf import PdfReader

    from operations_report import performance_pdf
    from operations_status import OperationStatus, status_text

    events = [opening(), Event("f", date(2026, 1, 5), date(2026, 1, 5), "FEE", amount=D(".01"))]
    result = compare(cut(events, "2026-01-01"), cut(events, "2026-01-10"), confirmed=True)
    assert D(result["gain"]) == D("-.01")
    status = OperationStatus()
    status.cut_comparison = result
    snapshot = status.snapshot("Cuenta ficticia")
    assert snapshot["cut_comparison"] == result
    assert b'"gain": "-0.01"' in status_text(snapshot)
    pages = PdfReader(BytesIO(performance_pdf(snapshot))).pages
    assert len(pages) == 2
    assert "Comparación de cortes" in pages[0].extract_text()
    assert "-0.01 MXN" in pages[0].extract_text()


def test_comparison_csv_neutralizes_spreadsheet_formula_identifiers():
    from operations_cuts_ui import comparison_csv

    events = [
        Event("p", date(2026, 1, 1), date(2026, 1, 1), "OPEN_POSITION", asset="=UNTRUSTED()", quantity=1)
    ]
    result = compare(
        cut(events, "2026-01-01", quotes={("=UNTRUSTED()", "MXN"): 10}),
        cut(events, "2026-01-10", quotes={("=UNTRUSTED()", "MXN"): 11}),
        confirmed=True,
    )
    raw = comparison_csv(result)
    assert b"'=UNTRUSTED()" in raw
    assert b"Ganancia monetaria" in raw and b"1" in raw


def test_cut_ui_renews_confirmation_on_change_and_does_not_recompute_navigation():
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest

    from operations_cuts import build_cut, compare_cuts

    previous = build_cut(
        [opening()],
        cutoff="2026-01-01",
        base="MXN",
        valuation=value_book(book_at([opening()], date(2026, 1, 1)), {}, {}, raw_prices_confirmed=True),
    )
    app = AppTest.from_string(
        f"""
from datetime import date
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from transaction_ledger import Event,book_at,value_book
from operations_status import OperationStatus
from operations_cuts_ui import render_cut_comparison
events=[Event("open",date(2026,1,1),date(2026,1,1),"OPEN_CASH",amount=100),
        Event("fee",date(2026,1,5),date(2026,1,5),"FEE",amount=st.session_state.get("amount",".01"))]
book=book_at(events,date(2026,1,10))
status=OperationStatus(cutoff="2026-01-10",base="MXN",book=book,
 valuation=value_book(book,{{}},{{}},raw_prices_confirmed=True),ledger_events=tuple(events))
st.session_state.setdefault("cuts_panel",True)
with patch("operations_cuts_ui.st.file_uploader",return_value=BytesIO({previous!r})):
 st.session_state["result"]=render_cut_comparison(
  (None,None,None,None),status,status.snapshot("Ficticia"),key=lambda x:x)
""",
        default_timeout=45,
    )
    with patch("operations_cuts_ui.compare_cuts", wraps=compare_cuts) as engine:
        app.run()
        assert not app.exception
        assert not app.checkbox(key="cuts_confirmed").value
        app.checkbox(key="cuts_confirmed").check().run()
        assert app.session_state["result"]["gain"] == "-0.01"
        calls = engine.call_count
        app.run()
        assert engine.call_count == calls
        app.session_state["amount"] = ".02"
        app.run()
        assert not app.checkbox(key="cuts_confirmed").value
        assert app.session_state["result"]["gain"] is None
        app.checkbox(key="cuts_confirmed").check().run()
        assert app.session_state["result"]["gain"] == "-0.02"
        app.session_state["cuts_panel"] = False
        app.run()
        assert app.session_state["result"] is None


@pytest.mark.parametrize("number", ["1e9999999", "1e-9999999999999999999", "NaN", "Infinity"])
def test_hostile_decimal_is_rejected_with_public_validation_error(number):
    from hashlib import sha256

    from operations_cuts import read_cut

    saved = cut([opening()], "2026-01-01")
    saved["payload"]["valuation"]["detail"][0]["ValorOrigen"] = number
    saved["sha256"] = sha256(
        json.dumps(
            saved["payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    with pytest.raises(PortfolioError, match="El corte no es válido"):
        read_cut(json.dumps(saved).encode())


def test_foreign_split_needs_no_fabricated_transaction_fx():
    events = [
        Event(
            "p", date(2026, 1, 1), date(2026, 1, 1), "OPEN_POSITION", asset="AAA", currency="USD", quantity=10
        ),
        Event("s", date(2026, 1, 5), date(2026, 1, 5), "SPLIT", asset="AAA", currency="USD", quantity=2),
    ]
    result = compare(
        cut(events, "2026-01-01", quotes={("AAA", "USD"): 10}, fx={("USD", "MXN"): 20}),
        cut(events, "2026-01-10", quotes={("AAA", "USD"): 5}, fx={("USD", "MXN"): 21}),
        confirmed=True,
    )
    assert D(result["price"]) == 0 and D(result["fx"]) == 100


def test_clear_review_discards_current_cut_data_only(monkeypatch):
    from types import SimpleNamespace

    import operations_review_ui as ui

    state = {
        "_ops_context_key": "own",
        "_ops_review_own": {"token": "token", "files": {}},
        "cut_comparison_result_other": {"keep": True},
    }
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    owned = [ui.review_key(name) for name in ("cut_previous", "cuts_confirmed", "cut_comparison_result")]
    owned += ["_analysis_memo_" + ui.review_key(name) for name in ("cut_build", "cut_compare")]
    for name in owned:
        state[name] = {"private": True}
    ui.clear_review()
    assert not set(owned).intersection(state)
    assert state["cut_comparison_result_other"] == {"keep": True}


def test_partial_fx_does_not_reclassify_already_explained_base_prices_as_unknown():
    events = [
        opening("USD"),
        Event("pos", date(2026, 1, 1), date(2026, 1, 1), "OPEN_POSITION", asset="AAA", quantity=1),
        Event(
            "buy",
            date(2026, 1, 5),
            date(2026, 1, 5),
            "BUY",
            asset="BBB",
            currency="USD",
            quantity=2,
            price=10,
            amount=20,
        ),
    ]
    result = compare(
        cut(events, "2026-01-01", quotes={("AAA", "MXN"): 100}, fx={("USD", "MXN"): 20}),
        cut(events, "2026-01-10", quotes={("AAA", "MXN"): 110, ("BBB", "USD"): 10}, fx={("USD", "MXN"): 20}),
        confirmed=True,
    )
    assert result["price"] is None
    assert result["known_components"]["price"] == "10"
    assert D(result["unexplained"]) == 0


def test_pdf_comparison_keeps_original_cent_at_large_admitted_amount():
    from io import BytesIO

    from pypdf import PdfReader

    from operations_report import performance_pdf
    from operations_status import OperationStatus

    saved = OperationStatus().snapshot("Cuenta ficticia")
    result = compare(cut([opening()], "2026-01-01"), cut([opening()], "2026-01-10"), confirmed=True)
    result["gain"] = "100000000000000.01"
    saved["cut_comparison"] = result
    text = PdfReader(BytesIO(performance_pdf(saved))).pages[0].extract_text()
    assert "100,000,000,000,000.01 MXN" in text
    assert "100,000,000,000,000.02 MXN" not in text
