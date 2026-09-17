"""Render a fictional comparative report for visual quality review."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from benchmarking import analyze_benchmark
from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioMetrics, RiskMetrics
from price_quality import PriceQualityIssue
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    StressReport,
    create_comparison_pdf_report,
)
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows


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
        index=pd.date_range("2023-08-01", periods=600, freq="B"),
        columns=labels,
    )
    result = simulate_portfolio_paths(
        fictional_returns, alternatives[0].metrics.weights,
        initial_value=1_000_000, months=36, paths=500,
        monthly_withdrawal=40_000, annual_fee=0.01,
        transaction_cost_bps=10, inflation_rate=0.04,
        rebalance_months=6, seed=42,
    )
    historical_parts = []
    for alternative in alternatives:
        history = historical_worst_windows(fictional_returns, alternative.metrics.weights)
        history.insert(0, "Escenario", alternative.name)
        historical_parts.append(history)
    stress_history = pd.concat(historical_parts, ignore_index=True)
    shocks = pd.Series([-0.02, -0.25, -0.18, 0.0], index=labels, name="Shock")
    shock_results = {
        alternative.name: deterministic_shock(
            alternative.metrics.weights, shocks, 1_000_000, labels=labels
        )
        for alternative in alternatives
    }
    cost_assumptions = ImplementationCostAssumptions(
        commission_bps=25, market_cost_bps=8, vat_rate=0.16, minimum_commission=20,
    )
    current_weights = alternatives[-1].metrics.weights
    implementation_costs = tuple(
        estimate_implementation_cost(
            labels, alternative.metrics.weights, 1_000_000, cost_assumptions,
            alternative_name=alternative.name, current_weights=current_weights,
        )
        for alternative in alternatives
    )
    allocation_policy = pd.DataFrame({
        "Clase": ["deuda_gubernamental", "renta_variable", "efectivo"],
        "Mínimo": [0.20, 0.30, 0.05],
        "Máximo": [0.50, 0.75, 0.20],
        "Activos": [1, 2, 1],
    })
    benchmark_returns = (
        fictional_returns["ETF_SIC"] * 0.65
        + fictional_returns["ACCION_MX"] * 0.35
    )
    benchmark_prices = 100 * (1 + benchmark_returns).cumprod()
    benchmark_analyses = tuple(
        analyze_benchmark(
            fictional_returns, alternative.metrics.weights, benchmark_prices,
            benchmark_name="Índice compuesto ficticio",
            portfolio_name=alternative.name, risk_free_rate=0.06,
        )
        for alternative in alternatives
    )
    output = Path("output/pdf/comparativo_ficticio_costos_mxn.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(create_comparison_pdf_report(
        labels, date(2021, 1, 4), date(2025, 12, 31), alternatives, 1_000_000,
        base_currency="MXN", risk_free_rate=0.06, observations=1_200,
        quotes=dict.fromkeys(labels, "MXN"),
        data_source="datos ficticios para revisión visual; no son cotizaciones de mercado",
        price_quality_issues=(
            PriceQualityIssue("ETF_SIC", "Salto de precio", "2024-06-10", "2024-06-11", "+35.40%"),
            PriceQualityIssue(
                "ACCION_MX", "Cierre sin cambio", "2024-08-01", "2024-08-08",
                "5 sesiones consecutivas sin variación",
            ),
        ),
        implementation_costs=implementation_costs,
        implementation_cost_assumptions=cost_assumptions,
        implementation_cost_source="Tarifario ficticio para revisión visual",
        implementation_cost_source_date=date(2026, 9, 16),
        simulation=SimulationReport(
            "Máximo Sharpe", result, 0, 40_000, 0.01, 10, 0.04, 6, 21,
        ),
        stress=StressReport(stress_history, shocks, shock_results),
        allocation_policy=allocation_policy,
        benchmark_analyses=benchmark_analyses,
        benchmark_source="serie ficticia para revisión visual; no es un índice de mercado",
    ))
    print(output.resolve())


if __name__ == "__main__":
    main()
