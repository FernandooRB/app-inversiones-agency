import json
from dataclasses import asdict, replace
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from pypdf import PdfReader

from data_rights import RIGHTS_COLUMNS
from instrument_identity import IDENTITY_COLUMNS, valid_isin
from pilot_validation import evaluate_snapshot_model, review_cost_profile
from portfolio_core import PortfolioError
from scripts.run_snapshot_pilot import main
from snapshot_pilot import INPUT_ROLES, SnapshotSettings, prepare_snapshot, run_snapshot


def synthetic_isin(number):
    prefix = f"ZZ{number:09d}"
    return next(prefix + str(digit) for digit in range(10) if valid_isin(prefix + str(digit)))


@pytest.fixture
def pilot():
    dates = pd.bdate_range("2020-01-01", periods=180)
    assets = ("AAA", "BBB", "CCC")
    rng = np.random.default_rng(87)
    draws = rng.normal([0.0004, 0.0001, 0.0003], [0.012, 0.018, 0.009], (180, 3))
    prices = pd.DataFrame(100 * np.exp(np.cumsum(draws, axis=0)), index=dates, columns=assets)
    prices.index.name = "Fecha"
    cutoff = dates[-1].date()
    settings = SnapshotSettings(
        dates[0].date(),
        cutoff,
        assets,
        0.02,
        "Supuesto sintético de prueba",
        0.6,
        months=3,
        paths=100,
        block_days=7,
    )
    today = date.today().isoformat()

    def rights(source):
        return (
            ",".join(RIGHTS_COLUMNS)
            + "\n"
            + f"{source},Prueba sintética,BMV,{today},,CONFIRMADO,INVESTIGACION_INTERNA,"
            + "AJUSTADO,Cierre local,Datos sintéticos propios\n"
        ).encode()

    def identity(source):
        return (
            ",".join(IDENTITY_COLUMNS)
            + "\n"
            + "".join(
                f"{asset},{synthetic_isin(index)},BMV,{asset},BMV,MXN,CIERRE_LOCAL_AJUSTADO,{today},{source}\n"
                for index, asset in enumerate(assets, start=1)
            )
        ).encode()

    files = {
        "holdings": (
            f"FechaCorte,Instrumento,ValorMXN\n{cutoff},AAA,80000\n{cutoff},BBB,10000\n{cutoff},CCC,10000\n"
        ).encode(),
        "coverage": (
            "FechaCorte,ValorCarteraAnalizadaMXN,EfectivoFueraAnalisisMXN,"
            "PendienteLiquidacionMXN,OtrosFueraAnalisisMXN,TotalCuentaMXN,Fuente\n"
            f"{cutoff},100000,5000,0,0,105000,Cobertura sintética\n"
        ).encode(),
        "prices": prices.to_csv(date_format="%Y-%m-%d").encode(),
        "reference_prices": prices.to_csv(date_format="%Y-%m-%d").encode(),
        "rights": rights("Origen sintético principal"),
        "reference_rights": rights("Origen sintético de referencia"),
        "identity": identity("Catálogo sintético principal"),
        "reference_identity": identity("Catálogo sintético de referencia"),
    }
    return files, settings


def test_local_pipeline_keeps_cash_outside_and_caps_only_proposals(pilot):
    files, settings = pilot
    result = run_snapshot(prepare_snapshot(files, settings))
    assert len(result.alternatives) == 4
    assert result.alternatives[0].metrics.weights[0] == 0.8
    for alternative in result.alternatives:
        assert alternative.metrics.weights.sum() == pytest.approx(1)
        if alternative.name in {"Mínima volatilidad", "Máximo Sharpe"}:
            assert alternative.metrics.weights.max() <= settings.max_weight + 1e-7
        for simulation in result.simulations[alternative.name].values():
            assert simulation.monthly_values[0] == pytest.approx(np.repeat(100_000, settings.paths))
            assert simulation.monthly_values.shape == (settings.months + 1, settings.paths)
    summary = result.summary()
    assert summary["human_review_pending"]
    assert not summary["client_delivery_allowed"]
    assert not summary["historical_account_performance_calculated"]
    assert summary["fingerprints"] == {role: sha256(value).hexdigest() for role, value in files.items()}
    json.dumps(summary, allow_nan=False)


def test_future_quotes_do_not_change_estimation_or_simulation(pilot):
    files, settings = pilot
    baseline = run_snapshot(prepare_snapshot(files, settings))
    future_dates = pd.bdate_range(settings.as_of + timedelta(days=1), periods=30)
    extension = "".join(f"{day.date()},100000,500000,900000\n" for day in future_dates).encode()
    changed = dict(files)
    changed["prices"] += extension
    changed["reference_prices"] += extension
    result = run_snapshot(prepare_snapshot(changed, settings))
    assert result.prepared.prices.index.max().date() == settings.as_of
    for left, right in zip(baseline.alternatives, result.alternatives, strict=True):
        np.testing.assert_array_equal(left.metrics.weights, right.metrics.weights)
        for method in ("bootstrap_blocks", "lognormal"):
            np.testing.assert_array_equal(
                baseline.simulations[left.name][method].monthly_values,
                result.simulations[right.name][method].monthly_values,
            )


