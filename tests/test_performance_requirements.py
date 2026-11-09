"""Calendar coverage must explain missing inputs without selecting favorable flow timing."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from portfolio_core import PortfolioError
from realized_performance import Flow, normalize_valuations, performance, valuation_requirements

D = date(2026, 1, 1)


def test_eod_flows_share_one_required_close_and_need_no_previous_day():
    flows = [Flow(D + timedelta(days=4), 50, "EOD"), Flow(D + timedelta(days=4), 20, "EOD")]
    dates = [D, D + timedelta(days=4), D + timedelta(days=9)]
    result = valuation_requirements(D, dates[-1], flows, available_dates=dates)
    assert result["twr_coverage_ready"] and len(result["rows"]) == 3
    assert result["missing_required_dates"] == result["missing_conditional_dates"] == []


def test_unknown_timing_does_not_become_eod_when_all_possible_dates_exist():
    flows = [
        Flow(D + timedelta(days=4), 50),
        Flow(D + timedelta(days=4), 20),
        Flow(D + timedelta(days=6), -10),
    ]
    dates = [D + timedelta(days=n) for n in (0, 3, 4, 5, 6, 9)]
    result = valuation_requirements(D, dates[-1], flows, available_dates=dates)
    assert not result["twr_coverage_ready"] and result["unknown_flow_count"] == 3
    assert result["missing_required_dates"] == result["missing_conditional_dates"] == []
    assert result["unknown_flow_dates"] == [str(dates[2]), str(dates[4])]
    nav = pd.Series([100, 100, 170, 170, 160, 160], index=dates)
    assert performance(nav, flows)["twr"] is None
    assert all(flow.timing == "UNKNOWN" for flow in flows)


def test_missing_required_and_conditional_dates_stay_separate():
    flows = [Flow(D + timedelta(days=4), 50), Flow(D + timedelta(days=6), -10)]
    result = valuation_requirements(
        D, D + timedelta(days=9), flows, available_dates=[D, D + timedelta(days=9)]
    )
    assert result["missing_required_dates"] == ["2026-01-05", "2026-01-07"]
    assert result["missing_conditional_dates"] == ["2026-01-04", "2026-01-06"]


def test_bod_requires_previous_calendar_close_not_automatic_friday_substitution():
    monday = date(2026, 1, 5)
    result = valuation_requirements(
        D, monday, [Flow(monday, 100, "BOD")], available_dates=[D, D + timedelta(days=1), monday]
    )
    assert not result["twr_coverage_ready"] and result["missing_required_dates"] == ["2026-01-04"]
    assert not result["missing_conditional_dates"]


def test_bod_previous_close_can_be_the_initial_close_without_duplicate_rows():
    end = D + timedelta(days=1)
    result = valuation_requirements(D, end, [Flow(end, 100, "BOD")], available_dates=[D, end])
    assert result["twr_coverage_ready"] and len(result["rows"]) == 2
    assert "Cierre anterior a flujo BOD" in result["rows"][0]["reasons"]
    assert performance(pd.Series([100, 220], index=[D, end]), [Flow(end, 100, "BOD")])[
        "twr"
    ] == pytest.approx(0.1)


def test_known_bod_flow_makes_shared_conditional_date_required():
    end = D + timedelta(days=2)
    result = valuation_requirements(D, end, [Flow(end, 100), Flow(end, 10, "BOD")], available_dates=[D, end])
    assert result["missing_required_dates"] == ["2026-01-02"]
    assert not result["missing_conditional_dates"] and not result["twr_coverage_ready"]


def test_no_flows_requires_only_period_endpoints():
    end = D + timedelta(days=30)
    result = valuation_requirements(D, end, [], available_dates=[D, end])
    assert len(result["rows"]) == 2 and result["twr_coverage_ready"]


@pytest.mark.parametrize(
    "bad",
    [
        "NaT",
        None,
        "invalid",
        0,
        "2026-01-01T12:00:00",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00.000000001",
    ],
)
def test_available_date_must_be_a_real_date_without_zone_or_subday_time(bad):
    with pytest.raises(PortfolioError):
        valuation_requirements(D, D + timedelta(days=10), [], available_dates=[bad])


@pytest.mark.parametrize(
    "flow",
    [
        Flow(D, 10),
        Flow(D + timedelta(days=11), 10),
        Flow(D + timedelta(days=1), 10, "NOON"),
        Flow(datetime(2026, 1, 2), 10),
    ],
)
def test_invalid_or_out_of_period_flow_is_rejected(flow):
    with pytest.raises(PortfolioError):
        valuation_requirements(D, D + timedelta(days=10), [flow])


@pytest.mark.parametrize(
    "days",
    [
        [None, "2026-01-02"],
        ["NaT", "2026-01-02"],
        ["2026-01-01", "2026-01-01"],
        ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        ["2026-01-01T00:00:00.000000001", "2026-01-02T00:00:00"],
        ["2026-01-01T12:00:00", "2026-01-02T00:00:00"],
    ],
)
def test_invalid_nav_dates_cannot_count_as_closing_coverage(days):
    with pytest.raises(PortfolioError):
        performance(pd.Series([100, 101], index=days), [])


def test_nav_normalization_does_not_mutate_values_or_fill_missing_dates():
    source = pd.Series([110, 100], index=["2026-01-03", "2026-01-01"])
    original = source.copy()
    normalized = normalize_valuations(source)
    assert source.equals(original) and len(normalized) == 2
    assert list(normalized.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-03"]


def test_performance_returns_the_same_missing_date_plan_used_by_preflight():
    end = D + timedelta(days=365)
    flows = [Flow(D + timedelta(days=180), 100, "EOD")]
    result = performance(pd.Series([100, 220], index=[D, end]), flows)
    assert result["twr"] is None and result["xirr"] is not None
    assert result["valuation_requirements"] == valuation_requirements(D, end, flows, available_dates=[D, end])
