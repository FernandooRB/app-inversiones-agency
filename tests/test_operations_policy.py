import json
from datetime import date
from decimal import Decimal as D

import pytest

from operations_cuts import build_cut
from portfolio_core import PortfolioError
from transaction_ledger import Event, book_at, value_book


def policy(**overrides):
    return {
        "schema": 1,
        "scope": {"case_id": None, "account_id": None},
        "base": "MXN",
        "valid_from": "2026-01-01",
        "source": "Política ficticia declarada",
        "basis": "net",
        "targets": [{"instrument": "AAA", "currency": "MXN", "weight": "0.6"}],
        "tolerance": "0.05",
        "max_weight": "0.7",
        "min_cash": "0.2",
        "reference": None,
        **overrides,
    }


def fixture(*, quotes=10, pending=False, valued=True, cash=40):
    first = date(2026, 1, 1)
    events = [
        Event("cash", first, first, "OPEN_CASH", amount=cash),
        Event("stock", first, first, "OPEN_POSITION", asset="AAA", quantity=6),
    ]
    if pending:
        events += [
            Event(
                "pay",
                date(2026, 1, 5),
                date(2026, 1, 20),
                "BUY",
                asset="BBB",
                quantity=8,
                price=10,
                amount=80,
            ),
            Event("recv", date(2026, 1, 6), date(2026, 1, 20), "DIVIDEND", asset="AAA", amount=100),
        ]
    book = book_at(events, date(2026, 1, 10))
    valuation = (
        value_book(book, {("AAA", "MXN"): quotes, ("BBB", "MXN"): 10}, {}, raw_prices_confirmed=True)
        if valued
        else None
    )
    return build_cut(events, cutoff="2026-01-10", base="MXN", valuation=valuation)


def check(p=None, cut=None, **kwargs):
    from operations_policy import evaluate_policy

    return evaluate_policy(p if p is not None else policy(), cut or fixture(), **kwargs)


def test_exact_declared_bounds_and_all_figures_match():
    result = check(confirmed=True)
    assert result["counts"] == {"within": 3, "deviations": 0, "pending": 0}
    rows = {r["id"]: r for r in result["rows"]}
    assert D(rows["drift:AAA:MXN"]["observed"]) == D(".6")
    assert D(rows["concentration"]["observed"]) == D(".6")
    assert D(rows["cash"]["observed"]) == D(".4")
    assert all(r["source"] == policy()["source"] for r in result["rows"])


def test_new_confirmation_missing_values_and_future_policy_stay_pending():
    assert check()["counts"]["within"] == 0
    assert check(cut=fixture(valued=False), confirmed=True)["counts"]["pending"] == 3
    assert check(policy(valid_from="2026-02-01"), confirmed=True)["counts"]["pending"] == 3


def test_boundaries_are_inclusive_and_cent_change_is_not_erased():
    exact = check(policy(tolerance="0", max_weight=".6", min_cash=".4"), confirmed=True)
    assert exact["counts"]["deviations"] == 0
    changed = check(
        policy(tolerance="0", max_weight=".6", min_cash=".4"), fixture(quotes=D("10.01")), confirmed=True
    )
    assert changed["counts"]["deviations"] == 3


def test_cash_receivables_do_not_finance_pending_payments():
    result = check(policy(min_cash=".1"), fixture(cash=90, pending=True), confirmed=True)
    row = next(r for r in result["rows"] if r["id"] == "cash")
    # NAV=250; liquidated90 - pending payment80=10; receipt100 cannot fund the floor.
    assert D(row["observed"]) == D(".04")
    assert row["state"] == "Desvío"
    assert result["cash_available"] == "10"
    assert any(r["state"] == "Pendiente" and r["instrument"] == "BBB" for r in result["rows"])


def test_invested_basis_is_explicit_and_does_not_change_cash_denominator():
    result = check(
        policy(basis="invested", targets=[{"instrument": "AAA", "currency": "MXN", "weight": "1"}]),
        confirmed=True,
    )
    assert D(next(r for r in result["rows"] if r["id"].startswith("drift:"))["observed"]) == 1
    assert D(next(r for r in result["rows"] if r["id"] == "cash")["observed"]) == D(".4")


