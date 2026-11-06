"""Synthetic account research: costs, unknown data, portable runs and account isolation."""

import json
from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet

from account_demo import demo_account
from account_workflow import (
    AccountSettings,
    account_pdf,
    compare_account_cuts,
    make_run_bundle,
    read_run_bundle,
    run_account_analysis,
)
from analysis_session import analysis_key, session_compute
from case_workspace import CaseStore, Principal
from model_estimation import estimate_moments
from portfolio_core import PortfolioError
from portfolio_exposure import analyze_exposure, read_components
from simulation import simulate_portfolio_paths


@pytest.fixture
def account():
    files, metadata, defaults = demo_account()
    settings = AccountSettings(**defaults, goal_amount=110000, goal_months=3, paths=100)
    return files, metadata, settings


def test_unknown_costs_stay_unknown_and_partial_change_has_less_turnover(account):
    files, metadata, settings = account
    result = run_account_analysis(files, settings, metadata)
    table = result["comparison"].set_index("Alternativa")
    assert table.loc["Conservar", "Costo del cambio MXN"] == 0
    assert pd.isna(table.loc["Cambio parcial", "Costo del cambio MXN"])
    assert table.loc["Cambio parcial", "Rotación"] == pytest.approx(
        settings.partial_fraction * table.loc["Mínima volatilidad", "Rotación"]
    )
    assert any("Tarifario sin confirmar" in item for item in result["pending"])
    assert result["exposure"]["coverage"] == pytest.approx(0.97)


def test_goal_charges_switching_once_and_keeps_external_cash_in_the_scope(account):
    files, metadata, settings = account
    settings = replace(
        settings,
        costs_confirmed=True,
        cost_source="Tarifa ficticia",
        cost_date=date.today().isoformat(),
        commission_bps=25,
        vat_rate=0.16,
        annual_fixed_cost=120,
    )
    result = run_account_analysis(files, settings, metadata)
    table = result["comparison"].set_index("Alternativa")
    for alternative, simulation in result["simulations"].items():
        cost = table.loc[alternative, "Costo del cambio MXN"]
        assert simulation.monthly_values[0] == pytest.approx(np.repeat(105000 - cost, settings.paths))
    assert table.loc["Conservar", "Costo del cambio MXN"] == 0
    assert table.loc["Conservar", "Costo recurrente anual MXN"] == 120
    assert result["goals"]["Probabilidad simulada de alcanzar meta"].between(0, 1).all()


def test_unfunded_alternative_is_not_simulated(account):
    files, metadata, settings = account
    settings = replace(
        settings,
        outside_cash=0,
        costs_confirmed=True,
        commission_bps=25,
        cost_source="Ejemplo",
        cost_date=date.today().isoformat(),
    )
    result = run_account_analysis(files, settings, metadata)
    assert "Conservar" in result["simulations"]
    assert "Mínima volatilidad" not in result["simulations"]
    assert pd.isna(
        result["goals"]
        .set_index("Alternativa")
        .loc["Mínima volatilidad", "Probabilidad simulada de alcanzar meta"]
    )


def test_run_roundtrip_is_deterministic_binds_account_and_contains_inputs(account, tmp_path):
    files, metadata, settings = account
    result = run_account_analysis(files, settings, metadata)
    store = CaseStore(tmp_path / "workflow.db", Fernet.generate_key())
    admin = Principal("test", "admin", "ADMIN")
    store.initialize(admin)
    case = store.create(admin, "Caso sintético")
    state = store.update(
        admin,
        case["id"],
        1,
        "account",
        {"broker": "GBM", "product": "Trading MX", "portfolio": "Prueba", "currency": "MXN"},
    )
    account_id = state["accounts"][0]["id"]
    manifest, bundle = make_run_bundle(
        files, settings, metadata, result, case_id=case["id"], account_id=account_id
    )
    _, again = make_run_bundle(
        files,
        settings,
        metadata,
        result,
        case_id=case["id"],
        account_id=account_id,
        run_id=manifest["run_id"],
    )
    assert bundle == again
    artifact = store.attach(
        admin, case["id"], state["revision"], "cartera_run_test.zip", bundle, account_id=account_id
    )
    assert b"SIM-A" not in (tmp_path / "workflow.db").read_bytes()
    _, raw = store.artifact(admin, case["id"], artifact)
    opened, inputs, restored = read_run_bundle(raw, case_id=case["id"], account_id=account_id)
    assert restored == settings and inputs == files and opened == manifest
    with pytest.raises(PortfolioError, match="otro expediente"):
        read_run_bundle(raw, case_id=case["id"], account_id="wrong-account")
    reproduced = run_account_analysis(inputs, restored, opened["metadata"])
    np.testing.assert_array_equal(
        result["alternatives"][2].metrics.weights, reproduced["alternatives"][2].metrics.weights
    )
    pdf = account_pdf(result, settings, run_id=manifest["run_id"])
    assert pdf.startswith(b"%PDF")
    with_pdf, report_bundle = make_run_bundle(files, settings, metadata, result, pdf=pdf)
    assert read_run_bundle(report_bundle)[0]["report_sha256"] == with_pdf["report_sha256"]
    with ZipFile(BytesIO(report_bundle)) as archive:
        assert archive.read("report.pdf") == pdf


