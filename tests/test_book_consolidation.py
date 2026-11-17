"""Independent money expectations; all accounts and documents are fictional."""

import json
from datetime import date
from decimal import Decimal as D
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from operations_cuts import build_cut
from portfolio_core import PortfolioError
from transaction_ledger import Event, book_at, value_book

DAY = date(2026, 1, 10)
FX = b"Fecha,Moneda,Base,Tasa,Fuente\n2026-01-10,USD,MXN,20.01,Cierre ficticio\n"


def account(alias, amount, currency="MXN", *, extra=(), valued=True, scope=None, base=None):
    events = [Event(alias + "-open", DAY, DAY, "OPEN_CASH", currency=currency, amount=D(amount)), *extra]
    book = book_at(events, DAY)
    valuation = (
        value_book(
            book,
            {},
            {("MXN", "USD"): D("0.05"), ("USD", "MXN"): D("20.01")},
            base=base or currency,
            raw_prices_confirmed=True,
        )
        if valued
        else None
    )
    return {
        "alias": alias,
        "source": "Cuenta propia ficticia " + alias,
        "cut": build_cut(
            events,
            cutoff=DAY.isoformat(),
            base=base or currency,
            valuation=valuation,
            case_id="case-fake" if scope else None,
            account_id=scope,
        ),
    }


def pair():
    return [account("Cuenta1", "100.01"), account("Cuenta2", "10", "USD")]


def result(entries=None, **kwargs):
    from operations_consolidation import consolidate_books

    return consolidate_books(entries or pair(), confirmed=True, **kwargs)


def test_exact_native_values_are_converted_once_and_partial_subtotal_is_distinct():
    report = result(fx=FX)
    assert report["nav"] == "300.11" and report["known_subtotal"] == "300.11"
    assert report["accounts"][1]["nav"] == "200.10"
    missing = result()
    assert missing["nav"] is None and missing["known_subtotal"] == "100.01"
    assert missing["accounts"][1]["nav"] is None
    other_base_cut = account("Cuenta1", "100.01", base="USD")
    assert result([other_base_cut, pair()[1]], fx=FX)["nav"] == "300.11"


def test_unconfirmed_has_no_financial_result_and_no_global_return_is_invented():
    from operations_consolidation import consolidate_books

    report = consolidate_books(pair(), fx=FX)
    assert report["nav"] is None and report["known_subtotal"] is None
    assert report["state"] == "PENDING_REVIEW"
    assert "twr" not in report and "xirr" not in report


@pytest.mark.parametrize("change", ["duplicate", "renamed", "scope", "cutoff", "alias", "source"])
def test_scope_and_duplicate_inputs_fail_closed(change):
    entries = pair()
    if change == "duplicate":
        entries[1]["cut"] = entries[0]["cut"]
    elif change == "renamed":
        entries[1] = account("Cuenta2", "100.01")
    elif change == "scope":
        entries[1] = account("Cuenta2", "10", scope="account-fake")
    elif change == "cutoff":
        entries[1]["cut"] = build_cut([], cutoff="2026-01-09", base="MXN")
    elif change == "alias":
        entries[1]["alias"] = "cuenta1"
    else:
        entries[1]["source"] = ""
    with pytest.raises(PortfolioError):
        result(entries, fx=FX)


def test_linked_accounts_must_belong_to_current_case_and_allowed_membership():
    entries = [account("Cuenta1", "100.01", scope="a"), account("Cuenta2", "10", "USD", scope="b")]
    assert result(entries, fx=FX, case_id="case-fake", allowed_accounts={"a", "b"})["nav"] == "300.11"
    for kwargs in (
        {"case_id": "other", "allowed_accounts": {"a", "b"}},
        {"case_id": "case-fake", "allowed_accounts": {"a"}},
    ):
        with pytest.raises(PortfolioError):
            result(entries, fx=FX, **kwargs)


@pytest.mark.parametrize(
    "row",
    [
        "2026-01-09,USD,MXN,20.01,Fuente",
        "2026-01-10,USD,MXN,0,Fuente",
        "2026-01-10,USD,MXN,1e999999999,Fuente",
        "2026-01-10,USD,MXN,20.01,",
        "2026-01-10,USD,USD,20.01,Fuente",
    ],
)
def test_bad_fx_does_not_create_a_value(row):
    with pytest.raises(PortfolioError):
        result(fx=("Fecha,Moneda,Base,Tasa,Fuente\n" + row + "\n").encode())


