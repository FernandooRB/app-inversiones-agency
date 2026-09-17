import numpy as np
import pandas as pd
import pytest

from allocation_policy import parse_asset_classes, parse_class_limits, policy_table
from portfolio_core import (
    AllocationGroup,
    PortfolioError,
    efficient_frontier,
    feasible_reference_weights,
    optimize_portfolio,
    random_portfolios,
)


def model():
    names = ["EQ1", "EQ2", "BOND1", "BOND2"]
    means = pd.Series([0.20, 0.16, 0.07, 0.06], index=names)
    covariance = pd.DataFrame(np.diag([0.09, 0.07, 0.01, 0.008]), index=names, columns=names)
    groups = (
        AllocationGroup("deuda", (2, 3), 0.40, 0.70),
        AllocationGroup("renta_variable", (0, 1), 0.30, 0.60),
    )
    return means, covariance, groups


def assert_policy(weights):
    equity_weight = weights[:2].sum()
    assert 0.30 - 1e-7 <= equity_weight <= 0.60 + 1e-7
    assert 0.40 - 1e-7 <= weights[2:].sum() <= 0.70 + 1e-7


def test_parse_complete_policy_and_build_report_table():
    classes = parse_asset_classes("renta_variable, renta_variable, deuda", 3)
    groups = parse_class_limits("renta_variable,20,60\ndeuda,40,80", classes)
    assert [group.name for group in groups] == ["deuda", "renta_variable"]
    assert groups[0].asset_indices == (2,)
    table = policy_table(groups)
    assert table.loc[0, "Mínimo"] == pytest.approx(0.40)


@pytest.mark.parametrize(
    "limits,message",
    [
        ("renta_variable,0,100", "Faltan límites"),
        ("renta_variable,0,100\ndeuda,0,100\notra,0,10", "no utilizadas"),
        ("renta_variable,0\ndeuda,0,100", "línea 1"),
    ],
)
def test_parser_rejects_incomplete_or_unknown_policy(limits, message):
    with pytest.raises(PortfolioError, match=message):
        parse_class_limits(limits, ("renta_variable", "deuda"))


def test_optimizers_frontier_and_cloud_obey_same_class_limits():
    means, covariance, groups = model()
    for objective in ("max_sharpe", "min_volatility"):
        result = optimize_portfolio(
            means, covariance, 0.04, objective, 0.50, groups
        )
        assert_policy(result.weights)
    frontier = efficient_frontier(means, covariance, 0.50, points=12, allocation_groups=groups)
    assert len(frontier) >= 2
    cloud = random_portfolios(
        means, covariance, 0.04, simulations=200, max_weight=0.50,
        allocation_groups=groups,
    )
    assert len(cloud) == 200


def test_reference_is_nearest_feasible_allocation_to_equal_weights():
    groups = (
        AllocationGroup("deuda", (2, 3), 0.70, 0.80),
        AllocationGroup("renta_variable", (0, 1), 0.20, 0.30),
    )
    weights = feasible_reference_weights(4, 0.60, groups)
    np.testing.assert_allclose(weights, [0.15, 0.15, 0.35, 0.35], atol=1e-7)


@pytest.mark.parametrize(
    "groups,match",
    [
        ((AllocationGroup("a", (0,), 0, 1),), "exactamente"),
        (
            (AllocationGroup("a", (0,), 0.8, 1), AllocationGroup("b", (1, 2), 0, 0.2)),
            "no cabe",
        ),
        (
            (AllocationGroup("a", (0, 1), 0.6, 1), AllocationGroup("b", (2,), 0.5, 1)),
            "no permiten",
        ),
    ],
)
def test_infeasible_policies_fail_before_optimization(groups, match):
    means = pd.Series([0.1, 0.08, 0.04])
    covariance = pd.DataFrame(np.eye(3) * 0.02)
    with pytest.raises(PortfolioError, match=match):
        optimize_portfolio(means, covariance, 0.02, max_weight=0.5, allocation_groups=groups)
