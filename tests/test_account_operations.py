"""Economic, privacy and failure-path checks with fictional accounts only."""

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet

from account_drafts import draft_payload, restore_draft, run_options
from case_workspace import CaseStore, Principal, WorkspaceError
from executable_allocation import cost_aware_target, executable_plan
from gbm_documents import confirm_statement, read_statement
from implementation_costs import ImplementationCostAssumptions
from instrument_catalogue import read_catalogue
from multi_currency_wealth import consolidate_wealth, match_internal_flows
from operations_jobs import refresh_subscription
from portfolio_core import PortfolioError
from realized_performance import Flow, performance, xirr
from transaction_ledger import Event, book_at, merge_events, value_book

D = date(2026, 1, 1)


def event(identifier, kind, **kwargs):
    return Event(identifier, D, D, kind, **kwargs)


def test_trade_date_nav_and_settlement_cash_do_not_double_count_payable():
    deposit = event("1", "OPEN_CASH", amount=1000)
    buy = replace(
        event("2", "BUY", asset="SIM", quantity=3, price=100, amount=300, fee=2),
        settled=D + timedelta(days=2),
    )
    before = book_at([deposit, buy], D)
    assert before["cash"]["MXN"] == 1000 and before["pending"]["MXN"] == -302
    assert value_book(before, {("SIM", "MXN"): 100}, {}, raw_prices_confirmed=True)["nav"] == 998
    after = book_at([deposit, buy], D + timedelta(days=2))
    assert after["cash"]["MXN"] == 698 and not after["pending"]
    assert value_book(after, {("SIM", "MXN"): 100}, {}, raw_prices_confirmed=True)["nav"] == 998


def test_dividend_fee_split_and_fx_valuation_are_separate():
    entries = [
        event("1", "OPEN_POSITION", asset="SIM", currency="USD", quantity=2),
        event("2", "DIVIDEND", currency="USD", amount=5, tax=1),
        event("3", "SPLIT", asset="SIM", currency="USD", quantity=2),
    ]
    book = book_at(entries, D)
    assert book["positions"][("SIM", "USD")] == 4
    with pytest.raises(PortfolioError, match="tipo de cambio"):
        value_book(book, {("SIM", "USD"): 50}, {}, raw_prices_confirmed=True)
    assert (
        value_book(book, {("SIM", "USD"): 50}, {("USD", "MXN"): 20}, raw_prices_confirmed=True)["nav"] == 4080
    )
    with pytest.raises(PortfolioError, match="sin ajuste"):
        value_book(book, {("SIM", "USD"): 50}, {("USD", "MXN"): 20})


def test_ledger_idempotency_and_inconsistent_trade_rejected():
    row = event("1", "DEPOSIT", amount=50)
    assert len(merge_events([row], [row])) == 1
    with pytest.raises(PortfolioError, match="mismo ID"):
        merge_events([row], [replace(row, amount=51)])
    with pytest.raises(PortfolioError, match="reproduce"):
        event("2", "BUY", asset="SIM", quantity=2, price=10, amount=30)
    with pytest.raises(PortfolioError, match="corta"):
        book_at([event("1", "SELL", asset="SIM", quantity=1, price=10, amount=10)], D)


def test_deposit_is_not_profit_and_unknown_flow_timing_blocks_twr():
    nav = pd.Series([100, 200], index=[D, D + timedelta(days=1)])
    result = performance(nav, [Flow(D + timedelta(days=1), 100, "EOD")])
    assert result["twr"] == 0 and result["gain"] == 0
    assert result["xirr"] == pytest.approx(0, abs=1e-8)
    assert performance(nav, [Flow(D + timedelta(days=1), 100)])["twr"] is None


def test_bod_flow_participates_in_return_and_missing_flow_valuation_blocks_twr():
    nav = pd.Series([100, 220], index=[D, D + timedelta(days=1)])
    assert performance(nav, [Flow(D + timedelta(days=1), 100, "BOD")])["twr"] == pytest.approx(0.1)
    monthly = pd.Series([100, 220], index=[D, D + timedelta(days=30)])
    assert performance(monthly, [Flow(D + timedelta(days=15), 100, "EOD")])["twr"] is None


def test_xirr_uses_actual_dates_and_flags_possible_multiple_roots():
    assert xirr([(D, -100), (D + timedelta(days=365), 110)])["value"] == pytest.approx(0.1)
    assert (
        xirr([(D, -100), (D + timedelta(days=365), 230), (D + timedelta(days=730), -132)])["status"]
        == "MULTIPLES_RAICES_POSIBLES"
    )