def test_rejects_nonmatching_identity_between_sources(pilot):
    files, settings = pilot
    changed = dict(files)
    changed["reference_identity"] = files["reference_identity"].replace(
        synthetic_isin(1).encode(),
        synthetic_isin(99).encode(),
    )
    with pytest.raises(PortfolioError, match="mismo instrumento"):
        prepare_snapshot(changed, settings)


def test_rejects_price_disagreement_pending_rights_and_stale_cutoff(pilot):
    files, settings = pilot
    prices = pd.read_csv(BytesIO(files["reference_prices"]))
    prices[list(settings.assets)] *= 1.05
    with pytest.raises(PortfolioError, match="alertas de contraste"):
        prepare_snapshot({**files, "reference_prices": prices.to_csv(index=False).encode()}, settings)
    with pytest.raises(PortfolioError, match="CONFIRMADO"):
        prepare_snapshot({**files, "rights": files["rights"].replace(b"CONFIRMADO", b"PENDIENTE")}, settings)
    later = settings.as_of + timedelta(days=10)
    changed = {
        role: contents.replace(str(settings.as_of).encode(), str(later).encode())
        if role in {"holdings", "coverage"}
        else contents
        for role, contents in files.items()
    }
    with pytest.raises(PortfolioError, match="alejado del corte"):
        prepare_snapshot(changed, replace(settings, as_of=later))
    with pytest.raises(PortfolioError, match="posiciones"):
        prepare_snapshot(files, replace(settings, as_of=later))
    stale_reference = b"\n".join(files["reference_prices"].splitlines()[:171]) + b"\n"
    with pytest.raises(PortfolioError, match="alejado del corte"):
        prepare_snapshot(
            {**files, "reference_prices": stale_reference}, replace(settings, minimum_coverage_pct=90)
        )


@pytest.mark.parametrize("changes", [{"paths": 1}, {"months": True}, {"seed": -1}, {"max_weight": 0.3}])
def test_rejects_invalid_protocol_before_estimation(pilot, changes):
    files, settings = pilot
    with pytest.raises(PortfolioError):
        prepare_snapshot(files, replace(settings, **changes))


def write_configuration(root, files, settings):
    names = {}
    for role, contents in files.items():
        name = f"{role}.csv"
        (root / name).write_bytes(contents)
        names[role] = name
    config = root / "pilot.json"
    config.write_text(
        json.dumps({"version": 1, "files": names, "settings": asdict(settings)}, default=str),
        encoding="utf-8",
    )
    return config


def test_cli_writes_internal_comparison_and_no_private_values_to_console(pilot, tmp_path, capsys):
    files, settings = pilot
    config = write_configuration(tmp_path, files, settings)
    out = tmp_path / "results"
    assert main(["--config", str(config), "--output-dir", str(out), "--pdf"]) == 0
    console = capsys.readouterr().out
    assert "100000" not in console and "AAA" not in console
    assert not json.loads((out / "analysis.json").read_text(encoding="utf-8"))["client_delivery_allowed"]
    text = " ".join(
        " ".join(
            page.extract_text() or "" for page in PdfReader(out / "comparison_internal.pdf").pages
        ).split()
    )
    assert "Revisión interna" in text and "brutas antes de costos e impuestos" in text
    assert "no son el historial realizado" in text
    assert "Covarianza con contracción diagonal" in text
    assert "Tope por instrumento de las propuestas: 60.00%" in text
    fingerprint = sha256((out / "analysis.json").read_bytes()).hexdigest()
    assert main(["--config", str(config), "--output-dir", str(out)]) == 2
    assert sha256((out / "analysis.json").read_bytes()).hexdigest() == fingerprint


def test_pending_case_reports_only_missing_inputs_without_inventing_results(tmp_path, capsys):
    config = tmp_path / "pilot.json"
    config.write_text(json.dumps({"version": 1, "files": dict.fromkeys(INPUT_ROLES), "settings": None}))
    out = tmp_path / "pending"
    assert main(["--config", str(config), "--output-dir", str(out), "--check-only"]) == 2
    readiness = json.loads((out / "readiness.json").read_text(encoding="utf-8"))
    assert readiness["status"] == "INPUTS_PENDING"
    assert set(readiness["missing_inputs"]) == set(INPUT_ROLES)
    assert not readiness["model_executed"]
    assert not (out / "analysis.json").exists()
    assert not (out / "comparison_internal.pdf").exists()
    assert "INVALID" not in capsys.readouterr().out


def test_configuration_rejects_paths_outside_the_case(tmp_path):
    config = tmp_path / "pilot.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "files": {**dict.fromkeys(INPUT_ROLES), "holdings": "../another_case.csv"},
                "settings": None,
            }
        )
    )
    out = tmp_path / "results"
    assert main(["--config", str(config), "--output-dir", str(out), "--check-only"]) == 2
    assert not out.exists()


