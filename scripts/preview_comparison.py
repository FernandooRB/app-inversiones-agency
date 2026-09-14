"""Render a fictional comparative report for visual quality review."""

from datetime import date
from pathlib import Path

import numpy as np

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import PortfolioAlternative, create_comparison_pdf_report


def main() -> None:
    labels = ("CETES28", "ETF_SIC", "ACCION_MX", "EFECTIVO")
    cases = (
        ("Máximo Sharpe", [0.20, 0.45, 0.30, 0.05], 0.125, 0.138, 0.47, 0.039, 0.052),
        ("Mínima volatilidad", [0.50, 0.20, 0.10, 0.20], 0.083, 0.066, 0.34, 0.017, 0.024),
        ("Pesos iguales", [0.25, 0.25, 0.25, 0.25], 0.101, 0.105, 0.39, 0.029, 0.040),
        ("Cartera actual", [0.30, 0.30, 0.35, 0.05], 0.108, 0.119, 0.41, 0.034, 0.046),
    )
    alternatives = tuple(
        PortfolioAlternative(
            name,
            PortfolioMetrics(np.array(weights), annual_return, volatility, sharpe),
            RiskMetrics(0.95, 5, 0.0, var, cvar),
        )
        for name, weights, annual_return, volatility, sharpe, var, cvar in cases
    )
    output = Path("output/pdf/comparativo_ficticio_mxn.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(create_comparison_pdf_report(
        labels, date(2021, 1, 4), date(2025, 12, 31), alternatives, 1_000_000,
        base_currency="MXN", risk_free_rate=0.06, observations=1_200,
        quotes=dict.fromkeys(labels, "MXN"),
        data_source="datos ficticios para revisión visual; no son cotizaciones de mercado",
    ))
    print(output.resolve())


if __name__ == "__main__":
    main()