def positions():
    return pd.DataFrame(
        {"Instrumento": ["SIM-A", "SIM-B"], "Cantidad": [10, 0], "Precio": [10, 10], "Lote": [1, 1]}
    )


def test_lot_solver_funds_costs_and_respects_turnover_and_cash_floor():
    result = executable_plan(
        positions(),
        10,
        [0.5, 0.5],
        ImplementationCostAssumptions(10, 5, 0.16, 1),
        cash_floor=5,
        max_turnover=0.8,
        quotes_confirmed=True,
    )
    detail = result["detail"]
    assert result["cash"] >= 5 and result["turnover"] <= 0.8 + 1e-8
    assert result["cost"] > 0
    assert result["cash"] == pytest.approx(
        10 - (detail["Títulos a operar"] * detail["Precio"]).sum() - result["cost"]
    )
    assert np.equal(detail["Títulos a operar"] % detail["Lote"], 0).all()


def test_lot_solver_does_not_trade_without_turnover_or_unfunded_minimum_fee():
    result = executable_plan(positions(), 0, [0, 1], max_turnover=0, quotes_confirmed=True)
    assert (result["detail"]["Títulos a operar"] == 0).all()
    expensive = executable_plan(
        positions(), 0, [0, 1], ImplementationCostAssumptions(minimum_commission=500), quotes_confirmed=True
    )
    assert (expensive["detail"]["Títulos a operar"] == 0).all()
    with pytest.raises(PortfolioError):
        executable_plan(positions(), 0, [0.5, 0.5], max_turnover=0, max_weight=0.5, quotes_confirmed=True)


def test_cost_aware_target_and_turnover_cap():
    target = cost_aware_target([0.03, 0.2], np.diag([0.01, 0.01]), [1, 0], max_turnover=0.2)
    assert np.abs(target - [1, 0]).sum() <= 0.200001
    assert target[1] > 0


@pytest.fixture
def context(tmp_path):
    store = CaseStore(tmp_path / "cases.db", Fernet.generate_key())
    admin = Principal("https://issuer.test", "admin", "ADMIN")
    analyst = Principal("https://issuer.test", "analyst", "ANALYST")
    stranger = Principal("https://issuer.test", "other", "ANALYST")
    store.initialize(admin)
    state = store.create(analyst, "Synthetic")
    state = store.update(
        analyst,
        state["id"],
        state["revision"],
        "account",
        {"broker": "GBM", "product": "Trading MX", "portfolio": "SIM", "currency": "MXN"},
    )
    return store, admin, analyst, stranger, state, state["accounts"][0]["id"]


def test_working_data_is_encrypted_owner_bound_revision_safe_and_restorable(context, tmp_path):
    store, admin, analyst, other, state, account = context
    version = store.save_working(
        analyst, state["id"], account, "draft", "analysis", {"canary": "PRIVATE-555"}
    )
    assert version == 1 and b"PRIVATE-555" not in store.path.read_bytes()
    assert store.read(analyst, state["id"])["revision"] == state["revision"]
    with pytest.raises(WorkspaceError):
        store.working_records(other, state["id"], account, "draft")
    store.grant(admin, state["id"], other)
    assert store.working_records(other, state["id"], account, "draft") == []
    with pytest.raises(WorkspaceError, match="versión operativa"):
        store.save_working(analyst, state["id"], account, "draft", "analysis", {})
    assert store.backup(admin, tmp_path / "backup.db")["integrity"] == "VERIFIED"
    restored = CaseStore(tmp_path / "backup.db", store._key)
    assert (
        restored.working_records(analyst, state["id"], account, "draft")[0]["data"]["canary"] == "PRIVATE-555"
    )
    store.revoke(admin, state["id"], analyst)
    with pytest.raises(WorkspaceError):
        store.working_records(analyst, state["id"], account, "draft")


def test_working_ciphertext_swap_rejected(context):
    store, _, actor, _, state, account = context
    for name in ("a", "b"):
        store.save_working(actor, state["id"], account, "draft", name, {"value": name})
    with sqlite3.connect(store.path) as db:
        token = db.execute("SELECT token FROM working_records WHERE name='a'").fetchone()[0]
        db.execute("UPDATE working_records SET token=? WHERE name='b'", (token,))
    with pytest.raises(WorkspaceError):
        store.working_records(actor, state["id"], account, "draft")


