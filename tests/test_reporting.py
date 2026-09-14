from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
import pdfplumber

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from simulation import simulate_portfolio_paths


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
            "Máximo Sharpe", result, 100, 0.01, 0, 0.04, 12, 21,
        ),
    )
    with pdfplumber.open(BytesIO(report)) as pdf:
        assert len(pdf.pages) >= 2
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Escenarios Monte Carlo" in text
    assert "1,000" in text
    assert "No incluye retiros" in text