def transfer_pair(*, incoming="10", settled=DAY):
    return [
        account(
            "Cuenta1", "110.01", extra=[Event("out", DAY, DAY, "TRANSFER_OUT", amount=10, reference="r")]
        ),
        account(
            "Cuenta2",
            "190.10",
            extra=[Event("in", DAY, settled, "TRANSFER_IN", amount=D(incoming), reference="r")],
        ),
    ]


LINK = b"CuentaSalida,IDSalida,CuentaEntrada,IDEntrada,Fuente\nCuenta1,out,Cuenta2,in,Comprobante ficticio\n"


def test_transfer_candidate_is_not_evidence_and_never_subtracted_from_wealth():
    pending = result(transfer_pair())
    assert pending["nav"] == "300.11"
    assert all(t["state"] == "PENDING" for t in pending["transfers"])
    linked = result(transfer_pair(), links=LINK)
    assert linked["nav"] == "300.11"
    assert all(t["state"] == "DOCUMENTED_INTERNAL" for t in linked["transfers"])
    assert linked["transfers"][0]["source"] == "Comprobante ficticio"


@pytest.mark.parametrize(
    "entries", [transfer_pair(incoming="10.01"), transfer_pair(settled=date(2026, 1, 11))]
)
def test_cent_or_settlement_difference_stays_pending(entries):
    report = result(entries, links=LINK)
    assert all(t["state"] == "PENDING" for t in report["transfers"])
    assert any("difer" in t["reason"].lower() for t in report["transfers"])


def test_link_cannot_reuse_leg_or_omit_source():
    for links in (LINK + LINK.split(b"\n")[1] + b"\n", LINK.replace(b"Comprobante ficticio", b"")):
        with pytest.raises(PortfolioError):
            result(transfer_pair(), links=links)


@pytest.mark.parametrize("raw", [None, 123, [1], "not bytes"])
def test_malformed_cut_inputs_have_controlled_errors(raw):
    entries = pair()
    entries[0]["cut"] = raw
    with pytest.raises(PortfolioError):
        result(entries)


def test_missing_link_leg_and_ambiguous_candidates_remain_pending():
    missing = result(transfer_pair(), links=LINK.replace(b",in,", b",absent,"))
    assert all(t["state"] == "PENDING" for t in missing["transfers"])
    entries = transfer_pair()
    entries.append(
        account("Cuenta3", "30", extra=[Event("in-2", DAY, DAY, "TRANSFER_IN", amount=10, reference="r")])
    )
    report = result(entries)
    assert all(not t["candidate"] and t["state"] == "PENDING" for t in report["transfers"])


def test_internal_transfer_keeps_fees_taxes_and_unknown_timing():
    entries = [
        account(
            "Cuenta1",
            "110.01",
            extra=[
                Event("out", DAY, DAY, "TRANSFER_OUT", amount=10, fee=D(".01"), tax=D(".02"), reference="r")
            ],
        ),
        account("Cuenta2", "190.10", extra=[Event("in", DAY, DAY, "TRANSFER_IN", amount=10, reference="r")]),
    ]
    report = result(entries, links=LINK)
    assert report["nav"] == "300.08"
    assert report["transfers"][0]["fee"] == "0.01" and report["transfers"][0]["timing"] == "UNKNOWN"


def test_different_currency_and_in_kind_are_not_assumed_internal():
    entries = transfer_pair()
    entries[1] = account(
        "Cuenta2",
        "10",
        "USD",
        extra=[Event("in", DAY, DAY, "TRANSFER_IN", currency="USD", amount=10, reference="r")],
    )
    assert all(t["state"] == "PENDING" for t in result(entries, fx=FX, links=LINK)["transfers"])


def test_bundle_bound_scope_cannot_be_imported_as_temporary():
    from operations_consolidation_bundle import build_bundle, read_bundle

    entries = [account("Cuenta1", "100.01", scope="a"), account("Cuenta2", "10", "USD", scope="b")]
    raw = build_bundle(entries, fx=FX, case_id="case-fake", allowed_accounts={"a", "b"})
    with pytest.raises(PortfolioError):
        read_bundle(raw)
    with pytest.raises(PortfolioError):
        read_bundle(raw, case_id="case-fake", allowed_accounts={"a"})


def test_unvalued_repo_never_becomes_principal_and_known_cash_remains_visible():
    entries = pair()
    entries[0] = account(
        "Cuenta1",
        "100.01",
        valued=False,
        extra=[Event("repo", DAY, DAY, "OPEN_REPO", asset="BONO", reference="R", amount=200)],
    )
    report = result(entries, fx=FX)
    assert report["nav"] is None and report["known_subtotal"] == "300.11"
    assert next(r for r in report["detail"] if r["section"] == "repos")["native"] is None


