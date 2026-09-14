from datetime import date

import numpy as np

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import PortfolioAlternative, create_comparison_pdf_report, create_pdf_report


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
