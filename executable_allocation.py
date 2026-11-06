"""Cost-aware allocation and integer-lot proposals; this module never sends orders."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp, minimize

from implementation_costs import ImplementationCostAssumptions, _validate_assumptions
from portfolio_core import PortfolioError


def cost_aware_target(
    mean, covariance, current, *, cost_rate=0.002, risk_aversion=4.0, max_weight=1.0, max_turnover=0.5
):
    """Annual mean-variance utility minus proportional implementation cost.

    Turnover is sum(abs(target-current)), counting both legs. Minimum fees and
    lots are handled by executable_plan rather than this convex approximation.
    """
    mean, covariance, current = map(np.asarray, (mean, covariance, current))
    n = len(current)
    if (
        not n
        or mean.shape != (n,)
        or covariance.shape != (n, n)
        or not all(np.isfinite(v).all() for v in (mean, covariance, current))
        or np.any(current < 0)
        or not np.isclose(current.sum(), 1)
        or not 0 <= cost_rate <= 0.2
        or not 0 < risk_aversion <= 100
        or not 1 / n <= max_weight <= 1
        or not 0 <= max_turnover <= 2
    ):
        raise PortfolioError("Los supuestos de optimización con costos no son válidos.")
    if not np.allclose(covariance, covariance.T) or np.linalg.eigvalsh(covariance).min() < -1e-9:
        raise PortfolioError("La covarianza debe ser simétrica y semidefinida positiva.")
    # Auxiliary distances remove abs() at the SLSQP objective/constraint boundary.
    x0 = np.r_[np.repeat(1 / n, n), np.abs(np.repeat(1 / n, n) - current)]
    result = minimize(
        lambda x: risk_aversion / 2 * x[:n] @ covariance @ x[:n] - mean @ x[:n] + cost_rate * x[n:].sum(),
        x0,
        method="SLSQP",
        bounds=[(0, max_weight)] * n + [(0, 2)] * n,
        constraints=[
            {"type": "eq", "fun": lambda x: x[:n].sum() - 1},
            {"type": "ineq", "fun": lambda x: x[n:] - (x[:n] - current)},
            {"type": "ineq", "fun": lambda x: x[n:] + (x[:n] - current)},
            {"type": "ineq", "fun": lambda x: max_turnover - x[n:].sum()},
        ],
        options={"maxiter": 1000, "ftol": 1e-10},
    )
    if (
        not result.success
        or np.abs(result.x[:n] - current).sum() > max_turnover + 1e-6
        or abs(result.x[:n].sum() - 1) > 1e-6
    ):
        raise PortfolioError("No se encontró una cartera que cumpla costos, concentración y rotación.")
    return result.x[:n]


def executable_plan(
    positions: pd.DataFrame,
    cash: float,
    target,
    assumptions=None,
    *,
    cash_floor=0.0,
    max_turnover=2.0,
    max_weight=1.0,
    minimum_trade=0.0,
    cost_penalty=1.0,
    class_limits=None,
    quotes_confirmed=False,
):
    """MILP minimizes absolute target-value error plus cost, with exact cash constraints.

    Input columns: Instrumento,Cantidad,Precio,Lote[,Clase]. All values use one
    declared account currency and same dated raw executable quote source.
    No assumed broker tariff: supplied assumptions must be confirmed in the UI.
    """
    assumptions = assumptions or ImplementationCostAssumptions()
    _validate_assumptions(assumptions)
    required = {"Instrumento", "Cantidad", "Precio", "Lote"}
    if quotes_confirmed is not True or not required.issubset(positions) or not 0 < len(positions) <= 25:
        raise PortfolioError(
            "Confirma cotizaciones sin ajuste e importa cantidad, precio y lote de 1 a 25 activos."
        )
    frame = positions.copy()
    if frame["Instrumento"].duplicated().any() or frame["Instrumento"].astype(str).str.strip().eq("").any():
        raise PortfolioError("Cada instrumento debe aparecer una sola vez.")
    try:
        quantity, price, lot = (frame[key].to_numpy(dtype=float) for key in ("Cantidad", "Precio", "Lote"))
        target = np.asarray(target, dtype=float)
    except (ValueError, TypeError) as exc:
        raise PortfolioError("Las cantidades, cotizaciones, lotes y pesos deben ser numéricos.") from exc
    n = len(frame)
    parameters = np.r_[
        quantity, price, lot, target, cash, cash_floor, max_turnover, max_weight, minimum_trade, cost_penalty
    ]
    if (
        target.shape != (n,)
        or not np.isfinite(parameters).all()
        or np.any(quantity < 0)
        or np.any(price <= 0)
        or np.any(lot <= 0)
        or np.any(target < 0)
        or target.sum() > 1 + 1e-8
        or cash < cash_floor
        or cash_floor < 0
        or not 0 <= max_turnover <= 2
        or not 0 < max_weight <= 1
        or minimum_trade < 0
        or not 0 < cost_penalty <= 100
    ):
        raise PortfolioError("Los límites de títulos, efectivo, pesos o costos no son válidos.")
    nav = float(quantity @ price + cash)
    if nav <= 0:
        raise PortfolioError("El patrimonio disponible debe ser positivo.")
    lp, held = lot * price, quantity * price
    commission = assumptions.commission_bps / 10000
    market = assumptions.market_cost_bps / 10000
    vat = 1 + assumptions.vat_rate
    buy_max = np.floor((nav - cash_floor) / lp)
    sell_max = np.floor(quantity / lot + 1e-10)
    # Eight n-sized blocks: buy lots, sell lots, buy/sell active, buy/sell fees, +/- deviations.
    count = 8 * n
    lower, upper = np.zeros(count), np.full(count, np.inf)
    upper[:n], upper[n : 2 * n] = buy_max, sell_max
    upper[2 * n : 4 * n] = 1
    upper[4 * n : 6 * n] = max(commission * nav, assumptions.minimum_commission)
    integrality = np.r_[np.ones(4 * n), np.zeros(4 * n)]
    objective = np.zeros(count)
    objective[:n] = cost_penalty * market * lp / nav
    objective[n : 2 * n] = cost_penalty * market * lp / nav
    objective[4 * n : 6 * n] = cost_penalty * vat / nav
    # Up to three cents per active order reserve cash for cent rounding of
    # notional, commission+VAT and market cost. Actual charges are recomputed below.
    objective[2 * n : 4 * n] = cost_penalty * 0.03 / nav
    objective[6 * n :] = 1 / nav
    rows, lows, highs = [], [], []

    def constraint(entries, low=-np.inf, high=np.inf):
        row = np.zeros(count)
        for key, value in entries.items():
            row[key] = value
        rows.append(row)
        lows.append(low)
        highs.append(high)

    for i in range(n):
        b, s, zb, zs, fb, fs, plus, minus = (k * n + i for k in range(8))
        constraint({b: 1, zb: -buy_max[i]}, high=0)
        constraint({s: 1, zs: -sell_max[i]}, high=0)
        constraint({zb: 1, zs: 1}, high=1)
        constraint({b: lp[i], zb: -max(minimum_trade, lp[i])}, low=0)
        constraint({s: lp[i], zs: -max(minimum_trade, lp[i])}, low=0)
        for lots, active, fee in ((b, zb, fb), (s, zs, fs)):
            constraint({fee: 1, lots: -commission * lp[i]}, low=0)
            constraint({fee: 1, active: -assumptions.minimum_commission}, low=0)
            constraint({fee: 1, active: -upper[fee]}, high=0)
        desired = target[i] * nav - held[i]
        constraint({b: lp[i], s: -lp[i], plus: -1, minus: 1}, desired, desired)
        constraint({b: lp[i], s: -lp[i]}, high=max_weight * nav - held[i])
    budget = {
        **{i: lp[i] * (1 + market) for i in range(n)},
        **{n + i: lp[i] * (-1 + market) for i in range(n)},
        **dict.fromkeys(range(4 * n, 6 * n), vat),
        **dict.fromkeys(range(2 * n, 4 * n), 0.03),
    }
    constraint(budget, high=cash - cash_floor)
    constraint({i: lp[i % n] for i in range(2 * n)}, high=nav * max_turnover)
    for label, limit in (class_limits or {}).items():
        if "Clase" not in frame or not 0 <= limit <= 1:
            raise PortfolioError("Los límites por clase requieren etiquetas y proporciones válidas.")
        mask = frame["Clase"].eq(label).to_numpy()
        if not mask.any():
            raise PortfolioError("Un límite de clase no corresponde a los instrumentos.")
        entries = {i: lp[i] for i in np.flatnonzero(mask)}
        entries.update({n + i: -lp[i] for i in np.flatnonzero(mask)})
        constraint(entries, high=limit * nav - held[mask].sum())
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(np.asarray(rows), lows, highs),
        options={"time_limit": 10, "mip_rel_gap": 1e-6},
    )
    if result.x is None or result.status not in {0, 1}:
        raise PortfolioError("No existe una propuesta de lotes que cumpla efectivo, rotación y límites.")
    buys, sells = np.rint(result.x[:n]), np.rint(result.x[n : 2 * n])
    if np.max(np.abs(np.r_[buys, sells] - result.x[: 2 * n])) > 1e-5:
        raise PortfolioError("El solucionador no devolvió títulos enteros por lote.")
    delta = (buys - sells) * lot
    cent = Decimal("0.01")
    notional = np.array(
        [
            float((Decimal(str(abs(q))) * Decimal(str(p))).quantize(cent, rounding=ROUND_HALF_UP))
            for q, p in zip(delta, price, strict=True)
        ]
    )
    commissions = np.where(notional > 0, np.maximum(notional * commission, assumptions.minimum_commission), 0)
    commission_vat = np.array(
        [float(Decimal(str(value * vat)).quantize(cent, rounding=ROUND_CEILING)) for value in commissions]
    )
    market_cost = np.array(
        [float(Decimal(str(value * market)).quantize(cent, rounding=ROUND_CEILING)) for value in notional]
    )
    costs = commission_vat + market_cost
    signed_notional = np.sign(delta) * notional
    remaining = cash - signed_notional.sum() - costs.sum()
    final = quantity + delta
    if (
        remaining < cash_floor - 1e-5
        or np.any(final < -1e-8)
        or notional.sum() > nav * max_turnover + 1e-5
        or np.any(final * price > nav * max_weight + 1e-5)
    ):
        raise PortfolioError("La comprobación final de efectivo y límites rechazó la propuesta.")
    frame["Títulos a operar"] = delta
    frame["PesoObjetivo"] = target
    frame["Importe firmado"] = signed_notional
    frame["Comisión e IVA"] = commission_vat
    frame["Costo de mercado"] = market_cost
    frame["Títulos finales"] = final
    frame["Peso final sobre capital inicial"] = final * price / nav
    return {
        "detail": frame,
        "cash": float(remaining),
        "cost": float(costs.sum()),
        "turnover": float(notional.sum() / nav),
        "optimal": result.status == 0,
        "basis": "Pesos y límites sobre capital inicial. Importes a centavos; cargos redondeados "
        "hacia arriba y reserva de hasta 3 centavos por orden. Confirma el redondeo de tu intermediario.",
    }