def test_refresh_preserves_last_good_data_and_deduplicates_failure_alerts(context, tmp_path):
    store, _, actor, _, state, account = context
    feed = tmp_path / "quotes.csv"
    feed.write_text("Fecha,Instrumento,Precio,Moneda\n2026-01-01,SIM,10,MXN\n", encoding="utf-8")
    sources = {
        "approved": {
            "path": str(feed),
            "approved_folder": str(tmp_path),
            "kind": "quotes",
            "rights_valid_until": "2027-01-01",
            "price_basis": "raw",
        }
    }
    store.save_working(
        actor,
        state["id"],
        account,
        "subscription",
        "approved",
        {"enabled": True, "source_id": "approved", "max_age_days": 7, "interval_minutes": 60},
    )

    def refresh(now):
        record = store.working_records(actor, state["id"], account, "subscription")[0]
        return refresh_subscription(store, actor, state["id"], account, record, sources, now=now, force=True)

    assert not refresh(datetime(2026, 1, 2, tzinfo=UTC))["stale"]
    good = store.working_records(actor, state["id"], account, "feed")[0]["data"]["bytes"]
    feed.write_text("invalid", encoding="utf-8")
    assert refresh(datetime(2026, 1, 3, tzinfo=UTC))["status"] == "REFRESH_FAILED"
    assert store.working_records(actor, state["id"], account, "feed")[0]["data"]["bytes"] == good
    refresh(datetime(2026, 1, 4, tzinfo=UTC))
    alerts = store.working_records(actor, state["id"], account, "alert")
    assert len(alerts) == 1 and alerts[0]["version"] == 1


def test_multicurrency_wealth_and_internal_transfer_matching():
    frame = pd.DataFrame(
        {
            "Fecha": [str(D)] * 2,
            "Cuenta": ["a", "b"],
            "Instrumento": ["SIM", "CASH"],
            "Moneda": ["MXN", "USD"],
            "Valor": [100, 10],
            "EmisorID": ["ISSUER-SIM", ""],
        }
    )
    fx = pd.DataFrame(
        {"Fecha": [str(D)], "Moneda": ["USD"], "Base": ["MXN"], "Tasa": [20], "Fuente": ["SIM"]}
    )
    assert consolidate_wealth(frame, fx, cutoff=D)["nav"] == 300
    with pytest.raises(PortfolioError):
        consolidate_wealth(frame, pd.DataFrame(), cutoff=D)
    with pytest.raises(PortfolioError):
        consolidate_wealth(frame, fx, cutoff=D, allowed_accounts={"a"})
    legs = pd.DataFrame(
        {
            "Fecha": [str(D)] * 2,
            "Cuenta": ["a", "b"],
            "Tipo": ["TRANSFER_OUT", "TRANSFER_IN"],
            "Moneda": ["MXN", "MXN"],
            "Importe": [100, 100],
            "Referencia": ["SIM-REF"] * 2,
        }
    )
    assert match_internal_flows(legs)["Estado"].eq("INTERNA_VERIFICADA").all()
    legs.loc[1, "Importe"] = 99
    assert match_internal_flows(legs)["Estado"].eq("SIN_PAREJA_VERIFICADA").all()


def test_catalogue_rejects_invalid_isin_and_future_date():
    header = "Instrumento,ISIN,Mercado,EmisorID,Emisor,Tipo,Sector,Pais,Moneda,Lote,Fecha,Fuente\n"
    row = "SIM,US0378331005,XNAS,LEI-SIM,Sim,Acción,Tech,US,USD,1,2026-01-01,synthetic\n"
    assert len(read_catalogue((header + row).encode(), cutoff=D)) == 1
    with pytest.raises(PortfolioError):
        read_catalogue((header + row.replace("US0378331005", "US0378331006")).encode(), cutoff=D)
    with pytest.raises(PortfolioError):
        read_catalogue((header + row).encode(), cutoff=date(2025, 1, 1))


