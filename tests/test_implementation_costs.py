from datetime import date, timedelta

import numpy as np
import pytest

from implementation_costs import (
    ImplementationCostAssumptions,
    OrderCostRule,
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


def _rule(asset, operation, commission_bps, *, market_cost_bps=0, minimum=0,
          valid_from=None, valid_until=None, annual_fixed_cost=0):
    return OrderCostRule(
        asset=asset, operation=operation, intermediary="Casa de prueba",
        product="Capitales", market="BMV",
        valid_from=valid_from or date.today(), valid_until=valid_until,
        consulted_on=date.today(), tariff_kind="NEGOCIADA_CLIENTE",
        source="Acuerdo de prueba", assumptions=ImplementationCostAssumptions(
            commission_bps=commission_bps, market_cost_bps=market_cost_bps,
            vat_rate=0.16, minimum_commission=minimum,
            annual_fixed_cost=annual_fixed_cost,
        ),
    )


def test_order_rules_apply_each_assets_documented_rate_and_minimum():
    result = estimate_implementation_cost(
        ("AAA", "BBB"), [0.6, 0.4], 100_000,
        ImplementationCostAssumptions(annual_fixed_cost=1_000),
        alternative_name="Objetivo",
        order_rules=(
            _rule("AAA", "Ambas", 12, market_cost_bps=5),
            _rule("BBB", "Ambas", 25, market_cost_bps=10, minimum=120),
        ),
    )
    assert result.detail["Comisión"].tolist() == pytest.approx([72, 120])
    assert result.commission == pytest.approx(192)
    assert result.vat == pytest.approx(30.72)
    assert result.market_cost == pytest.approx(70)
    assert result.total_cost == pytest.approx(292.72)
    assert result.detail["Comisión aplicada (pb)"].tolist() == [12, 25]
    assert result.detail["Tipo tarifa"].tolist() == ["NEGOCIADA_CLIENTE"] * 2


def test_order_rules_require_the_correct_buy_and_sell_directions():
    result = estimate_implementation_cost(
        ("AAA", "BBB"), [0.7, 0.3], 100_000,
        ImplementationCostAssumptions(), alternative_name="Rebalanceo",
        current_weights=[0.4, 0.6],
        order_rules=(_rule("AAA", "Compra", 10), _rule("BBB", "Venta", 20)),
    )
    assert result.detail["Operación"].tolist() == ["Compra", "Venta"]
    assert result.commission == pytest.approx(90)


def test_order_rules_fail_closed_when_a_trade_has_no_rule():
    with pytest.raises(PortfolioError, match="BBB.*compra"):
        estimate_implementation_cost(
            ("AAA", "BBB"), [0.5, 0.5], 100_000,
            ImplementationCostAssumptions(), alternative_name="Objetivo",
            order_rules=(_rule("AAA", "Ambas", 10),),
        )


def test_order_rules_reject_overlap_and_expired_terms():
    base = dict(
        tickers=("AAA",), target_weights=[1], portfolio_value=100_000,
        assumptions=ImplementationCostAssumptions(), alternative_name="Objetivo",
    )
    with pytest.raises(PortfolioError, match="duplicadas o superpuestas"):
        estimate_implementation_cost(
            **base, order_rules=(_rule("AAA", "Ambas", 10), _rule("AAA", "Compra", 12)),
        )
    with pytest.raises(PortfolioError, match="no está vigente"):
        estimate_implementation_cost(
            **base, order_rules=(_rule(
                "AAA", "Ambas", 10, valid_from=date.today() - timedelta(days=10),
                valid_until=date.today() - timedelta(days=1),
            ),),
        )


def test_historical_order_cost_cannot_use_a_later_consultation():
    with pytest.raises(PortfolioError, match="consultó después"):
        estimate_implementation_cost(
            ("AAA",), [1], 100_000, ImplementationCostAssumptions(),
            alternative_name="Histórico",
            order_rules=(_rule(
                "AAA", "Ambas", 10, valid_from=date.today() - timedelta(days=10),
            ),),
            as_of=date.today() - timedelta(days=1),
        )


def test_order_rules_keep_transactional_and_annual_terms_separate():
    base = dict(
        tickers=("AAA",), target_weights=[1], portfolio_value=100_000,
        alternative_name="Objetivo",
    )
    with pytest.raises(PortfolioError, match="transaccionales generales"):
        estimate_implementation_cost(
            **base, assumptions=ImplementationCostAssumptions(commission_bps=25),
            order_rules=(_rule("AAA", "Ambas", 10),),
        )
    with pytest.raises(PortfolioError, match="costos anuales"):
        estimate_implementation_cost(
            **base, assumptions=ImplementationCostAssumptions(),
            order_rules=(_rule("AAA", "Ambas", 10, annual_fixed_cost=1_000),),
        )


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
