"""Reviewed strategy provenance and comparable lot plans; never sends orders."""

import math
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from hashlib import sha256

import numpy as np
import pandas as pd

from account_workflow import INPUT_NAMES, code_fingerprint
from analysis_session import analysis_key
from executable_allocation import executable_plan
from implementation_costs import ImplementationCostAssumptions, _validate_assumptions
from portfolio_core import PortfolioError
from portfolio_exposure import _text
from transaction_ledger import latest_review_day

STRATEGY_FIELDS = {
    "schema",
    "name",
    "run_id",
    "analysis_key",
    "code_sha256",
    "files_sha256",
    "assets",
    "weights",
    "currency",
    "as_of",
    "history_start",
    "sample_start",
    "sample_end",
}


def validate_strategy(value, assets, cutoff, currency, target):
    """Check bounded historical provenance; hashes establish integrity, not authorship."""
    try:
        if (
            not isinstance(value, dict)
            or set(value) != STRATEGY_FIELDS
            or type(value["schema"]) is not int
            or value["schema"] != 1
        ):
            raise ValueError
        if not isinstance(value["name"], str) or not _text(value["name"].lstrip()):
            raise ValueError
        for field, length in [("run_id", 32), ("analysis_key", 64), ("code_sha256", 64)]:
            if not isinstance(value[field], str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value[field]):
                raise ValueError
        if value["assets"] != list(assets) or not 0 < len(assets) <= 25 or len(set(assets)) != len(assets):
            raise ValueError
        if any(not isinstance(a, str) or not _text(a.lstrip()) for a in assets):
            raise ValueError
        weights = value["weights"]
        if (
            not isinstance(weights, list)
            or len(weights) != len(assets)
            or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in weights)
        ):
            raise ValueError
        if not np.isclose(sum(weights), 1, atol=1e-7, rtol=0) or not np.allclose(
            weights, target, atol=1e-9, rtol=0
        ):
            raise ValueError
        if value["currency"] != currency or currency != "MXN" or value["as_of"] != str(cutoff):
            raise ValueError
        days = [
            date.fromisoformat(value[k]) for k in ("history_start", "sample_start", "sample_end", "as_of")
        ]
        if (
            any(
                d.isoformat() != value[k]
                for d, k in zip(days, ("history_start", "sample_start", "sample_end", "as_of"), strict=True)
            )
            or not days[0] <= days[1] <= days[2] <= days[3] <= latest_review_day()
        ):
            raise ValueError
        hashes = value["files_sha256"]
        if (
            not isinstance(hashes, dict)
            or not {"holdings", "prices", "rights"}.issubset(hashes)
            or not set(hashes).issubset(INPUT_NAMES)
        ):
            raise ValueError
        if any(not isinstance(v, str) or not re.fullmatch("[0-9a-f]{64}", v) for v in hashes.values()):
            raise ValueError
        return deepcopy(value)
    except (ValueError, TypeError, KeyError):
        raise PortfolioError(
            "La procedencia de la estrategia no coincide con sus pesos, fechas o instrumentos."
        ) from None


def strategy_from_analysis(flow, binding, assets, cutoff, currency, name):
    """Require the exact identity/store/account and a current, calculated input snapshot."""
    if not flow or tuple(flow.get("context", ())) != tuple(binding) or len(binding) != 4:
        raise PortfolioError("Abre un análisis de esta misma cuenta e identidad.")
    completed = flow.get("completed")
    if not completed:
        raise PortfolioError("Primero calcula el análisis de esta cuenta.")
    settings, result = completed["settings"], completed["result"]
    version = code_fingerprint()
    expected = analysis_key(completed["files"], asdict(settings), completed["metadata"], version)
    if (
        result["code_sha256"] != version
        or result["key"] != expected
        or flow.get("files") != completed["files"]
        or flow.get("metadata") != completed["metadata"]
        or any(flow.get("defaults", {}).get(k, v) != v for k, v in asdict(settings).items())
    ):
        raise PortfolioError(
            "Hay cambios sin calcular o una versión distinta; vuelve a calcular el análisis."
        )
    if currency != "MXN" or str(cutoff) != settings.as_of or tuple(assets) != settings.assets:
        raise PortfolioError("El análisis debe coincidir en corte, moneda e instrumentos en el mismo orden.")
    alternative = next((a for a in result["alternatives"] if a.name == name), None)
    if alternative is None:
        raise PortfolioError("La alternativa elegida no pertenece al análisis calculado.")
    returns = result["model"].returns
    value = {
        "schema": 1,
        "name": name,
        "run_id": completed["run_id"],
        "analysis_key": expected,
        "code_sha256": version,
        "files_sha256": {k: sha256(v).hexdigest() for k, v in completed["files"].items()},
        "assets": list(assets),
        "weights": alternative.metrics.weights.tolist(),
        "currency": currency,
        "as_of": settings.as_of,
        "history_start": settings.history_start,
        "sample_start": returns.index[0].date().isoformat(),
        "sample_end": returns.index[-1].date().isoformat(),
    }
    return validate_strategy(value, assets, cutoff, currency, value["weights"])