def test_failed_private_control_does_not_leak_the_amount_to_console(pilot, tmp_path, capsys):
    files, settings = pilot
    config = write_configuration(
        tmp_path,
        {
            **files,
            "coverage": files["coverage"].replace(
                b"105000",
                b"105001",
            ),
        },
        settings,
    )
    out = tmp_path / "results"
    assert main(["--config", str(config), "--output-dir", str(out)]) == 2
    console = capsys.readouterr().out
    assert "105001" not in console and "AAA" not in console
    assert not out.exists()


def synthetic_tariff():
    from broker_tariffs import DATED_TARIFF_COLUMNS

    return (
        ",".join(DATED_TARIFF_COLUMNS) + "\n"
        "Intermediario sintético,Trading MX,BMV,PUBLICA,2020-01-01,,2020-09-08,"
        "0.25,16,0,0,0,0,Tarifa sintética de prueba\n"
    ).encode()


def test_cost_supplement_separates_costs_from_gross_model(pilot):
    files, settings = pilot
    run = run_snapshot(prepare_snapshot(files, settings))
    before = run.summary()
    costs = review_cost_profile(run, synthetic_tariff())
    summary = costs.summary(run.prepared.holdings.total_value)
    assert summary["estimates"][0]["total_cost"] == 0
    assert summary["estimates"][1]["total_cost"] > 0
    assert summary["estimates"][1]["vat"] == pytest.approx(summary["estimates"][1]["commission"] * 0.16)
    assert run.summary() == before
    pdf_text = " ".join(page.extract_text() for page in PdfReader(BytesIO(run.pdf(costs=costs))).pages)
    assert "Tarifa sintética de prueba" in pdf_text


def test_extended_validation_keeps_insufficient_history_and_benchmark_pending(pilot):
    files, settings = pilot
    run = run_snapshot(prepare_snapshot(files, settings))
    validation = evaluate_snapshot_model(run)
    assert validation["holdout"]["status"] == "COMPUTED_GROSS"
    assert validation["holdout"]["training_end"] < validation["holdout"]["evaluation_start"]
    assert validation["sample_end"] == settings.as_of.isoformat()
    assert validation["four_cuts"]["status"].startswith("INSUFFICIENT_HISTORY")
    assert validation["benchmark"]["status"].startswith("PENDING")
    assert not validation["client_delivery_allowed"]
    json.dumps(validation, allow_nan=False)


def test_cli_supports_cost_and_validation_supplements(pilot, tmp_path):
    files, settings = pilot
    config = write_configuration(tmp_path, files, settings)
    (tmp_path / "tariff.csv").write_bytes(synthetic_tariff())
    out = tmp_path / "supplement"
    assert (
        main(
            [
                "--config",
                str(config),
                "--output-dir",
                str(out),
                "--tariff-profile",
                "tariff.csv",
                "--extended-validation",
                "--pdf",
            ]
        )
        == 0
    )
    analysis = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["implementation"]["fingerprint"] == sha256(synthetic_tariff()).hexdigest()
    assert "validation" in analysis
    assert not analysis["client_delivery_allowed"]


def test_check_only_validates_a_supplied_tariff_without_running_model(pilot, tmp_path):
    files, settings = pilot
    config = write_configuration(tmp_path, files, settings)
    (tmp_path / "tariff.csv").write_bytes(synthetic_tariff().replace(b"2020-01-01", b"2021-01-01"))
    out = tmp_path / "bad_tariff"
    assert (
        main(
            [
                "--config",
                str(config),
                "--output-dir",
                str(out),
                "--check-only",
                "--tariff-profile",
                "tariff.csv",
            ]
        )
        == 2
    )
    assert not out.exists()


def test_snapshot_universe_uses_same_twenty_five_asset_limit_as_ui(pilot):
    _, settings = pilot
    with pytest.raises(PortfolioError):
        replace(settings, assets=tuple(f"ASSET{number}" for number in range(26))).validate()


def test_four_calibrated_cuts_run_when_history_is_sufficient(pilot):
    files, settings = pilot
    dates = pd.bdate_range(end=pd.Timestamp(settings.history_start) - pd.Timedelta(days=1), periods=100)
    rng = np.random.default_rng(111)
    early = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, (100, 3)), axis=0)),
        index=dates,
        columns=settings.assets,
    )
    existing = pd.read_csv(BytesIO(files["prices"]), index_col=0, parse_dates=True)
    prices = pd.concat([early, existing])
    prices.index.name = "Fecha"
    contents = prices.to_csv(date_format="%Y-%m-%d").encode()
    settings = replace(settings, history_start=dates[0].date())
    run = run_snapshot(
        prepare_snapshot({**files, "prices": contents, "reference_prices": contents}, settings)
    )
    result = evaluate_snapshot_model(run)
    assert result["four_cuts"]["status"] == "COMPUTED_GROSS"
    rows = result["four_cuts"]["summary"]
    assert len({row["Corte inicial"] for row in rows}) == 4
    assert all(row["Estimación hasta"] < row["Evaluación desde"] for row in rows)
