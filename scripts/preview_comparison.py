"""Render a fictional comparative report for visual quality review."""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from benchmarking import analyze_benchmark
from black_litterman import AbsoluteView, black_litterman_posterior
from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioMetrics, RiskMetrics
from price_quality import PriceQualityIssue
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    StressReport,
    create_comparison_pdf_report,
)
from risk_attribution import attribute_volatility
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows
from tax_impact import estimate_tax_reserve, read_tax_basis_csv


def main() -> None:
    labels = ("CETES28", "BONOM", "ETF_SIC", "ACCION_MX", "LIQUIDEZ", "FONDOA1")
    cases = (
        ("Máximo Sharpe", [0.15, 0.15, 0.35, 0.20, 0.05, 0.10], 0.125, 0.138, 0.47, 0.039, 0.052),
        ("Mínima volatilidad", [0.30, 0.20, 0.10, 0.10, 0.15, 0.15], 0.083, 0.066, 0.34, 0.017, 0.024),
        ("Pesos iguales", [1 / 6] * 6, 0.101, 0.105, 0.39, 0.029, 0.040),
        ("Cartera actual", [0.20, 0.15, 0.20, 0.25, 0.05, 0.15], 0.108, 0.119, 0.41, 0.034, 0.046),
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
        rng.normal(
            [0.0002, 0.00025, 0.0005, 0.0006, 0.0001, 0.0003],
            [0.001, 0.004, 0.009, 0.012, 0.0005, 0.003], size=(600, 6),
        ),
        index=pd.date_range("2023-08-01", periods=600, freq="B"),
        columns=labels,
    )
    covariance = fictional_returns.cov() * 252
    alternatives = tuple(
        PortfolioAlternative(
            alternative.name,
            PortfolioMetrics(
                alternative.metrics.weights,
                alternative.metrics.annual_return,
                float(np.sqrt(alternative.metrics.weights @ covariance @ alternative.metrics.weights)),
                alternative.metrics.sharpe_ratio,
            ),
            alternative.risk,
        )
        for alternative in alternatives
    )
    black_litterman = black_litterman_posterior(
        covariance,
        alternatives[-1].metrics.weights,
        0.06,
        risk_aversion=2.5,
        tau=0.05,
        views=(
            AbsoluteView("ETF_SIC", 0.13, 0.60),
            AbsoluteView("ACCION_MX", 0.10, 0.55),
        ),
    )
    black_litterman_weights = np.array([0.20, 0.15, 0.25, 0.15, 0.10, 0.15])
    black_litterman_return = float(black_litterman_weights @ black_litterman.posterior_returns)
    black_litterman_volatility = float(np.sqrt(
        black_litterman_weights @ covariance @ black_litterman_weights
    ))
    black_litterman_metrics = PortfolioMetrics(
        weights=black_litterman_weights,
        annual_return=black_litterman_return,
        annual_volatility=black_litterman_volatility,
        sharpe_ratio=(black_litterman_return - 0.06) / black_litterman_volatility,
    )
    alternatives = (*alternatives, PortfolioAlternative(
        "Black-Litterman", black_litterman_metrics,
        RiskMetrics(0.95, 5, 0.0, 0.031, 0.043),
    ))
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
    shocks = pd.Series([-0.03, -0.08, -0.22, -0.22, 0.0, -0.10], index=labels, name="Shock")
    class_shocks = pd.Series({
        "deuda_gubernamental": -0.06,
        "renta_variable": -0.22,
        "efectivo": 0.0,
        "fondo": -0.10,
    }, name="Shock por clase")
    shock_results = {
        alternative.name: deterministic_shock(
            alternative.metrics.weights, shocks, 1_000_000, labels=labels
        )
        for alternative in alternatives
    }
    cost_assumptions = ImplementationCostAssumptions(
        commission_bps=25, market_cost_bps=8, vat_rate=0.16, minimum_commission=20,
        annual_fixed_cost=1_032, annual_management_rate=0.01,
    )
    current_weights = next(
        alternative.metrics.weights
        for alternative in alternatives
        if alternative.name == "Cartera actual"
    )
    implementation_costs = tuple(
        estimate_implementation_cost(
            labels, alternative.metrics.weights, 1_000_000, cost_assumptions,
            alternative_name=alternative.name, current_weights=current_weights,
        )
        for alternative in alternatives
    )
    tax_rows = pd.DataFrame({
        "FechaCorte": ["2026-09-17"] * len(labels),
        "Instrumento": labels,
        "CostoFiscalActualizadoMXN": current_weights * 800_000,
        "TratamientoFiscal": [
            "NO_ESTIMADO", "NO_ESTIMADO", "PF_ACCIONES_BOLSA_ART129",
            "PF_ACCIONES_BOLSA_ART129", "NO_ESTIMADO", "NO_ESTIMADO",
        ],
        "TasaEscenarioPct": [np.nan, np.nan, 10, 10, np.nan, np.nan],
        "Fuente": ["Base fiscal ficticia para revisión visual"] * len(labels),
    })
    tax_basis_profile = read_tax_basis_csv(
        tax_rows.to_csv(index=False).encode("utf-8-sig"), labels, date(2026, 9, 17)
    )
    current_values = pd.Series(current_weights * 1_000_000, index=labels)
    tax_reserve_estimates = tuple(
        estimate_tax_reserve(item, current_values, tax_basis_profile)
        for item in implementation_costs
    )
    allocation_policy = pd.DataFrame({
        "Clase": ["deuda_gubernamental", "renta_variable", "efectivo", "fondo"],
        "Mínimo": [0.20, 0.30, 0.05, 0.0],
        "Máximo": [0.60, 0.75, 0.20, 0.30],
        "Activos": [2, 2, 1, 1],
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
    risk_attributions = tuple(
        attribute_volatility(
            covariance, alternative.metrics.weights, alternative_name=alternative.name
        )
        for alternative in alternatives
    )
    output = Path("output/pdf/comparativo_ficticio_costos_mxn.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(create_comparison_pdf_report(
        labels, date(2021, 1, 4), date(2025, 12, 31), alternatives, 1_000_000,
        base_currency="MXN", risk_free_rate=0.06, observations=1_200,
        quotes=dict.fromkeys(labels, "MXN"),
        data_source=(
            "CSV ficticio; Proveedor de ejemplo / Cierres diarios; mercados BMV y SIC; derechos "
            "revisados 2026-09-01; alcance ENTREGABLES_DERIVADOS; cierre oficial "
            "America/Mexico_City; referencia Contrato ficticio sección 4; precios declarados "
            "ajustados; SHA-256 datos abcdef012345 y manifiesto 9876543210ab; BONOM representa "
            "una emisión preparada desde precio limpio, interés devengado y cupones; LIQUIDEZ una "
            "tasa histórica declarada, y FONDOA1 valor de acción y distribuciones de una serie "
            "exacta; no son cotizaciones de mercado"
        ),
        price_quality_issues=(
            PriceQualityIssue("ETF_SIC", "Salto de precio", "2024-06-10", "2024-06-11", "+35.40%"),
            PriceQualityIssue(
                "ACCION_MX", "Cierre sin cambio", "2024-08-01", "2024-08-08",
                "5 sesiones consecutivas sin variación",
            ),
        ),
        implementation_costs=implementation_costs,
        implementation_cost_assumptions=cost_assumptions,
        implementation_cost_source=(
            "Perfil contractual ficticio para revisión visual; CSV SHA-256 0123456789ab"
        ),
        implementation_cost_source_date=date(2026, 9, 17),
        tax_reserve_estimates=tax_reserve_estimates,
        tax_basis_profile=tax_basis_profile,
        simulation=SimulationReport(
            "Máximo Sharpe", result, 0, 40_000, 0.01, 10, 0.04, 6, 21,
        ),
        stress=StressReport(
            stress_history, shocks, shock_results, class_shocks,
            "Venta global y búsqueda de liquidez",
            "Caída simultánea de activos de riesgo y presión moderada en deuda.",
        ),
        allocation_policy=allocation_policy,
        benchmark_analyses=benchmark_analyses,
        benchmark_source="serie ficticia para revisión visual; no es un índice de mercado",
        risk_attributions=risk_attributions,
        black_litterman=black_litterman,
        black_litterman_source="cartera actual ficticia",
    ))
    print(output.resolve())


if __name__ == "__main__":
    main()