@pytest.mark.parametrize("change", ["input", "summary", "extra_path"])
def test_run_rejects_corruption_and_unexpected_members(account, change):
    files, metadata, settings = account
    result = run_account_analysis(files, settings, metadata)
    _, bundle = make_run_bundle(files, settings, metadata, result)
    output = BytesIO()
    with ZipFile(BytesIO(bundle)) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for name in original.namelist():
            value = original.read(name)
            if change == "input" and name == "inputs/holdings":
                value = value.replace(b"40000", b"50000")
            if change == "summary" and name == "run.json":
                payload = json.loads(value)
                payload["summary"]["positions"]["SIM-A"] = 1
                value = json.dumps(payload).encode()
            changed.writestr(name, value)
        if change == "extra_path":
            changed.writestr("../../private.txt", b"bad")
    with pytest.raises(PortfolioError):
        read_run_bundle(output.getvalue())


def test_changed_inputs_cannot_be_archived_as_previous_result(account):
    files, metadata, settings = account
    result = run_account_analysis(files, settings, metadata)
    with pytest.raises(PortfolioError, match="cambiaron"):
        make_run_bundle(files, replace(settings, risk_free_rate=0.01), metadata, result)


def test_cuts_compare_values_and_weights_without_misreporting_return(account):
    files, metadata, settings = account
    result = run_account_analysis(files, settings, metadata)
    before, _ = make_run_bundle(files, settings, metadata, result, case_id="case", account_id="account")
    after = json.loads(json.dumps(before))
    after["summary"]["as_of"] = (date.fromisoformat(settings.as_of) + timedelta(days=1)).isoformat()
    after["summary"]["positions"]["SIM-A"] += 10000
    table = compare_account_cuts(before, after).set_index("Instrumento")
    assert table.loc["SIM-A", "Cambio de valuación MXN"] == 10000
    assert not any("rendimiento" in column.lower() or "retorno" in column.lower() for column in table.columns)
    after["account_id"] = "other"
    with pytest.raises(PortfolioError, match="misma cuenta"):
        compare_account_cuts(before, after)


def test_exposure_combines_direct_and_indirect_and_preserves_unknown(account):
    files, metadata, settings = account
    components = read_components(files["components"], settings.assets)
    result = analyze_exposure(settings.assets, [0.4, 0.3, 0.3], metadata, components)
    assert result["aggregates"]["Emisor"]["Emisor ficticio A"] == pytest.approx(0.58)
    assert result["aggregates"]["Emisor"]["Sin cobertura"] == pytest.approx(0.03)
    assert result["overlap"].loc["Emisor ficticio A", "Vehiculos"] == 2
    assert result["detail"]["Peso"].sum() == pytest.approx(1)
    future = files["components"].replace(settings.as_of.encode(), b"2099-01-01")
    with pytest.raises(PortfolioError):
        read_components(future, settings.assets)


def test_fixed_fees_reduce_wealth_exactly_and_record_unpaid_fees():
    returns = pd.DataFrame({"A": np.zeros(100)})
    result = simulate_portfolio_paths(
        returns, [1], initial_value=1000, months=3, paths=100, monthly_fixed_fee=10, rebalance_months=None
    )
    assert result.monthly_values[-1] == pytest.approx(np.repeat(970, 100))
    depleted = simulate_portfolio_paths(
        returns, [1], initial_value=10, months=3, paths=100, monthly_fixed_fee=10, rebalance_months=None
    )
    assert np.all(depleted.monthly_values[-1] == 0)
    assert np.all(depleted.unpaid_fees == 20)


def test_external_cash_can_be_exempt_from_proportional_management_costs():
    returns = pd.DataFrame({"A": np.zeros(100), "Cash": np.zeros(100)})
    result = simulate_portfolio_paths(
        returns,
        [0.5, 0.5],
        initial_value=1000,
        months=1,
        paths=100,
        annual_fee=0.12,
        rebalance_months=None,
        fee_exempt_assets=(1,),
    )
    expected = 500 + 500 * (1 - 0.12) ** (1 / 12)
    assert result.monthly_values[-1] == pytest.approx(np.repeat(expected, 100))


def test_session_memo_does_not_share_mutation_or_ignore_input_changes():
    state, calls = {}, []

    def compute():
        calls.append(True)
        return pd.DataFrame({"A": [1]})

    first = session_compute(state, "test", analysis_key("one"), compute)
    first.iloc[0, 0] = 99
    assert session_compute(state, "test", analysis_key("one"), compute).iloc[0, 0] == 1
    session_compute(state, "test", analysis_key("two"), compute)
    session_compute({}, "test", analysis_key("one"), compute)
    assert len(calls) == 3


def test_calibration_never_silently_falls_back_to_sample():
    rng = np.random.default_rng(2)
    returns = pd.DataFrame(rng.normal(0, 0.01, (80, 2)), index=pd.bdate_range("2025-01-01", periods=80))
    with pytest.raises(PortfolioError, match="100 retornos"):
        estimate_moments(returns)
    assert estimate_moments(returns, "sample").shrinkage == 0


def test_private_session_is_cleared_when_authorized_identity_changes():
    from access import isolate_session_identity

    state = {"private_holdings": ["previous account"]}
    claims = {"iss": "test", "sub": "first"}
    isolate_session_identity(state, claims)
    assert "private_holdings" not in state
    state["private_holdings"] = ["first account"]
    isolate_session_identity(state, claims)
    assert state["private_holdings"] == ["first account"]
    isolate_session_identity(state, {"iss": "test", "sub": "second"})
    assert "private_holdings" not in state
