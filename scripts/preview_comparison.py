"""Render a fictional comparative report for visual quality review."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import PortfolioAlternative, SimulationReport, create_comparison_pdf_report
from simulation import simulate_portfolio_paths


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
    rng = np.random.default_rng(21)
    fictional_returns = pd.DataFrame(
        rng.normal([0.0002, 0.0005, 0.0006, 0.0001], [0.001, 0.009, 0.012, 0.0005],
                   size=(600, 4)),
        columns=labels,
    )
    result = simulate_portfolio_paths(
        fictional_returns, alternatives[0].metrics.weights,
        initial_value=1_000_000, months=36, paths=500,
        monthly_contribution=10_000, annual_fee=0.01,
        transaction_cost_bps=10, inflation_rate=0.04,
        rebalance_months=6, seed=42,
    )
    output = Path("output/pdf/comparativo_ficticio_montecarlo_mxn.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(create_comparison_pdf_report(
        labels, date(2021, 1, 4), date(2025, 12, 31), alternatives, 1_000_000,
        base_currency="MXN", risk_free_rate=0.06, observations=1_200,
        quotes=dict.fromkeys(labels, "MXN"),
        data_source="datos ficticios para revisión visual; no son cotizaciones de mercado",
        simulation=SimulationReport(
            "Máximo Sharpe", result, 10_000, 0.01, 10, 0.04, 6, 21,
        ),
    ))
    print(output.resolve())


if __name__ == "__main__":
    main()