def test_pdf_draft_keeps_provenance_and_requires_confirmation():
    from test_gbm_intake import _gbm_quantity_pdf

    from scripts.inspect_gbm_intake import IntakeError

    raw = _gbm_quantity_pdf()
    draft = read_statement(raw)
    assert draft["positions"][0]["Cantidad"] == "2"
    assert draft["positions"][0]["Pagina"] == 2 and draft["movement_candidates"]
    assert len(draft["cash_review"]) == draft["checks"]["cash_rows_checked"]
    assert all(row["EstadoRevision"] == "PENDIENTE" for row in draft["cash_review"])
    assert draft["cash_review"][0]["ControlAritmetico"] == "APERTURA_COTEJADA"
    with pytest.raises(IntakeError):
        confirm_statement(
            draft,
            contract_confirmed=False,
            currency_confirmed=True,
            differences_accepted=False,
            mapping={"SYMA": "SIM.MX"},
        )


def test_cash_review_preserves_cent_discrepancies_and_original_balances():
    from gbm_documents import _cash_review

    lines = [
        "01/01 SALDO INICIAL EN EFECTIVO 0.00 0.00 0.00 0.00 100.00",
        "02/02 DEPOSITO 0.00 0.00 0.00 10.00 110.01",
        "03/03 COMPRA 0.00 0.00 0.00 5.00 105.01",
    ]
    candidates = [
        {"Pagina": 2, "Fila": i + 1, "Texto": line, "sha256": sha256(line.encode()).hexdigest()}
        for i, line in enumerate(lines)
    ]
    review = _cash_review(candidates, "a" * 64)
    assert review[1]["SaldoEsperado"] == "110.00"
    assert review[1]["SaldoImpreso"] == "110.01"
    assert review[1]["Diferencia"] == "-0.01"
    assert review[1]["ControlAritmetico"] == "DIFERENCIA_CENTAVO"
    assert review[2]["SaldoAnteriorImpreso"] == "110.01"
    assert review[2]["SaldoEsperado"] == "105.01"
    assert review[2]["Diferencia"] == "0.00"
    assert review[2]["TextoOriginal"] == lines[2]
    assert all(row["EstadoRevision"] == "PENDIENTE" for row in review)
    assert len({row["ID"] for row in review}) == len(review)
    assert _cash_review(candidates, "b" * 64)[0]["ID"] != review[0]["ID"]


def test_private_review_packets_keep_values_and_refuse_public_output(tmp_path, monkeypatch):
    import json

    from test_gbm_intake import _gbm_quantity_pdf

    from scripts import run_private_pilot as pilot

    monkeypatch.setattr(pilot, "__file__", str(tmp_path / "scripts" / "run_private_pilot.py"))
    source = tmp_path / "synthetic.pdf"
    raw = _gbm_quantity_pdf()
    source.write_bytes(raw)
    with pytest.raises(ValueError, match="data/private"):
        pilot.write_review_packets([source], tmp_path / "public")
    assert not (tmp_path / "public").exists()
    destination = tmp_path / "data" / "private" / "review"
    result = pilot.write_review_packets([source], destination)
    assert result["status"] == "REQUIERE_REVISION_HUMANA"
    packet = result["packets"][0]
    draft = json.loads((destination / packet["json"]).read_text(encoding="utf-8"))
    assert packet["rows"] == len(draft["cash_review"])
    assert sum(packet["controls"].values()) == packet["rows"]
    assert draft["sha256"] == sha256(raw).hexdigest()
    assert source.read_bytes() == raw
    report = (destination / packet["markdown"]).read_text(encoding="utf-8")
    assert "no es un paquete de análisis" in report
    assert all(row["TextoOriginal"] in report for row in draft["cash_review"])


def test_drafts_roundtrip_and_archives_newest_first():
    payload = draft_payload(
        {
            "files": {"holdings": b"synthetic"},
            "metadata": {},
            "defaults": {},
            "demo": True,
            "import_review": None,
        }
    )
    assert restore_draft(payload)["files"]["holdings"] == b"synthetic"
    state = {
        "artifacts": [
            {"id": "older", "name": "cartera_run_a.zip", "account_id": "a", "added_in_revision": 2},
            {"id": "newer", "name": "cartera_run_b.zip", "account_id": "a", "added_in_revision": 3},
        ]
    }
    assert list(run_options(state, "a")) == ["newer", "older"]