def test_undeclared_criteria_and_unknown_asset_targets_are_not_zero():
    result = check(policy(targets=[], tolerance=None, max_weight=None, min_cash=None), confirmed=True)
    assert result["counts"]["within"] == 0 and result["counts"]["pending"] == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("tolerance", "NaN"),
        ("max_weight", "1.01"),
        ("min_cash", "-0.1"),
        ("min_cash", True),
        ("tolerance", "1e9999999"),
        ("source", ""),
        ("schema", True),
        ("basis", "unknown"),
    ],
)
def test_invalid_policy_is_rejected_without_echoing_private_values(field, value):
    from operations_policy import validate_policy

    with pytest.raises(PortfolioError, match="política"):
        validate_policy(policy(**{field: value}))


def test_scope_and_currency_mismatch_rejected_and_inputs_immutable():
    p = policy(scope={"case_id": "different", "account_id": "different"})
    with pytest.raises(PortfolioError):
        check(p, confirmed=True)
    p = policy(base="USD")
    with pytest.raises(PortfolioError):
        check(p, confirmed=True)
    p = policy()
    before = json.dumps(p, sort_keys=True)
    check(p, confirmed=True)
    assert json.dumps(p, sort_keys=True) == before


def test_v5_zip_preserves_only_proposed_criteria_and_rejects_tampering():
    from io import BytesIO
    from zipfile import ZipFile

    from operations_review import build_operations_review, read_operations_review

    manifest, raw = build_operations_review(
        {"ledger": b"fictitious ledger"}, cutoff="2026-01-10", base="MXN", policy=policy()
    )
    assert manifest["schema"] == 5
    restored, files = read_operations_review(raw)
    assert restored["policy_data"] == policy()
    assert restored["review_state"] == "PENDING_REVIEW" and files["ledger"] == b"fictitious ledger"
    with ZipFile(BytesIO(raw)) as z:
        members = {name: z.read(name) for name in z.namelist()}
    members["policy/policy.json"] = members["policy/policy.json"].replace(b'"0.7"', b'"0.8"')
    out = BytesIO()
    with ZipFile(out, "w") as z:
        for name, contents in members.items():
            z.writestr(name, contents)
    with pytest.raises(PortfolioError):
        read_operations_review(out.getvalue())


def test_v5_policy_scope_must_match_package_scope():
    from operations_review import build_operations_review

    with pytest.raises(PortfolioError):
        build_operations_review(
            {"ledger": b"fake"},
            cutoff="2026-01-10",
            base="MXN",
            policy=policy(scope={"case_id": "other", "account_id": "other"}),
        )


def test_policy_report_uses_same_snapshot_and_bounded_pdf():
    from io import BytesIO

    from pypdf import PdfReader

    from operations_report import performance_pdf
    from operations_status import OperationStatus, status_text

    status = OperationStatus(base="MXN", cutoff="2026-01-10")
    status.policy_report = check(policy(max_weight=".5"), confirmed=True)
    snapshot = status.snapshot("Cuenta ficticia")
    assert snapshot["policy_report"]["counts"]["deviations"] == 1
    assert b'"policy_report"' in status_text(snapshot)
    pages = PdfReader(BytesIO(performance_pdf(snapshot))).pages
    assert len(pages) == 2 and "Política de cartera" in pages[1].extract_text()