def compare_plans(
    positions,
    cash,
    target,
    assumptions=None,
    *,
    fraction=0.25,
    quotes_confirmed=False,
    cash_floor=0.0,
    max_turnover=2.0,
    max_weight=1.0,
    minimum_trade=0.0,
    full_plan=None,
):
    """Interpolate target weights, then solve lots independently at the same dated prices."""
    assumptions = assumptions or ImplementationCostAssumptions()
    _validate_assumptions(assumptions)
    try:
        required = {"Instrumento", "Cantidad", "Precio", "Lote", "PesoObjetivo"}
        if (
            quotes_confirmed is not True
            or not required.issubset(positions)
            or set(positions) - required - {"Clase"}
            or not 0 < len(positions) <= 25
        ):
            raise ValueError
        p = positions.copy()
        if (
            not p["Instrumento"].map(lambda v: isinstance(v, str) and _text(v.lstrip())).all()
            or p["Instrumento"].duplicated().any()
        ):
            raise ValueError
        if "Clase" in p and not p["Clase"].map(lambda v: isinstance(v, str) and _text(v.lstrip())).all():
            raise ValueError
        quantity, price, lot = (p[k].to_numpy(dtype=float) for k in ("Cantidad", "Precio", "Lote"))
        target = np.asarray(target, dtype=float)
        params = np.r_[
            quantity, price, lot, target, cash, cash_floor, max_turnover, max_weight, minimum_trade, fraction
        ]
        if (
            not np.isfinite(params).all()
            or target.shape != quantity.shape
            or (quantity < 0).any()
            or (price <= 0).any()
            or (lot <= 0).any()
            or (target < 0).any()
            or target.sum() > 1 + 1e-8
            or cash < 0
            or cash_floor < 0
            or not 0 <= fraction <= 1
            or not 0 <= max_turnover <= 2
            or not 0 < max_weight <= 1
            or minimum_trade < 0
        ):
            raise ValueError
        nav = float(quantity @ price + cash)
        if nav <= 0:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise PortfolioError(
            "Confirma cotizaciones y revisa los insumos y límites de la comparación."
        ) from None
    current = quantity * price / nav
    reused = None
    if full_plan is not None:
        # Only a matching live proposal is reusable. Validation never solves.
        from operations_proposal import portable_proposal, proposal_positions

        payload = portable_proposal(full_plan)
        prior = payload["inputs"]
        rows = proposal_positions(prior)
        same_rows = [row["Instrumento"] for row in rows] == list(p["Instrumento"])
        for field in ("Cantidad", "Precio", "Lote"):
            same_rows = same_rows and np.allclose(
                [float(row[field]) for row in rows], p[field].to_numpy(dtype=float), atol=1e-9, rtol=0
            )
        if (
            not same_rows
            or not np.allclose(prior["target"], target, atol=1e-9, rtol=0)
            or prior["tariff"] != asdict(assumptions)
            or any(
                prior[k] != v
                for k, v in dict(
                    cash=cash,
                    cash_floor=cash_floor,
                    max_turnover=max_turnover,
                    max_weight=max_weight,
                    minimum_trade=minimum_trade,
                ).items()
            )
        ):
            raise PortfolioError("La propuesta previa no coincide con los insumos de la comparación.")
        reused = full_plan["result"]
    baseline = p.copy()
    baseline["PesoObjetivo"] = current
    baseline["Títulos a operar"] = 0.0
    baseline["Importe firmado"] = 0.0
    baseline["Comisión e IVA"] = 0.0
    baseline["Costo de mercado"] = 0.0
    baseline["Títulos finales"] = quantity
    baseline["Peso final sobre capital inicial"] = current
    reference = {
        "detail": baseline,
        "cash": float(cash),
        "cost": 0.0,
        "turnover": 0.0,
        "optimal": True,
        "basis": (
            "Referencia sin transacciones. Se conservan títulos y efectivo; no incluye mantenimiento futuro."
        ),
    }
    plans, rows = {"Conservar": reference}, []
    for name, weights in [
        ("Conservar", current),
        ("Cambio parcial", current + fraction * (target - current)),
        ("Propuesta", target),
    ]:
        reason = ""
        plan = reference if name == "Conservar" else reused if name == "Propuesta" else None
        if name != "Conservar" and plan is None:
            try:
                plan = executable_plan(
                    p,
                    cash,
                    weights,
                    assumptions,
                    cash_floor=cash_floor,
                    max_turnover=max_turnover,
                    max_weight=max_weight,
                    minimum_trade=minimum_trade,
                    quotes_confirmed=True,
                )
            except PortfolioError as error:
                reason = str(error)
        plans[name] = plan
        status = "Disponible" if plan else "No disponible"
        if name == "Conservar" and (cash < cash_floor or np.any(current > max_weight + 1e-8)):
            status, reason = (
                "Fuera de límites",
                "La referencia conserva una concentración o reserva que incumple los límites.",
            )
        detail = plan["detail"] if plan else None
        signed = detail["Importe firmado"] if plan else None
        rows.append(
            {
                "Alternativa": name,
                "Estado": status,
                "Compras": float(signed.clip(lower=0).sum()) if plan else None,
                "Ventas": float(-signed.clip(upper=0).sum()) if plan else None,
                "Órdenes": int(detail["Títulos a operar"].ne(0).sum()) if plan else None,
                "Costo": plan["cost"] if plan else None,
                "Efectivo": plan["cash"] if plan else None,
                "Rotación": plan["turnover"] if plan else None,
                "Motivo": reason,
            }
        )
    return {"plans": plans, "summary": pd.DataFrame(rows), "fraction": float(fraction)}


