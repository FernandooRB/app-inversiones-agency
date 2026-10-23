from datetime import date
from io import BytesIO

import numpy as np
from pypdf import PdfReader

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import PortfolioAlternative, create_comparison_pdf_report


def test_executive_cover_uses_same_risk_and_explicit_missing_costs():
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    alternatives = tuple(
        PortfolioAlternative(name, PortfolioMetrics(np.array([0.6, 0.4]), 0.1, 0.15, 0.4), risk)
        for name in ("Cartera al corte", "Mínima volatilidad")
    )
    pdf = create_comparison_pdf_report(
        ("AAA", "BBB"),
        date(2020, 1, 1),
        date(2020, 12, 31),
        alternatives,
        100_000,
        base_currency="MXN",
        risk_free_rate=0.02,
        observations=251,
        quotes={"AAA": "MXN", "BBB": "MXN"},
        executive_summary=True,
        objective="Estudio <sintético> de prueba",
    )
    pages = [page.extract_text() for page in PdfReader(BytesIO(pdf)).pages]
    assert "Resumen para revisión del equipo" in pages[0]
    assert "Estudio <sintético> de prueba" in pages[0]
    assert "2,500 MXN" in pages[0]
    assert "Pendiente" in pages[0]
    assert "pueden ocurrir pérdidas mayores" in pages[0]
    assert "Comparativo de carteras" in pages[1]
