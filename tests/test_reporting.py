from datetime import date

import numpy as np

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import create_pdf_report


def test_pdf_report_is_created():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    report = create_pdf_report(("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1), metrics, risk, 100_000)
    assert report.startswith(b"%PDF")
    assert len(report) > 1_000
