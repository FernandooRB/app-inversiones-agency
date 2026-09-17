from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
from pypdf import PdfReader

from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioMetrics, RiskMetrics
from price_quality import PriceQualityIssue
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    StressReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows


def test_pdf_report_is_created():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    report = create_pdf_report(("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1), metrics, risk, 100_000)
    assert report.startswith(b"%PDF")
    assert len(report) > 1_000


def test_both_pdfs_include_declared_asset_class_policy():
    metrics = PortfolioMetrics(np.array([0.4, 0.6]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    policy = pd.DataFrame({
        "Clase": ["crecimiento", "defensivo"],
        "Mínimo": [0.20, 0.60], "Máximo": [0.40, 0.80], "Activos": [1, 1],
    })
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, allocation_policy=policy,
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Referencia simple factible", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        allocation_policy=policy,
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        assert "Política por clase de activo" in text
        assert "crecimiento" in text
        assert "20.0%" in text
        assert "clasificación fue declarada" in text


def test_both_pdfs_report_explicit_implementation_cost_assumptions():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    assumptions = ImplementationCostAssumptions(25, 10, 0.16, 20)
    estimate = estimate_implementation_cost(
        ("AAA", "BBB"), metrics.weights, 100_000, assumptions,
        alternative_name="Máximo Sharpe",
    )
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, base_currency="MXN",
        implementation_costs=(estimate,), implementation_cost_assumptions=assumptions,
        implementation_cost_source="Tarifario de prueba",
        implementation_cost_source_date=date(2026, 9, 16),
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        implementation_costs=(estimate,), implementation_cost_assumptions=assumptions,
        implementation_cost_source="Tarifario de prueba",
        implementation_cost_source_date=date(2026, 9, 16),
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        assert "Costo estimado de implementación" in text
        assert "25.0 pb por orden" in text
        assert "IVA sobre" in text
        assert "comisión: 16.00%" in text
        assert "390.00" in text
        assert "Tarifario de prueba" in text


def test_both_pdfs_include_heuristic_price_review_with_original_quote_context():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    issue = PriceQualityIssue("AAA", "Salto de precio", "2024-01-02", "2024-01-03", "+40.00%")
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1), metrics, risk,
        100_000, price_quality_issues=(issue,),
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "USD"},
        price_quality_issues=(issue,),
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        assert "Revisión de precios originales" in text
        assert "moneda de cotización" in text
        assert "Salto de precio" in text
    basic_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(basic)).pages)
    assert "+40.00%" in basic_text


def test_price_review_stays_with_its_detail_at_small_and_large_alert_counts():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    issue = PriceQualityIssue("AAA", "Salto de precio", "2024-01-02", "2024-01-03", "+40.00%")

    for issues in ((), (issue,)):
        report = create_pdf_report(
            ("AAA", "BBB"), date(2023, 1, 1), date(2024, 12, 31),
            metrics, risk, 100_000, price_quality_issues=issues,
        )
        assert len(PdfReader(BytesIO(report)).pages) == 1

    report = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 12, 31),
        metrics, risk, 100_000, price_quality_issues=(issue,) * 12,
    )
    pages = [page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages]
    assert len(pages) == 2
    assert "Revisión de precios originales" not in pages[0]
    assert "Revisión de precios originales" in pages[1]
    assert pages[1].count("Salto de precio") == 12


def test_pdf_report_records_prepared_cetes_source():
    metrics = PortfolioMetrics(np.array([0.7, 0.3]), 0.09, 0.10, 0.40)
    risk = RiskMetrics(0.95, 1, 0.01, 0.015, 0.02)
    source = "Yahoo Finance; CETES28: CSV preparado, SHA-256 abc123"
    report = create_pdf_report(
        ("ETF_SIC", "CETES28"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, base_currency="MXN",
        quotes={"ETF_SIC": "USD", "CETES28": "MXN"}, data_source=source,
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    assert source in text


def test_comparison_pdf_uses_same_risk_horizon_and_builds():
    first = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    second = PortfolioMetrics(np.array([0.5, 0.5]), 0.09, 0.12, 0.33)
    risk = RiskMetrics(0.95, 5, 0.02, 0.025, 0.035)
    alternatives = (
        PortfolioAlternative("Máximo Sharpe", first, risk),
        PortfolioAlternative("Pesos iguales", second, risk),
    )
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        alternatives, 100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "USD"},
    )
    assert report.startswith(b"%PDF")
    assert len(report) > 2_000


def test_comparison_pdf_includes_simulation_assumptions_and_limits():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 5, 0.02, 0.025, 0.035)
    returns = pd.DataFrame(np.zeros((80, 2)), columns=["AAA", "BBB"])
    result = simulate_portfolio_paths(
        returns, metrics.weights, initial_value=1000, months=12, paths=100,
        monthly_contribution=100, annual_fee=0.01, inflation_rate=0.04,
    )
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        1000, base_currency="MXN", risk_free_rate=0.05, observations=80,
        quotes={"AAA": "MXN", "BBB": "MXN"},
        simulation=SimulationReport(
            "Máximo Sharpe", result, 100, 0, 0.01, 0, 0.04, 12, 21,
        ),
    )
    pdf = PdfReader(BytesIO(report))
    assert len(pdf.pages) >= 2
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Escenarios Monte Carlo" in text
    assert "1,000" in text
    assert "No incluye retiros" in text


def test_comparison_pdf_reports_unfunded_withdrawals():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 5, 0.02, 0.025, 0.035)
    returns = pd.DataFrame(np.zeros((80, 2)), columns=["AAA", "BBB"])
    result = simulate_portfolio_paths(
        returns, metrics.weights, initial_value=1000, months=4, paths=100,
        monthly_withdrawal=300,
    )
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        1000, base_currency="MXN", risk_free_rate=0.05, observations=80,
        quotes={"AAA": "MXN", "BBB": "MXN"},
        simulation=SimulationReport(
            "Máximo Sharpe", result, 0, 300, 0, 0, 0, 12, 21,
        ),
    )
    pdf = PdfReader(BytesIO(report))
    assert len(pdf.pages) >= 2
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Retiros programados" in text
    assert "1,200" in text
    assert "retiro no cubierto" in text


def test_comparison_pdf_reports_historical_and_hypothetical_stress():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 5, 0.02, 0.025, 0.035)
    index = pd.date_range("2023-01-02", periods=80, freq="B")
    returns = pd.DataFrame({
        "AAA": np.linspace(-0.02, 0.02, 80),
        "BBB": np.linspace(0.01, -0.01, 80),
    }, index=index)
    history = historical_worst_windows(returns, metrics.weights)
    history.insert(0, "Escenario", "Máximo Sharpe")
    shocks = pd.Series([-0.20, -0.05], index=["AAA", "BBB"], name="Shock")
    result = deterministic_shock(metrics.weights, shocks, 1000, labels=shocks.index)
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        1000, base_currency="MXN", risk_free_rate=0.05, observations=80,
        quotes={"AAA": "MXN", "BBB": "MXN"},
        stress=StressReport(history, shocks, {"Máximo Sharpe": result}),
    )
    pdf = PdfReader(BytesIO(report))
    assert len(pdf.pages) >= 2
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Pruebas de estrés" in text
    assert "Peores ventanas históricas" in text
    assert "Shock hipotético simultáneo" in text
    assert "-14.00%" in text