def test_large_values_keep_cent_and_zero_or_negative_nav_is_not_replaced():
    assert (
        result([account("Cuenta1", "100000000000000.01"), account("Cuenta2", "0.02")])["nav"]
        == "100000000000000.03"
    )
    report = result(
        [
            account("Cuenta1", "10", extra=[Event("w", DAY, DAY, "WITHDRAWAL", amount=11)]),
            account("Cuenta2", "0.5"),
        ]
    )
    assert report["nav"] == "-0.5" and all(r["weight"] is None for r in report["detail"])


def test_bundle_roundtrip_is_data_only_and_rechecks_scope_and_integrity():
    from operations_consolidation_bundle import build_bundle, read_bundle

    raw = build_bundle(pair(), fx=FX)
    saved = read_bundle(raw)
    assert saved["entries"] == pair() and saved["fx"] == FX
    assert saved["review_state"] == "PENDING_REVIEW"
    with ZipFile(BytesIO(raw)) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["accounts/Cuenta1.cut.json"] += b" "
    bad = BytesIO()
    with ZipFile(bad, "w", ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
    with pytest.raises(PortfolioError):
        read_bundle(bad.getvalue())


@pytest.mark.parametrize("name", ["../private", "/absolute", "accounts/evil.pdf", "consolidation.json"])
def test_bundle_rejects_unknown_paths_and_duplicate_manifest(name):
    from operations_consolidation_bundle import build_bundle, read_bundle

    raw = build_bundle(pair(), fx=FX)
    stream = BytesIO(raw)
    with ZipFile(stream, "a", ZIP_DEFLATED) as z:
        z.writestr(name, b"{}")
    with pytest.raises(PortfolioError):
        read_bundle(stream.getvalue())


def test_report_exports_share_snapshot_and_escape_spreadsheet_text():
    from operations_consolidation_report import report_csv, report_text

    entries = pair()
    entries[0]["source"] = "=ficticio"
    report = result(entries, fx=FX)
    before = json.dumps(report, sort_keys=True)
    assert "300.11" in report_text(report) and b"300.11" in report_csv(report)
    assert b"'=ficticio" in report_csv(report)
    assert json.dumps(report, sort_keys=True) == before


def test_manual_historical_wealth_renews_confirmation_after_input_change():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_ui import _wealth
def upload(label, *args, **kwargs):
    if label.startswith("Cierres por cuenta"):
        ending = st.session_state.get("ending", "100")
        data = "Fecha,Cuenta,Moneda,NAV\\n2026-01-01,A,MXN,100\\n2026-01-10,A,MXN,"+ending+"\\n"
        return BytesIO(data.encode())
    if label.startswith("Flujos:"):
        return BytesIO(b"Fecha,Cuenta,Tipo,Moneda,Importe,Referencia,MomentoFlujo,FXBase,FuenteFX\\n")
    return None
with patch("streamlit.file_uploader", side_effect=upload):
    _wealth((None,None,None,None))
""").run(timeout=30)
    label = "Concilié los cierres y todos los flujos del patrimonio, con FX al momento de cada flujo"
    check = next(c for c in app.checkbox if c.label == label)
    check.check().run(timeout=30)
    assert next(c for c in app.checkbox if c.label == label).value is True
    app.session_state["ending"] = "110"
    app.run(timeout=30)
    assert not app.exception
    assert next(c for c in app.checkbox if c.label == label).value is False


def test_fx_form_submits_current_values_not_previous_render_values():
    from streamlit.testing.v1 import AppTest

    entries = repr(pair())
    code = """
import streamlit as st
from operations_consolidation_ui import render_consolidation,group_scope
context=(None,None,None,None)
root="consolidation_"+group_scope(context)
st.session_state.setdefault(root,{"token":"fictional","proposal":{"entries":ENTRIES}})
st.session_state.setdefault(root+"_panel",True)
render_consolidation(context)
""".replace("ENTRIES", entries)
    app = AppTest.from_string(code).run(timeout=30)
    assert not app.exception
    next(t for t in app.text_input if t.label == "Tasa FX del corte").input("20.01")
    next(t for t in app.text_input if t.label == "Fuente FX del grupo").input("Fuente ficticia actual")
    next(b for b in app.button if b.label == "Añadir FX al CSV").click().run(timeout=30)
    assert not app.exception
    value = next(t for t in app.text_area if t.label == "FX documentado del grupo CSV").value
    assert "2026-01-10,USD,MXN,20.01,Fuente ficticia actual" in value


def test_corrupt_compressed_stream_has_controlled_rejection():
    import struct

    from operations_consolidation_bundle import build_bundle, read_bundle

    raw = bytearray(build_bundle(pair(), fx=FX))
    with ZipFile(BytesIO(raw)) as archive:
        info = archive.getinfo("consolidation.json")
        name_size, extra_size = struct.unpack_from("<HH", raw, info.header_offset + 26)
        offset = info.header_offset + 30 + name_size + extra_size
    raw[offset] = 7  # Reserved DEFLATE block type; malformed compressed bytes, not just bad CRC.
    with pytest.raises(PortfolioError):
        read_bundle(bytes(raw))


def test_transfer_form_submits_current_selection_and_source():
    from streamlit.testing.v1 import AppTest

    entries = [
        account(
            "Cuenta1",
            "120",
            extra=[
                Event("out", DAY, DAY, "TRANSFER_OUT", amount=10, reference="r"),
                Event("out2", DAY, DAY, "TRANSFER_OUT", amount=5, reference="q"),
            ],
        ),
        account(
            "Cuenta2",
            "80",
            extra=[
                Event("in", DAY, DAY, "TRANSFER_IN", amount=10, reference="r"),
                Event("in2", DAY, DAY, "TRANSFER_IN", amount=5, reference="q"),
            ],
        ),
    ]
    code = """
import streamlit as st
from operations_consolidation_ui import render_consolidation,group_scope
context=(None,None,None,None)
root="consolidation_"+group_scope(context)
st.session_state.setdefault(root,{"token":"fictional","proposal":{"entries":ENTRIES}})
st.session_state.setdefault(root+"_panel",True)
render_consolidation(context)
""".replace("ENTRIES", repr(entries))
    app = AppTest.from_string(code).run(timeout=30)
    assert not app.exception
    next(t for t in app.selectbox if t.label == "Pata de salida").select(("Cuenta1", "out2"))
    next(t for t in app.selectbox if t.label == "Pata de entrada").select(("Cuenta2", "in2"))
    next(t for t in app.text_input if t.label == "Fuente del vínculo entre cuentas").input(
        "Fuente ficticia actual"
    )
    next(b for b in app.button if b.label == "Añadir vínculo al CSV").click().run(timeout=30)
    assert not app.exception
    value = next(t for t in app.text_area if t.label == "Vínculos documentados CSV").value
    assert "Cuenta1,out2,Cuenta2,in2,Fuente ficticia actual" in value


def test_negative_csv_values_remain_numbers_while_text_is_escaped():
    import csv
    from io import StringIO

    from operations_consolidation_report import report_csv

    report = result(
        [
            account("Cuenta1", "10", extra=[Event("w", DAY, DAY, "WITHDRAWAL", amount=11)]),
            account("Cuenta2", "0.5"),
        ]
    )
    rows = list(csv.reader(StringIO(report_csv(report).decode("utf-8-sig"))))
    assert rows[0][5] == "-0.5"
    assert next(r for r in rows if len(r) == 9 and r[:3] == ["Cuenta1", "cash", "cash"])[4] == "-1"


def test_collapsing_group_preserves_edits_as_unconfirmed_proposals():
    from streamlit.testing.v1 import AppTest

    from operations_consolidation_ui import group_scope

    root = "consolidation_" + group_scope((None, None, None, None))
    code = """
import streamlit as st
from operations_consolidation_ui import render_consolidation,group_scope
context=(None,None,None,None)
root="consolidation_"+group_scope(context)
st.session_state.setdefault(root,{"token":"fictional","proposal":{"entries":ENTRIES}})
st.session_state.setdefault(root+"_panel",True)
render_consolidation(context)
""".replace("ENTRIES", repr(pair()))
    app = AppTest.from_string(code).run(timeout=30)
    next(t for t in app.text_input if t.label == "Fuente de pertenencia de cuenta 1").input(
        "Fuente ficticia editada"
    ).run(timeout=30)
    app.session_state[root + "_panel"] = False
    app.run(timeout=30)
    app.session_state[root + "_panel"] = True
    app.run(timeout=30)
    assert not app.exception
    assert (
        next(t for t in app.text_input if t.label == "Fuente de pertenencia de cuenta 1").value
        == "Fuente ficticia editada"
    )