def test_portable_backup_restores_cases_drafts_and_technical_database(context, tmp_path):
    from operational_backup import create_backup_bundle, verify_backup_bundle

    store, admin, actor, _, state, account = context
    store.save_working(actor, state["id"], account, "draft", "analysis", {"sensitive": "CANARY-2026"})
    technical = tmp_path / "technical.db"
    with sqlite3.connect(technical) as db:
        db.execute("CREATE TABLE sample (value TEXT)")
        db.execute("INSERT INTO sample VALUES ('CANARY-2026')")
    destination = tmp_path / "daily.sigbackup"
    result = create_backup_bundle(store, admin, destination, technical_path=technical)
    assert result["technical_included"] and result["encrypted"]
    assert b"CANARY-2026" not in destination.read_bytes()
    recovered = tmp_path / "recovered"
    verify_backup_bundle(store, admin, destination, restore_to=recovered)
    with sqlite3.connect(recovered / "technical.db") as db:
        assert db.execute("SELECT value FROM sample").fetchone()[0] == "CANARY-2026"
    with pytest.raises(WorkspaceError):
        verify_backup_bundle(store, admin, destination, restore_to=recovered)
    with pytest.raises(WorkspaceError):
        verify_backup_bundle(store, actor, destination)


def test_monitor_uses_common_raw_close_and_rejects_adjusted_prices():
    import base64

    from operations_jobs import monitor_drift

    data = {
        "price_basis": "raw",
        "bytes": base64.b64encode(
            b"Fecha,Instrumento,Precio,Moneda\n2026-01-02,A,20,MXN\n2026-01-02,B,10,MXN\n"
        ).decode(),
    }
    monitor = {
        "quantities": {"A": 1, "B": 1},
        "weights": {"A": 0.5, "B": 0.5},
        "tolerance": 0.1,
        "currency": "MXN",
        "as_of": "2026-01-01",
    }
    assert monitor_drift(data, monitor)["exceeded"]
    with pytest.raises(PortfolioError):
        monitor_drift({**data, "price_basis": "adjusted"}, monitor)
    with pytest.raises(PortfolioError):
        monitor_drift(data, {**monitor, "as_of": "2026-01-03"})


def test_consolidated_performance_removes_internal_transfers_and_requires_aligned_closes():
    from multi_currency_wealth import consolidated_performance

    nav = pd.DataFrame(
        {
            "Fecha": ["2026-01-01"] * 2 + ["2026-01-02"] * 2,
            "Cuenta": ["a", "b", "a", "b"],
            "Moneda": ["MXN"] * 4,
            "NAV": [100, 100, 50, 150],
        }
    )
    flows = pd.DataFrame(
        {
            "Fecha": ["2026-01-02"] * 2,
            "Cuenta": ["a", "b"],
            "Tipo": ["TRANSFER_OUT", "TRANSFER_IN"],
            "Moneda": ["MXN"] * 2,
            "Importe": [50, 50],
            "Referencia": ["PAIR"] * 2,
            "MomentoFlujo": ["EOD"] * 2,
            "FXBase": [1, 1],
            "FuenteFX": [""] * 2,
        }
    )
    result = consolidated_performance(nav, pd.DataFrame(), flows)
    assert result["performance"]["twr"] == 0 and result["performance"]["net_flow"] == 0
    with pytest.raises(PortfolioError, match="pareja"):
        consolidated_performance(nav, pd.DataFrame(), flows.iloc[:1])
    with pytest.raises(PortfolioError, match="calendario"):
        consolidated_performance(nav.iloc[:3], pd.DataFrame(), flows)


def test_fractional_lots_reserve_cash_for_cent_rounding():
    frame = pd.DataFrame({"Instrumento": ["SIM"], "Cantidad": [0], "Precio": [10.123456], "Lote": [0.01]})
    result = executable_plan(
        frame, 10, [1], ImplementationCostAssumptions(10, 5, 0.16), cash_floor=0, quotes_confirmed=True
    )
    assert result["cash"] >= 0
    assert result["cash"] == pytest.approx(10 - result["detail"]["Importe firmado"].sum() - result["cost"])
    assert (result["detail"]["Comisión e IVA"] * 100).round().tolist() == pytest.approx(
        (result["detail"]["Comisión e IVA"] * 100).tolist()
    )


def test_executable_csv_rejects_formula_labels_and_unreviewed_extra_columns():
    for frame in (
        positions().assign(Instrumento=["=EXTERNAL()", "SIM-B"]),
        positions().assign(Notes="=EXTERNAL()"),
    ):
        with pytest.raises(PortfolioError, match="exportación"):
            executable_plan(frame, 0, [0.5, 0.5], quotes_confirmed=True)