def test_ui_changes_revoke_confirmation_and_current_zip_gets_current_policy():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        """
from datetime import date
import streamlit as st
from operations_policy_ui import render_policy
from operations_status import OperationStatus
from transaction_ledger import Event,book_at,value_book
st.session_state['_ops_context_key']='policy-test'
st.session_state.setdefault('_ops_review_policy-test',{'token':'seed','files':{}})
events=(Event('c',date(2026,1,1),date(2026,1,1),'OPEN_CASH',amount=40),
        Event('p',date(2026,1,1),date(2026,1,1),'OPEN_POSITION',asset='AAA',quantity=6))
book=book_at(events,date(2026,1,10))
status=OperationStatus(cutoff='2026-01-10',base='MXN',book=book,ledger_events=events,
 valuation=value_book(book,{('AAA','MXN'):10},{},raw_prices_confirmed=True))
st.session_state.setdefault('policy_panel_policy-test_seed',True)
render_policy((None,None,None,None),status)
st.session_state['report']=status.policy_report
""",
        default_timeout=45,
    ).run()
    assert not app.exception
    assert next(x for x in app.number_input if x.label.startswith("Máximo individual")).value is None
    next(x for x in app.text_input if x.label == "Fuente de la política").set_value("Ficticia").run()
    next(x for x in app.number_input if x.label.startswith("Máximo individual")).set_value(50).run()
    consent = next(x for x in app.checkbox if x.label.startswith("Confirmé la política"))
    assert not consent.value
    consent.check().run()
    assert app.session_state["report"]["counts"]["deviations"] == 1
    next(x for x in app.number_input if x.label.startswith("Máximo individual")).set_value(70).run()
    assert not next(x for x in app.checkbox if x.label.startswith("Confirmé la política")).value
    assert app.session_state["_ops_review_policy-test"]["policy"]["max_weight"] == "0.7"
    assert app.session_state["report"]["counts"]["within"] == 0


@pytest.mark.parametrize("name", ["=AAA", "+AAA", "-AAA", "@AAA", "  =AAA"])
def test_editable_targets_roundtrip_preserves_original_identifiers(name):
    from operations_policy import targets_from_csv
    from operations_policy_ui import targets_csv

    targets = [{"instrument": name, "currency": "MXN", "weight": "0.6"}]
    assert targets_from_csv(targets_csv(targets)) == targets


def test_v5_accepts_legacy_and_strategy_proposals_together_with_policy():
    from test_operations_comparison import flow, proposal_case

    from operations_proposal import portable_proposal
    from operations_review import build_operations_review, read_operations_review

    data = flow.__wrapped__()
    for linked in (False, True):
        proposal = portable_proposal(proposal_case(data, linked=linked))
        _, raw = build_operations_review(
            {"ledger": b"fake"},
            cutoff=proposal["inputs"]["date"],
            base="MXN",
            proposal=proposal,
            policy=policy(),
        )
        opened, _ = read_operations_review(raw)
        assert opened["schema"] == 5 and opened["proposal_data"] == proposal
        assert opened["policy_data"] == policy()


def reference(as_of="2026-01-10"):
    return {
        "schema": 1,
        "name": "Ficticia",
        "run_id": "a" * 32,
        "analysis_key": "b" * 64,
        "code_sha256": "c" * 64,
        "files_sha256": {n: "d" * 64 for n in ("holdings", "prices", "rights")},
        "assets": ["AAA", "BBB"],
        "weights": [0.6, 0.4],
        "currency": "MXN",
        "as_of": as_of,
        "history_start": "2025-01-01",
        "sample_start": "2025-01-02",
        "sample_end": "2026-01-05",
    }


def test_imported_reference_does_not_absorb_real_cent_change_at_zero_tolerance():
    first = date(2026, 1, 1)
    events = [Event(a, first, first, "OPEN_POSITION", asset=a, quantity=1) for a in ("AAA", "BBB")]
    book = book_at(events, date(2026, 1, 10))
    val = value_book(
        book,
        {("AAA", "MXN"): D("6000000000.01"), ("BBB", "MXN"): D("4000000000")},
        {},
        raw_prices_confirmed=True,
    )
    cut = build_cut(events, cutoff="2026-01-10", base="MXN", valuation=val)
    p = policy(
        basis="invested",
        reference=reference(),
        tolerance="0",
        targets=[
            {"instrument": a, "currency": "MXN", "weight": w} for a, w in (("AAA", ".6"), ("BBB", ".4"))
        ],
    )
    result = check(p, cut, confirmed=True)
    assert all(r["state"] == "Desvío" for r in result["rows"] if r["kind"] == "drift")


def test_future_analysis_is_pending_on_an_earlier_cut():
    p = policy(
        basis="invested",
        reference=reference("2026-01-15"),
        targets=[
            {"instrument": a, "currency": "MXN", "weight": w} for a, w in (("AAA", ".6"), ("BBB", ".4"))
        ],
    )
    result = check(p, confirmed=True)
    assert result["counts"]["within"] == 0 and result["counts"]["deviations"] == 0
