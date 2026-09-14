"""Hypothetical portfolio paths; historical estimates are not forecasts."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import MIN_OBSERVATIONS, PortfolioError, validate_weights

SESSIONS_PER_MONTH = 21


@dataclass(frozen=True)
class SimulationResult:
    """Nominal month-end values, with path columns and month-zero in row zero."""

    monthly_values: np.ndarray
    invested_capital: np.ndarray
    real_terminal_values: np.ndarray
    method: str
    seed: int
    shortfall_paths: np.ndarray
    total_withdrawn: np.ndarray

    def bands(self) -> pd.DataFrame:
        percentiles = np.quantile(self.monthly_values, [0.05, 0.5, 0.95], axis=1).T
        return pd.DataFrame(
            {
                "Mes": np.arange(len(self.invested_capital)),
                "Percentil 5": percentiles[:, 0],
                "Mediana": percentiles[:, 1],
                "Percentil 95": percentiles[:, 2],
                "Capital aportado": self.invested_capital,
            }
        )

    @property
    def probability_below_contributions(self) -> float:
        """Fraction of simulated endings below nominal capital contributed."""
        return float(np.mean(self.monthly_values[-1] < self.invested_capital[-1]))

    @property
    def probability_of_shortfall(self) -> float:
        """Fraction of paths unable to cover at least one scheduled withdrawal."""
        return float(np.mean(self.shortfall_paths))


def _validate_inputs(
    returns, weights, initial_value, months, paths, monthly_contribution, monthly_withdrawal,
    annual_fee, transaction_cost_bps, rebalance_months, inflation_rate, seed, block_days,
    method,
):
    if not isinstance(returns, pd.DataFrame) or len(returns) < MIN_OBSERVATIONS - 1:
        raise PortfolioError("Se requieren al menos 59 retornos diarios para simular.")
    data = returns.to_numpy(dtype=float)
    if data.ndim != 2 or data.shape[1] == 0 or not np.isfinite(data).all() or (data <= -1).any():
        raise PortfolioError("Los retornos deben ser finitos y mayores a -100%.")
    validate_weights(weights, data.shape[1])
    if method not in {"bootstrap_blocks", "lognormal"}:
        raise PortfolioError("Método de simulación no reconocido.")
    if not isinstance(months, int) or not 1 <= months <= 120:
        raise PortfolioError("El horizonte debe estar entre 1 y 120 meses.")
    if not isinstance(paths, int) or not 100 <= paths <= 2000:
        raise PortfolioError("El número de trayectorias debe estar entre 100 y 2,000.")
    if not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise PortfolioError("La semilla debe ser un entero no negativo de 32 bits.")
    if not isinstance(block_days, int) or not 1 <= block_days <= min(63, len(data)):
        raise PortfolioError("El bloque histórico debe tener entre 1 y 63 sesiones disponibles.")
    if rebalance_months not in {None, 3, 6, 12}:
        raise PortfolioError("Rebalanceo no reconocido.")
    for value in (
        initial_value, monthly_contribution, monthly_withdrawal,
        annual_fee, transaction_cost_bps, inflation_rate,
    ):
        if not np.isfinite(value):
            raise PortfolioError("Los supuestos de simulación deben ser finitos.")
    if initial_value <= 0 or monthly_contribution < 0 or monthly_withdrawal < 0:
        raise PortfolioError("El capital debe ser positivo; aportaciones y retiros no negativos.")
    if monthly_contribution > 0 and monthly_withdrawal > 0:
        raise PortfolioError("Elige aportaciones o retiros mensuales para un escenario, no ambos.")
    if not 0 <= annual_fee < 1 or not 0 <= transaction_cost_bps <= 500:
        raise PortfolioError("Comisión anual o costo de operación fuera del rango permitido.")
    if not -0.5 < inflation_rate <= 1:
        raise PortfolioError("Inflación anual fuera del rango permitido.")
    return data, np.asarray(weights, dtype=float)


def simulate_portfolio_paths(
    returns: pd.DataFrame,
    weights,
    *,
    initial_value: float,
    months: int,
    paths: int = 500,
    monthly_contribution: float = 0.0,
    monthly_withdrawal: float = 0.0,
    annual_fee: float = 0.0,
    transaction_cost_bps: float = 0.0,
    rebalance_months: int | None = 12,
    inflation_rate: float = 0.0,
    method: str = "bootstrap_blocks",
    seed: int = 42,
    block_days: int = 21,
) -> SimulationResult:
    """Simulate correlated asset returns and deterministic cash-flow rules.

    Contributions or withdrawals occur at month-end. Withdrawals sell holdings
    proportionally and stop at zero; any unpaid amount flags a shortfall. Trading
    cost is charged on initial/contribution purchases, withdrawal sales and
    gross traded notional at each rebalance.
    Annual fees accrue daily. No tax, spread, liquidity or regime model is included.
    """
    data, target_weights = _validate_inputs(
        returns, weights, initial_value, months, paths, monthly_contribution,
        monthly_withdrawal,
        annual_fee, transaction_cost_bps, rebalance_months, inflation_rate, seed,
        block_days, method,
    )
    rng = np.random.default_rng(seed)
    cost_rate = transaction_cost_bps / 10_000
    fee_factor = (1 - annual_fee) ** (1 / (12 * SESSIONS_PER_MONTH))
    holdings = np.broadcast_to(
        initial_value * (1 - cost_rate) * target_weights, (paths, len(target_weights))
    ).copy()
    monthly_values = np.empty((months + 1, paths))
    monthly_values[0] = holdings.sum(axis=1)
    invested = initial_value + monthly_contribution * np.arange(months + 1)
    shortfall_paths = np.zeros(paths, dtype=bool)
    total_withdrawn = np.zeros(paths)

    if method == "lognormal":
        log_returns = np.log1p(data)
        log_mean = log_returns.mean(axis=0)
        log_covariance = np.atleast_2d(np.cov(log_returns, rowvar=False))
        eigenvalues, eigenvectors = np.linalg.eigh(log_covariance)
        factor = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))

    block_start = None
    for day in range(1, months * SESSIONS_PER_MONTH + 1):
        if method == "bootstrap_blocks":
            offset = (day - 1) % block_days
            if offset == 0:
                block_start = rng.integers(0, len(data) - block_days + 1, size=paths)
            daily_growth = 1 + data[block_start + offset]
        else:
            log_draw = rng.standard_normal((paths, len(target_weights))) @ factor.T + log_mean
            daily_growth = np.exp(log_draw)
        holdings *= daily_growth * fee_factor

        if day % SESSIONS_PER_MONTH == 0:
            month = day // SESSIONS_PER_MONTH
            holdings += monthly_contribution * (1 - cost_rate) * target_weights
            if monthly_withdrawal > 0:
                before = holdings.sum(axis=1)
                gross_sale = np.minimum(before, monthly_withdrawal / (1 - cost_rate))
                paid = gross_sale * (1 - cost_rate)
                total_withdrawn += paid
                shortfall_paths |= paid < monthly_withdrawal - 1e-8
                remaining_fraction = np.divide(
                    before - gross_sale, before,
                    out=np.zeros_like(before), where=before > 0,
                )
                holdings *= remaining_fraction[:, None]
            if rebalance_months is not None and month % rebalance_months == 0:
                before = holdings.sum(axis=1)
                desired = before[:, None] * target_weights
                traded_notional = np.abs(desired - holdings).sum(axis=1)
                after = before - cost_rate * traded_notional
                holdings = after[:, None] * target_weights
            monthly_values[month] = holdings.sum(axis=1)
        if not np.isfinite(holdings).all():
            raise PortfolioError("La simulación produjo valores no finitos; revisa los supuestos.")

    real_terminal = monthly_values[-1] / (1 + inflation_rate) ** (months / 12)
    return SimulationResult(
        monthly_values, invested, real_terminal, method, seed,
        shortfall_paths, total_withdrawn,
    )
