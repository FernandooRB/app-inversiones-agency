"""Local, retrospective snapshot research using supplied data and existing engines."""

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256

import numpy as np
import pandas as pd

from covariance_calibration import select_diagonal_shrinkage
from data_rights import read_data_rights_csv
from holdings import CurrentHoldings, read_current_holdings_csv
from holdings_control import HoldingsCoverageControl, read_holdings_coverage_csv
from instrument_identity import read_instrument_identity_csv
from pilot_validation import PilotCosts
from portfolio_core import (
    PortfolioError,
    PortfolioMetrics,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    optimize_portfolio,
    portfolio_statistics,
    validate_weights,
)
from price_quality import PriceQualityIssue, assess_price_quality
from price_source_validation import PriceSourceComparison, compare_price_sources
from price_upload import read_adjusted_price_csv
from reporting import (
    HoldingsAuditReport,
    PortfolioAlternative,
    SimulationReport,
    create_comparison_pdf_report,
)
from simulation import SimulationResult, simulate_portfolio_paths

INPUT_ROLES = (
    "holdings", "coverage", "prices", "rights", "identity",
    "reference_prices", "reference_rights", "reference_identity",
)


@dataclass(frozen=True)
class SnapshotSettings:
    history_start: date
    as_of: date
    assets: tuple[str, ...]
    risk_free_rate: float
    risk_free_source: str
    max_weight: float
    months: int = 12
    paths: int = 500
    seed: int = 42
    rebalance_months: int = 12
    block_days: int = 21
    tolerance_pct: float = 0.1
    minimum_coverage_pct: float = 100.0
    max_price_age_days: int = 7

    def validate(self) -> None:
        if (self.history_start >= self.as_of or self.as_of > date.today()
                or not self.assets or len(self.assets) > 25 or len(set(self.assets)) != len(self.assets)
                or any(not isinstance(asset, str) or asset != asset.strip().upper()
                       or not asset for asset in self.assets)):
            raise PortfolioError("Define universo único y fechas válidas para el corte retrospectivo.")
        if (not np.isfinite(self.risk_free_rate) or not -1 < self.risk_free_rate < 1
                or not isinstance(self.risk_free_source, str) or not self.risk_free_source.strip()
                or len(self.risk_free_source) > 300
                or any(ord(char) < 32 for char in self.risk_free_source)):
            raise PortfolioError("Declara tasa libre de riesgo y fuente o justificación del supuesto.")
        if (not isinstance(self.max_price_age_days, int) or isinstance(self.max_price_age_days, bool)
                or not 0 <= self.max_price_age_days <= 7):
            raise PortfolioError("La antigüedad máxima del último precio debe ser de 0 a 7 días.")
        if (not np.isfinite(self.max_weight) or not 0 < self.max_weight <= 1
                or self.max_weight * len(self.assets) < 1 - 1e-10):
            raise PortfolioError("El límite de concentración no permite invertir el capital completo.")
        for value, lower, upper in (
            (self.months, 1, 120), (self.paths, 100, 2000), (self.seed, 0, 2**32 - 1),
            (self.block_days, 1, 63),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
                raise PortfolioError("Horizonte, trayectorias, semilla o bloque fuera del protocolo.")
        if (self.rebalance_months not in {3, 6, 12}
                or not np.isfinite(self.tolerance_pct) or not 0 <= self.tolerance_pct <= 100
                or not np.isfinite(self.minimum_coverage_pct) or not 0 < self.minimum_coverage_pct <= 100):
            raise PortfolioError("Revisa frecuencia de rebalanceo y umbrales de contraste.")


@dataclass(frozen=True)
class PreparedSnapshot:
    settings: SnapshotSettings
    holdings: CurrentHoldings
    coverage: HoldingsCoverageControl
    prices: pd.DataFrame
    comparison: PriceSourceComparison
    quality_issues: tuple[PriceQualityIssue, ...]
    fingerprints: dict[str, str]
    provenance: str


def prepare_snapshot(files: dict[str, bytes], settings: SnapshotSettings) -> PreparedSnapshot:
    """Check both licensed series and snapshot alignment before any estimation."""
    settings.validate()
    if set(files) != set(INPUT_ROLES) or any(not contents for contents in files.values()):
        raise PortfolioError("Se necesitan los ocho archivos locales del piloto.")
    quotes = dict.fromkeys(settings.assets, "MXN")
    rights = read_data_rights_csv(files["rights"])
    read_data_rights_csv(files["reference_rights"])
    identity = read_instrument_identity_csv(files["identity"], settings.assets, quotes)
    reference_identity = read_instrument_identity_csv(files["reference_identity"], settings.assets, quotes)
    if identity.proxy_assets or reference_identity.proxy_assets:
        raise PortfolioError("Este piloto requiere cierres locales en MXN; no admite series proxy.")
    holdings = read_current_holdings_csv(files["holdings"], settings.assets)
    if holdings.as_of.date() != settings.as_of:
        raise PortfolioError("El corte solicitado no coincide con las posiciones.")
    coverage = read_holdings_coverage_csv(files["coverage"], holdings)
    prices = read_adjusted_price_csv(
        files["prices"], settings.assets, settings.history_start, settings.as_of,
    ).prices
    reference_prices = read_adjusted_price_csv(
        files["reference_prices"], settings.assets, settings.history_start, settings.as_of,
    ).prices
    if any((settings.as_of - series.index[-1].date()).days > settings.max_price_age_days
           for series in (prices, reference_prices)):
        raise PortfolioError("El último precio de una fuente está demasiado alejado del corte.")
    comparison = compare_price_sources(
        files["prices"], files["rights"], files["reference_prices"], files["reference_rights"],
        settings.assets, quotes, settings.history_start, settings.as_of,
        tolerance_pct=settings.tolerance_pct, minimum_coverage_pct=settings.minimum_coverage_pct,
        primary_identity_csv=files["identity"], reference_identity_csv=files["reference_identity"],
    )
    if comparison.review_reasons:
        raise PortfolioError("Resuelve las alertas de contraste de precios antes de ejecutar el piloto.")
    if len(prices) < 101:
        raise PortfolioError("Este protocolo calibrado requiere al menos 101 precios diarios.")
    fingerprints = {name: sha256(contents).hexdigest() for name, contents in files.items()}
    provenance = (
        "Estudio retrospectivo interno; datos aportados, sin descarga automática. "
        "Asignaciones hipotéticas brutas antes de costos e impuestos; los rendimientos de una "
        "cartera fija sobre esta muestra no son el historial realizado de la cuenta. "
        f"Fuente {rights.source}; producto {rights.product}; alcance {rights.authorized_scope}; "
        f"precios SHA-256 {fingerprints['prices'][:12]}; derechos SHA-256 {rights.fingerprint[:12]}; "
        f"identidad SHA-256 {identity.fingerprint[:12]}; {comparison.audit_note}. "
        f"Tasa libre de riesgo: {settings.risk_free_source}. "
        "La declaración de derechos y las identidades requieren comprobación documental humana"
    )
    return PreparedSnapshot(
        settings, holdings, coverage, prices, comparison, assess_price_quality(prices),
        fingerprints, provenance,
    )


@dataclass(frozen=True)
class SnapshotRun:
    prepared: PreparedSnapshot
    alternatives: tuple[PortfolioAlternative, ...]
    simulations: dict[str, dict[str, SimulationResult]]
    shrinkage: float

    def summary(self) -> dict:
        settings = self.prepared.settings
        return {
            "protocol_version": 1,
            "scope": "INTERNAL_RETROSPECTIVE_GROSS_ONLY",
            "client_delivery_allowed": False,
            "human_review_pending": True,
            "historical_account_performance_calculated": False,
            "settings": {**asdict(settings), "history_start": settings.history_start.isoformat(),
                         "as_of": settings.as_of.isoformat()},
            "effective_start": self.prepared.prices.index[0].date().isoformat(),
            "effective_end": self.prepared.prices.index[-1].date().isoformat(),
            "observations": len(self.prepared.prices),
            "covariance_shrinkage": self.shrinkage,
            "fingerprints": self.prepared.fingerprints,
            "price_quality_issues": [asdict(issue) for issue in self.prepared.quality_issues],
            "capital_basis": "analyzed_holdings_only_cash_excluded",
            "simulation_basis": "gross_nominal_no_contributions_no_withdrawals",
            "alternatives": [{
                "name": alternative.name,
                "weights": dict(zip(settings.assets, alternative.metrics.weights.tolist(), strict=True)),
                "annualized_sample_mean": alternative.metrics.annual_return,
                "annualized_volatility": alternative.metrics.annual_volatility,
                "sample_sharpe": alternative.metrics.sharpe_ratio,
                "risk": asdict(alternative.risk),
                "simulations": {method: {
                    "bands": result.bands().to_dict(orient="records"),
                    "probability_below_initial_capital": result.probability_below_contributions,
                } for method, result in self.simulations[alternative.name].items()},
            } for alternative in self.alternatives],
            "limits": [
                "No estima ejecución, liquidez, costos por orden, impuestos ni idoneidad del cliente.",
                "Media, covarianza y riesgo describen la muestra de estimación, "
                "no resultados fuera de muestra.",
                "Monte Carlo histórico por bloques y lognormal son escenarios, no pronósticos.",
                "Los topes se aplican a las asignaciones propuestas; la cartera actual puede incumplirlos.",
                "No se ha aprobado entrega a terceros ni cotejo de los originales.",
            ],
        }

    def pdf(self, *, costs: PilotCosts | None = None) -> bytes:
        settings = self.prepared.settings
        chosen = "Mínima volatilidad"
        simulation = SimulationReport(
            chosen, self.simulations[chosen]["bootstrap_blocks"],
            0.0, 0.0, 0.0, 0.0, 0.0, settings.rebalance_months, settings.block_days,
        )
        return create_comparison_pdf_report(
            settings.assets, self.prepared.prices.index[0].date(), self.prepared.prices.index[-1].date(),
            self.alternatives, self.prepared.holdings.total_value,
            base_currency="MXN", risk_free_rate=settings.risk_free_rate,
            observations=len(self.prepared.prices) - 1, quotes=dict.fromkeys(settings.assets, "MXN"),
            data_source=(self.prepared.provenance + ". "
                         f"Covarianza con contracción diagonal de {self.shrinkage:.0%}, "
                         "calibrada con bloques anteriores dentro de la muestra. "
                         f"Tope por instrumento de las propuestas: {settings.max_weight:.2%}"),
            holdings_audit=HoldingsAuditReport(
                self.prepared.holdings, "Archivo de posiciones; cotejo humano pendiente",
                self.prepared.fingerprints["holdings"], coverage=self.prepared.coverage,
            ),
            simulation=simulation, price_quality_issues=self.prepared.quality_issues,
            executive_summary=True,
            implementation_costs=costs.estimates if costs else (),
            implementation_cost_assumptions=costs.assumptions if costs else None,
            implementation_cost_source=costs.source if costs else None,
            implementation_cost_source_date=costs.consulted_on if costs else None,
        )


def run_snapshot(prepared: PreparedSnapshot) -> SnapshotRun:
    """Run four fixed-allocation alternatives and two simulation methods, without future data."""
    settings = prepared.settings
    returns = calculate_returns(prepared.prices)
    calibration = select_diagonal_shrinkage(returns)
    mean, covariance = annualized_moments(returns, covariance_shrinkage=calibration.intensity)
    metrics = []
    for name, weights in (
        ("Cartera al corte", prepared.holdings.weights.to_numpy()),
        ("Pesos iguales", np.repeat(1 / len(settings.assets), len(settings.assets))),
    ):
        validate_weights(weights, len(settings.assets))
        metrics.append((name, PortfolioMetrics(weights, *portfolio_statistics(
            weights, mean, covariance, settings.risk_free_rate,
        ))))
    for name, objective in (("Mínima volatilidad", "min_volatility"), ("Máximo Sharpe", "max_sharpe")):
        metrics.append((name, optimize_portfolio(
            mean, covariance, settings.risk_free_rate, objective, settings.max_weight,
        )))
    alternatives = tuple(PortfolioAlternative(
        name, metric, calculate_risk_metrics(returns, metric.weights),
    ) for name, metric in metrics)
    simulations = {alternative.name: {method: simulate_portfolio_paths(
        returns, alternative.metrics.weights, initial_value=prepared.holdings.total_value,
        months=settings.months, paths=settings.paths, seed=settings.seed,
        rebalance_months=settings.rebalance_months, block_days=settings.block_days, method=method,
    ) for method in ("bootstrap_blocks", "lognormal")} for alternative in alternatives}
    return SnapshotRun(prepared, alternatives, simulations, calibration.intensity)
