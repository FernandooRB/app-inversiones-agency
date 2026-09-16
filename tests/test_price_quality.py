import pandas as pd

from price_quality import assess_price_quality


def test_detects_jump_and_one_complete_unchanged_run_with_dates():
    dates = pd.date_range("2024-01-02", periods=11, freq="B")
    prices = pd.DataFrame({
        "AAA": [100, 101, 150, 150, 150, 150, 150, 150, 151, 151, 152],
        "BBB": [100 + value for value in range(11)],
    }, index=dates)
    issues = assess_price_quality(prices)
    assert len(issues) == 2
    jump, flat = issues
    assert (jump.ticker, jump.kind, jump.first_date, jump.last_date, jump.detail) == (
        "AAA", "Salto de precio", "2024-01-03", "2024-01-04", "+48.51%",
    )
    assert (flat.ticker, flat.kind, flat.first_date, flat.last_date, flat.detail) == (
        "AAA", "Cierre sin cambio", "2024-01-04", "2024-01-11",
        "5 sesiones consecutivas sin variación",
    )


def test_four_unchanged_sessions_are_below_threshold_and_end_run_is_counted():
    dates = pd.date_range("2024-02-01", periods=8, freq="B")
    short = pd.DataFrame({"AAA": [100, 100, 100, 100, 100, 101, 102, 103]}, index=dates)
    assert assess_price_quality(short) == ()
    complete = pd.DataFrame({"AAA": [100, 101, 101, 101, 101, 101, 101, 101]}, index=dates)
    issues = assess_price_quality(complete)
    assert len(issues) == 1
    assert issues[0].detail == "6 sesiones consecutivas sin variación"
    assert issues[0].last_date == "2024-02-12"
