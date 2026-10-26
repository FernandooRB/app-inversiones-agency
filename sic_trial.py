"""Manual SIC order-draft arithmetic; never submits orders or uses origin-market prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation


class SicTrialError(ValueError):
    """Visible reason why a local-currency draft cannot be calculated."""


@dataclass(frozen=True)
class SicDraft:
    quantity: int
    estimated_entry_mxn: Decimal
    planned_loss_mxn: Decimal
    estimated_target_profit_mxn: Decimal
    estimated_risk_reward: Decimal


def _money(value: object, label: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SicTrialError(f"{label} debe ser un número válido.") from None
    if not amount.is_finite() or amount <= 0:
        raise SicTrialError(f"{label} debe ser positivo y finito.")
    return amount


def prepare_sic_draft(
    *, ask_mxn: object, stop_mxn: object, target_mxn: object,
    capital_mxn: object, max_loss_mxn: object, cost_rate: object,
) -> SicDraft:
    """Constrain whole-share quantity by both capital and planned stop loss.

    Cost is a fraction charged at entry and exit. Gap risk is not bounded here.
    """
    ask = _money(ask_mxn, "El precio de compra local")
    stop = _money(stop_mxn, "El stop local")
    target = _money(target_mxn, "El objetivo local")
    capital = _money(capital_mxn, "El capital máximo")
    loss_limit = _money(max_loss_mxn, "La pérdida máxima planeada")
    try:
        cost = Decimal(str(cost_rate))
    except (InvalidOperation, ValueError):
        raise SicTrialError("El costo debe ser un número válido.") from None
    if not cost.is_finite() or not Decimal(0) <= cost < Decimal(1):
        raise SicTrialError("El costo por lado debe estar entre 0 % y 100 %.")
    if stop >= ask or target <= ask:
        raise SicTrialError("El stop debe estar debajo de la compra y el objetivo encima.")
    entry_each = ask * (1 + cost)
    loss_each = entry_each - stop * (1 - cost)
    gain_each = target * (1 - cost) - entry_each
    if gain_each <= 0:
        raise SicTrialError("El objetivo no deja beneficio neto con el costo indicado.")
    by_capital = int((capital / entry_each).to_integral_value(rounding=ROUND_FLOOR))
    by_loss = int((loss_limit / loss_each).to_integral_value(rounding=ROUND_FLOOR))
    quantity = min(by_capital, by_loss)
    if quantity < 1:
        raise SicTrialError("Con esos límites no cabe una acción completa.")
    return SicDraft(
        quantity=quantity,
        estimated_entry_mxn=quantity * entry_each,
        planned_loss_mxn=quantity * loss_each,
        estimated_target_profit_mxn=quantity * gain_each,
        estimated_risk_reward=gain_each / loss_each,
    )
