from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd
from pypdf import PdfReader

from benchmarking import analyze_benchmark
from black_litterman import AbsoluteView, black_litterman_posterior
from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioMetrics, RiskMetrics, optimize_portfolio
from price_quality import PriceQualityIssue
from reporting import (
    PortfolioAlternative,
    SimulationReport,
    StressReport,
    create_comparison_pdf_report,
    create_pdf_report,
)
from risk_attribution import attribute_volatility
from simulation import simulate_portfolio_paths
from stress import deterministic_shock, historical_worst_windows
from tax_cash_flows import read_tax_cash_flows_csv
from tax_impact import estimate_tax_reserve, read_tax_basis_csv


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


def test_both_pdfs_include_benchmark_metrics_and_source():
    index = pd.date_range("2023-01-02", periods=100, freq="B")
    benchmark_returns = np.linspace(-0.01, 0.012, len(index))
    returns = pd.DataFrame({
        "AAA": benchmark_returns,
        "BBB": benchmark_returns * 0.4 + 0.0003,
    }, index=index)
    prices = pd.Series(100 * np.cumprod(1 + benchmark_returns), index=index)
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    analysis = analyze_benchmark(
        returns, metrics.weights, prices, benchmark_name="IPC ficticio",
        portfolio_name="Máximo Sharpe", risk_free_rate=0.05,
    )
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, benchmark_analyses=(analysis,),
        benchmark_source="Fuente ficticia de prueba",
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=99, quotes={"AAA": "MXN", "BBB": "MXN"},
        benchmark_analyses=(analysis,), benchmark_source="Fuente ficticia de prueba",
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        assert "Comparación contra benchmark" in text
        assert "IPC ficticio" in text
        assert "Tracking error" in text
        assert "Alpha anual" in text
        assert "Fuente ficticia de prueba" in text


