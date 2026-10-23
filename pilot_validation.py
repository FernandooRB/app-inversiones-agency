"""Supplemental checks for a snapshot; never label sample fit as validation."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from backtesting import run_holdout_backtest
from broker_tariffs import read_broker_tariff_csv
from implementation_costs import (
    ImplementationCostAssumptions,
    ImplementationCostEstimate,
    estimate_implementation_cost,
)
from multi_cut import run_multi_cut_backtest
from portfolio_core import PortfolioError, calculate_returns
from sensitivity import analyze_allocation_sensitivity
from stress import historical_worst_windows


def _table(frame):
    # Pandas serializes missing metrics as null, dates as ISO; no non-standard NaN JSON.
    return json.loads(frame.reset_index().to_json(orient="records", date_format="iso"))


@dataclass(frozen=True)
class PilotCosts:
    estimates: tuple[ImplementationCostEstimate, ...]
    assumptions: ImplementationCostAssumptions
    source: str
    consulted_on: object
    fingerprint: str
    tariff_kind: str

    def summary(self, capital):
        return {
            "status": "ESTIMATED_REQUIRES_ACCOUNT_REVIEW",
            "fingerprint": self.fingerprint,
            "tariff_kind": self.tariff_kind,
            "source": self.source,
            "consulted_on": self.consulted_on.isoformat(),
            "assumptions": asdict(self.assumptions),
            "annual_recurring_cost_at_initial_capital": self.assumptions.annual_recurring_cost(capital),
            "estimates": [
                {
                    "alternative": item.alternative_name,
                    "buy_notional": item.buy_notional,
                    "sell_notional": item.sell_notional,
                    "commission": item.commission,
                    "vat": item.vat,
                    "market_cost": item.market_cost,
                    "total_cost": item.total_cost,
                    "orders": _table(item.detail),
                }
                for item in self.estimates
            ],
            "limits": "Costos adicionales al nominal objetivo; no son ejecución autofinanciada. "
            "No se descuentan de métricas brutas o Monte Carlo. No incluye impuestos.",
        }


def review_cost_profile(run, contents: bytes) -> PilotCosts:
    settings = run.prepared.settings
    tariff = read_broker_tariff_csv(contents, as_of=settings.as_of)
    if tariff.valid_from is None:
        raise PortfolioError("Este piloto requiere un perfil de costos con vigencia explícita.")
    estimates = tuple(
        estimate_implementation_cost(
            settings.assets,
            item.metrics.weights,
            run.prepared.holdings.total_value,
            tariff.assumptions,
            alternative_name=item.name,
            current_weights=run.prepared.holdings.weights.to_numpy(),
            as_of=settings.as_of,
        )
        for item in run.alternatives
    )
    return PilotCosts(
        estimates,
        tariff.assumptions,
        tariff.source,
        tariff.consulted_on,
        sha256(contents).hexdigest(),
        tariff.tariff_kind,
    )


def evaluate_snapshot_model(run) -> dict:
    settings = run.prepared.settings
    returns = calculate_returns(run.prepared.prices)
    common = {"risk_free_rate": settings.risk_free_rate, "max_weight": settings.max_weight}
    result = {
        "client_delivery_allowed": False,
        "basis": "Hypothetical strategies; not realized account performance; costs and taxes excluded",
        "sample_end": returns.index[-1].date().isoformat(),
        "sensitivity": _table(analyze_allocation_sensitivity(returns, **common).summary),
        "historical_stress": {
            item.name: _table(historical_worst_windows(returns, item.metrics.weights))
            for item in run.alternatives
        },
    }
    # Do not silently substitute an uncalibrated estimator on short samples.
    if int(len(returns) * 0.7) >= 100:
        holdout = run_holdout_backtest(returns, covariance_shrinkage="cv", **common)
        result["holdout"] = {
            "status": "COMPUTED_GROSS",
            "training_end": holdout.training_end.isoformat(),
            "evaluation_start": holdout.evaluation_start.isoformat(),
            "evaluation_end": holdout.evaluation_end.isoformat(),
            "covariance_shrinkage": holdout.covariance_shrinkage,
            "summary": _table(holdout.summary),
            "allocations": _table(holdout.allocations),
        }
    else:
        result["holdout"] = {"status": "INSUFFICIENT_HISTORY_FOR_CALIBRATED_TRAINING"}
    if len(returns) >= 200:
        multiple = run_multi_cut_backtest(returns, covariance_shrinkage="cv", **common)
        result["four_cuts"] = {"status": "COMPUTED_GROSS", "summary": _table(multiple.summary)}
    else:
        result["four_cuts"] = {"status": "INSUFFICIENT_HISTORY_FOR_FOUR_CALIBRATED_CUTS"}
    result["benchmark"] = {"status": "PENDING_AUTHORIZED_INDEX_SERIES"}
    return result
