from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
from pypdf import PdfReader

from portfolio_core import PortfolioMetrics, RiskMetrics
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
