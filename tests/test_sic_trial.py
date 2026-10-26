from decimal import Decimal

import pytest

from sic_trial import SicTrialError, prepare_sic_draft


def test_quantity_is_constrained_by_capital_and_planned_stop_loss():
    draft = prepare_sic_draft(
        ask_mxn="100", stop_mxn="90", target_mxn="125",
        capital_mxn="1000", max_loss_mxn="25", cost_rate="0.01",
    )
    # Entry 101, stop proceeds 89.10, loss 11.90 per share -> 2 shares.
    assert draft.quantity == 2
    assert draft.estimated_entry_mxn == Decimal("202.00")
    assert draft.planned_loss_mxn == Decimal("23.80")
    assert draft.estimated_target_profit_mxn == Decimal("45.50")


@pytest.mark.parametrize("overrides", [
    {"stop_mxn": "100"}, {"target_mxn": "100"},
    {"ask_mxn": "NaN"}, {"capital_mxn": "0"},
    {"max_loss_mxn": "1"}, {"cost_rate": "1"},
    {"target_mxn": "101", "cost_rate": "0.02"},
])
def test_invalid_or_unaffordable_draft_is_rejected(overrides):
    inputs = dict(ask_mxn="100", stop_mxn="90", target_mxn="125",
                  capital_mxn="1000", max_loss_mxn="25", cost_rate="0.01")
    inputs.update(overrides)
    with pytest.raises(SicTrialError):
        prepare_sic_draft(**inputs)