def test_both_pdfs_include_reconciled_risk_attribution():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    covariance = pd.DataFrame(
        [[0.04, 0.006], [0.006, 0.01]], index=["AAA", "BBB"], columns=["AAA", "BBB"]
    )
    attribution = attribute_volatility(
        covariance, metrics.weights, alternative_name="Máximo Sharpe"
    )
    metrics = PortfolioMetrics(
        metrics.weights, metrics.annual_return, attribution.portfolio_volatility,
        metrics.sharpe_ratio,
    )
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1), metrics, risk,
        100_000, risk_attributions=(attribution,),
    )
    second_attribution = attribute_volatility(
        covariance, [0.5, 0.5], alternative_name="Pesos iguales"
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (
            PortfolioAlternative("Máximo Sharpe", metrics, risk),
            PortfolioAlternative(
                "Pesos iguales",
                PortfolioMetrics(
                    np.array([0.5, 0.5]), 0.09,
                    second_attribution.portfolio_volatility, 0.33,
                ),
                risk,
            ),
        ),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        risk_attributions=(attribution, second_attribution),
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        assert "Atribución de riesgo" in text
        assert "Razón de" in text
        assert "diversificación" in text
        assert "Contribuyentes" in text
        assert "efectivos" in text
        assert "contribución de Euler" in text


def test_comparison_pdf_documents_black_litterman_assumptions():
    covariance = pd.DataFrame(
        [[0.04, 0.006], [0.006, 0.01]], index=["AAA", "BBB"], columns=["AAA", "BBB"]
    )
    result = black_litterman_posterior(
        covariance, [0.6, 0.4], 0.05, risk_aversion=3.0, tau=0.08,
        views=(AbsoluteView("AAA", 0.16, 0.70),),
    )
    black_litterman_metrics = optimize_portfolio(
        result.posterior_returns, covariance, 0.05
    )
    historical_metrics = PortfolioMetrics(np.array([0.5, 0.5]), 0.09, 0.12, 0.33)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (
            PortfolioAlternative("Máximo Sharpe", historical_metrics, risk),
            PortfolioAlternative("Pesos iguales", historical_metrics, risk),
            PortfolioAlternative("Black-Litterman", black_litterman_metrics, risk),
        ),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        black_litterman=result, black_litterman_source="pesos de mercado declarados",
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    assert "Escenario Black-Litterman" in text
    assert "pesos de mercado declarados" in text
    assert "Aversión al riesgo: 3.00" in text
    assert "tau: 0.080" in text
    assert "16.00%" in text
    assert "70.0%" in text


def test_both_pdfs_report_explicit_implementation_cost_assumptions():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    assumptions = ImplementationCostAssumptions(25, 10, 0.16, 20, 1_032, 0.01)
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
        assert "costo recurrente anual estimado" in text
        assert "2,032.00" in text


def test_both_pdfs_report_auditable_tax_reserve_without_calling_it_tax_due():
    metrics = PortfolioMetrics(np.array([0.2, 0.8]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    implementation = estimate_implementation_cost(
        ("AAA", "BBB"), metrics.weights, 100_000,
        ImplementationCostAssumptions(commission_bps=10),
        alternative_name="Máximo Sharpe", current_weights=np.array([0.6, 0.4]),
    )
    fiscal_csv = (
        "FechaCorte,Instrumento,CostoFiscalActualizadoMXN,TratamientoFiscal,"
        "TasaEscenarioPct,Fuente\n"
        f"{date.today().isoformat()},AAA,40000,PF_ACCIONES_BOLSA_ART129,10,Fuente fiscal\n"
        f"{date.today().isoformat()},BBB,30000,NO_ESTIMADO,,Pendiente\n"
    ).encode()
    profile = read_tax_basis_csv(fiscal_csv, ("AAA", "BBB"), date.today())
    reserve = estimate_tax_reserve(
        implementation, pd.Series({"AAA": 60_000.0, "BBB": 40_000.0}), profile
    )
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, base_currency="MXN",
        tax_reserve_estimates=(reserve,), tax_basis_profile=profile,
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        tax_reserve_estimates=(reserve,), tax_basis_profile=profile,
    )
    for report in (basic, comparison):
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
        normalized = " ".join(text.split())
        assert "Reserva fiscal ilustrativa por ventas" in text
        assert profile.fingerprint[:12] in text
        assert "no el impuesto a pagar" in normalized


def test_both_pdfs_keep_cash_flow_withholding_apart_from_additional_reserve():
    metrics = PortfolioMetrics(np.array([0.2, 0.8]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 1, 0.02, 0.025, 0.035)
    contents = (
        b"FechaPago,Instrumento,TipoFlujo,ImporteBrutoMXN,ISRRetenidoMXN,"
        b"ImpuestoExtranjeroRetenidoMXN,TratamientoFiscal,BaseRetencionMXN,"
        b"DiasPeriodo,TasaControlPct,TasaReservaAdicionalPct,Fuente\n"
        b"2026-09-01,AAA,DIVIDENDO_MEX,10000,1000,0,"
        b"PF_DIVIDENDO_MEX_ART140,10000,,10,,Constancia ficticia\n"
        b"2026-09-02,BBB,DIVIDENDO_EXTRANJERO_SIC,5000,0,750,"
        b"ESCENARIO_TASA_ADICIONAL,,,,20,Constancia ficticia\n"
    )
    ledger = read_tax_cash_flows_csv(contents, ("AAA", "BBB"), date(2026, 9, 19))
    basic = create_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        metrics, risk, 100_000, base_currency="MXN", tax_cash_flow_ledger=ledger,
    )
    comparison = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        100_000, base_currency="MXN", risk_free_rate=0.05,
        observations=252, quotes={"AAA": "MXN", "BBB": "MXN"},
        tax_cash_flow_ledger=ledger,
    )
    for report in (basic, comparison):
        text = " ".join(
            (page.extract_text() or "") for page in PdfReader(BytesIO(report)).pages
        )
        assert "Flujos fiscales documentados" in text
        assert ledger.fingerprint[:12] in text
        assert "1,000.00" in text
        assert "750.00" in text
        assert "saldo a pagar" in text


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


def test_comparison_pdf_documents_named_class_stress():
    metrics = PortfolioMetrics(np.array([0.6, 0.4]), 0.10, 0.15, 0.40)
    risk = RiskMetrics(0.95, 5, 0.02, 0.025, 0.035)
    index = pd.date_range("2023-01-02", periods=80, freq="B")
    returns = pd.DataFrame({
        "AAA": np.linspace(-0.02, 0.02, 80),
        "BBB": np.linspace(0.01, -0.01, 80),
    }, index=index)
    history = historical_worst_windows(returns, metrics.weights)
    history.insert(0, "Escenario", "Máximo Sharpe")
    shocks = pd.Series([-0.25, -0.03], index=["AAA", "BBB"], name="Shock")
    class_shocks = pd.Series(
        {"renta_variable": -0.25, "deuda": -0.03}, name="Shock por clase"
    )
    result = deterministic_shock(metrics.weights, shocks, 1000, labels=shocks.index)
    report = create_comparison_pdf_report(
        ("AAA", "BBB"), date(2023, 1, 1), date(2024, 1, 1),
        (PortfolioAlternative("Máximo Sharpe", metrics, risk),
         PortfolioAlternative("Pesos iguales", metrics, risk)),
        1000, base_currency="MXN", risk_free_rate=0.05, observations=80,
        quotes={"AAA": "MXN", "BBB": "MXN"},
        stress=StressReport(
            history, shocks, {"Máximo Sharpe": result}, class_shocks,
            "Venta global", "Aversión al riesgo y ampliación de diferenciales",
        ),
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    assert "Clase declarada" in text
    assert "Venta global" in text
    assert "Aversión al riesgo" in text
    assert "renta_variable" in text