def plan_risk(plan, model):
    """Annual model exposure at final weights; cash is held constant, not renormalized away."""
    pending = {
        "status": "Pendiente",
        "annual_mean": None,
        "annual_volatility": None,
        "cash_weight": None,
        "coverage": None,
        "observations": None,
        "start": None,
        "end": None,
    }
    if plan is None or model is None:
        return pending
    frame = plan["detail"]
    assets = list(frame["Instrumento"])
    values = frame["Títulos finales"].to_numpy(dtype=float) * frame["Precio"].to_numpy(dtype=float)
    total = float(values.sum() + plan["cash"])
    if (
        total <= 0
        or not np.isfinite(values).all()
        or not np.isfinite(total)
        or (values < 0).any()
        or plan["cash"] < 0
    ):
        return pending
    pending["cash_weight"] = float(plan["cash"] / total)
    available = (
        set(model.moments.mean.index)
        & set(model.moments.covariance.index)
        & set(model.moments.covariance.columns)
        & set(model.returns)
    )
    covered = sum(v for a, v in zip(assets, values, strict=True) if a in available)
    pending["coverage"] = float(covered / values.sum()) if values.sum() else 1.0
    if not set(assets).issubset(available) or len(model.returns) < 2:
        return pending
    mean = model.moments.mean.loc[assets].to_numpy(dtype=float)
    covariance = model.moments.covariance.loc[assets, assets].to_numpy(dtype=float)
    if (
        not np.isfinite(mean).all()
        or not np.isfinite(covariance).all()
        or not np.allclose(covariance, covariance.T)
        or np.linalg.eigvalsh(covariance).min() < -1e-9
        or not np.isfinite(model.returns[assets].to_numpy(dtype=float)).all()
    ):
        return pending
    weights = values / total
    return {
        **pending,
        "status": "Modelo disponible",
        "annual_mean": float(weights @ mean),
        "annual_volatility": float(np.sqrt(max(0, weights @ covariance @ weights))),
        "observations": len(model.returns),
        "start": model.returns.index[0].date().isoformat(),
        "end": model.returns.index[-1].date().isoformat(),
    }
