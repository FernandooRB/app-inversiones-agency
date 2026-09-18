import numpy as np
import pytest

from implementation_costs import (
    ImplementationCostAssumptions,
    estimate_implementation_cost,
)
from portfolio_core import PortfolioError


def test_cash_purchase_charges_each_order_and_adds_vat_only_to_commission():
    result = estimate_implementation_cost(
        ("AAA", "BBB"), [0.6, 0.4], 100_000,
        ImplementationCostAssumptions(
            commission_bps=25, market_cost_bps=10, vat_rate=0.16,
            minimum_commission=50,
        ),
        alternative_name="Objetivo",
    )
    assert result.starting_point == "Efectivo"
    assert result.buy_notional == pytest.approx(100_000)
    assert result.sell_notional == 0
    assert result.commission == pytest.approx(250)
    assert result.vat == pytest.approx(40)
    assert result.market_cost == pytest.approx(100)
    assert result.total_cost == pytest.approx(390)


def test_rebalance_uses_both_buy_and_sell_notionals_without_half_turnover_shortcut():
    result = estimate_implementation_cost(
        ("AAA", "BBB"), [0.7, 0.3], 100_000,
        ImplementationCostAssumptions(commission_bps=10),
        alternative_name="Objetivo", current_weights=np.array([0.4, 0.6]),
    )
    assert result.buy_notional == pytest.approx(30_000)
    assert result.sell_notional == pytest.approx(30_000)
    assert result.traded_notional == pytest.approx(60_000)
    assert result.commission == pytest.approx(60)
    assert result.detail["Operación"].tolist() == ["Compra", "Venta"]


def test_minimum_commission_is_applied_per_nonzero_order_and_unchanged_target_costs_zero():
    assumptions = ImplementationCostAssumptions(commission_bps=1, minimum_commission=20)
    result = estimate_implementation_cost(
        ("AAA", "BBB", "CCC"), [0.5, 0.3, 0.2], 10_000, assumptions,
        alternative_name="Objetivo", current_weights=[0.5, 0.3, 0.2],
    )
    assert result.detail.empty
    assert result.total_cost == 0
    from_cash = estimate_implementation_cost(
        ("AAA", "BBB", "CCC"), [0.5, 0.3, 0.2], 10_000, assumptions,
        alternative_name="Objetivo",
    )
    assert from_cash.commission == 60


def test_zero_reference_capital_has_no_orders_or_costs():
    result = estimate_implementation_cost(
        ("AAA",), [1], 0,
        ImplementationCostAssumptions(commission_bps=25, minimum_commission=50),
        alternative_name="Objetivo",
    )
    assert result.detail.empty
    assert result.total_cost == 0


def test_annual_recurring_cost_keeps_fixed_and_asset_based_costs_separate():
    assumptions = ImplementationCostAssumptions(
        annual_fixed_cost=1_200, annual_management_rate=0.01,
    )
    assert assumptions.annual_recurring_cost(100_000) == pytest.approx(2_200)


@pytest.mark.parametrize(
    "assumptions",
    [
        ImplementationCostAssumptions(commission_bps=-1),
        ImplementationCostAssumptions(market_cost_bps=501),
        ImplementationCostAssumptions(vat_rate=1.01),
        ImplementationCostAssumptions(minimum_commission=-1),
        ImplementationCostAssumptions(annual_fixed_cost=1_000_001),
        ImplementationCostAssumptions(annual_management_rate=0.201),
    ],
)
def test_rejects_invalid_cost_assumptions(assumptions):
    with pytest.raises(PortfolioError):
        estimate_implementation_cost(
            ("AAA",), [1], 1000, assumptions, alternative_name="Objetivo"
        )
