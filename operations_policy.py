"""Read-only, explicit policy checks; unknown criteria and evidence stay pending."""

import csv
import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import StringIO

from operations_cuts import cut_state
from portfolio_core import PortfolioError
from transaction_ledger import decimal

MAX_POLICY_BYTES = 100_000
FIELDS = {
    "schema",
    "scope",
    "base",
    "valid_from",
    "source",
    "basis",
    "targets",
    "tolerance",
    "max_weight",
    "min_cash",
    "reference",
}
ZERO = Decimal(0)


def _text(value, maximum):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError
    return value


def _ratio(value):
    if not isinstance(value, str):
        raise ValueError
    number = decimal(value)
    if not ZERO <= number <= 1:
        raise ValueError
    return number


def validate_policy(value):
    try:
        if (
            not isinstance(value, dict)
            or set(value) != FIELDS
            or type(value["schema"]) is not int
            or value["schema"] != 1
        ):
            raise ValueError
        if len(json.dumps(value, allow_nan=False, ensure_ascii=False).encode()) > MAX_POLICY_BYTES:
            raise ValueError
        scope = value["scope"]
        if not isinstance(scope, dict) or set(scope) != {"case_id", "account_id"}:
            raise ValueError
        if (scope["case_id"] is None) != (scope["account_id"] is None):
            raise ValueError
        for item in scope.values():
            if item is not None:
                _text(item, 160)
        day = date.fromisoformat(value["valid_from"])
        if (
            day.isoformat() != value["valid_from"]
            or day > date.today()
            or value["base"] not in {"MXN", "USD"}
        ):
            raise ValueError
        if value["basis"] not in {"net", "invested"}:
            raise ValueError
        _text(value["source"], 500)
        for name in ("tolerance", "max_weight", "min_cash"):
            if value[name] is not None:
                _ratio(value[name])
        targets = value["targets"]
        if not isinstance(targets, list) or len(targets) > 100:
            raise ValueError
        keys = set()
        total = ZERO
        for target in targets:
            if not isinstance(target, dict) or set(target) != {"instrument", "currency", "weight"}:
                raise ValueError
            key = (_text(target["instrument"], 160), target["currency"])
            if key in keys or key[1] not in {"MXN", "USD"}:
                raise ValueError
            keys.add(key)
            total += _ratio(target["weight"])
        if total > Decimal("1.000000000001"):
            raise ValueError
        reference = value["reference"]
        if reference is not None:
            from operations_comparison import validate_strategy

            if value["basis"] != "invested" or any(t["currency"] != value["base"] for t in targets):
                raise ValueError
            validate_strategy(
                reference,
                [t["instrument"] for t in targets],
                reference["as_of"],
                value["base"],
                [float(t["weight"]) for t in targets],
            )
        return deepcopy(value)
    except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError, PortfolioError):
        raise PortfolioError(
            "La política no es válida: revisa criterios, fuente, fechas, límites y cuenta."
        ) from None


def targets_from_csv(raw):
    try:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_POLICY_BYTES:
            raise ValueError
        reader = csv.DictReader(StringIO(raw.lstrip("\ufeff")))
        if reader.fieldnames != ["Instrumento", "Moneda", "PesoObjetivo"]:
            raise ValueError
        targets = []
        for row in reader:
            if set(row) != {"Instrumento", "Moneda", "PesoObjetivo"} or len(targets) >= 100:
                raise ValueError
            number = decimal(row["PesoObjetivo"]) / 100
            targets.append(
                {"instrument": row["Instrumento"], "currency": row["Moneda"], "weight": str(number)}
            )
        # Remaining structural/currency/duplicate/ratio checks are common with ZIP recovery.
        return targets
    except (ValueError, TypeError, KeyError, ArithmeticError, PortfolioError):
        raise PortfolioError("Revisa los pesos: Instrumento,Moneda,PesoObjetivo en porcentaje.") from None


def evaluate_policy(policy, contents, *, confirmed=False):
    policy = validate_policy(policy)
    state = cut_state(contents)
    cut = state["cut"]["payload"]
    if (
        policy["scope"] != {"case_id": cut["case_id"], "account_id": cut["account_id"]}
        or policy["base"] != cut["base"]
    ):
        raise PortfolioError("La política debe corresponder a la misma cuenta y moneda del corte.")
    if len(state["book"]["positions"]) > 500:
        raise PortfolioError(
            "La revisión de política admite hasta 500 posiciones; conserva el libro completo."
        )
    digest = sha256(
        json.dumps(policy, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    result = {
        "schema": 1,
        "cutoff": cut["cutoff"],
        "base": cut["base"],
        "scope": policy["scope"],
        "source": policy["source"],
        "valid_from": policy["valid_from"],
        "basis": policy["basis"],
        "policy_sha256": digest,
        "cut_sha256": state["cut"]["sha256"],
        "rows": [],
        "weights": [],
        "cash_available": None,
        "counts": {"within": 0, "deviations": 0, "pending": 0},
        "notice": "Avisos técnicos para revisión. No crean operaciones ni acreditan aprobación financiera.",
    }
    reason = None
    if confirmed is not True:
        reason = "Confirma de nuevo la política, cuenta y fuentes del corte."
    elif policy["valid_from"] > cut["cutoff"]:
        reason = "La política todavía no estaba vigente en la fecha del corte."
    elif policy["reference"] is not None and policy["reference"]["as_of"] > cut["cutoff"]:
        reason = "La referencia del análisis es posterior al corte; no se usa información futura."
    elif state["values"] is None:
        reason = "Falta una valuación completa del corte, incluidos precios, FX y reportos."
    values = state["values"] or {}
    nav = decimal(cut["valuation"]["nav"]) if cut["valuation"] else None
    invested = sum((v[2] for key, v in values.items() if key in state["book"]["positions"]), ZERO)
    denominator = nav if policy["basis"] == "net" else invested
    weights = {
        key: (
            values[key][2] / denominator
            if not reason and denominator is not None and denominator > 0
            else None
        )
        for key in state["book"]["positions"]
    }
    if not reason:
        result["weights"] = [
            {
                "instrument": key[0],
                "currency": key[1],
                "weight": str(w) if w is not None else None,
                "value_base": str(values[key][2]),
            }
            for key, w in sorted(weights.items())
        ]

    def add(id, kind, observed, limit, *, instrument="", currency=None, target=None, extra=None):
        why = reason or extra
        if limit is None:
            why = "Criterio sin definir en la política."
        elif observed is None and not why:
            why = "Falta un denominador positivo o datos suficientes para este criterio."
        delta = observed - target if observed is not None and target is not None else None
        # Preserve declared decimals and strict boundaries, including cent changes at large NAV.
        epsilon = ZERO
        exceeded = (
            (
                abs(delta) > limit + epsilon
                if kind == "drift" and delta is not None
                else observed < limit
                if kind == "cash"
                else observed > limit
            )
            if not why
            else None
        )
        label = "Pendiente" if why else "Desvío" if exceeded else "Dentro de límites"
        result["rows"].append(
            {
                "id": id,
                "kind": kind,
                "instrument": instrument,
                "currency": currency or cut["base"],
                "state": label,
                "observed": str(observed) if observed is not None and not reason else None,
                "limit": str(limit) if limit is not None else None,
                "target": str(target) if target is not None else None,
                "difference": str(delta) if delta is not None and not reason else None,
                "source": policy["source"],
                "reason": why
                or ("Fuera del criterio declarado." if exceeded else "Dentro del criterio declarado."),
                "action": "Revisar criterio y evidencia; no se ejecutan cambios.",
                "numeric_guard": str(epsilon),
            }
        )
        result["counts"]["pending" if why else "deviations" if exceeded else "within"] += 1

    targets = {(t["instrument"], t["currency"]): decimal(t["weight"]) for t in policy["targets"]}
    if not targets or policy["tolerance"] is None:
        add("drift", "drift", None, None)
    else:
        for key in sorted(set(targets) | set(weights)):
            target = targets.get(key)
            observed = weights.get(
                key, ZERO if not reason and denominator is not None and denominator > 0 else None
            )
            add(
                "drift:" + key[0] + ":" + key[1],
                "drift",
                observed,
                decimal(policy["tolerance"]),
                instrument=key[0],
                currency=key[1],
                target=target,
                extra="Falta el peso objetivo de este instrumento." if target is None else None,
            )
    available_weights = [(key, w) for key, w in weights.items() if w is not None]
    largest = max(available_weights, key=lambda row: row[1]) if available_weights else None
    maximum = largest[1] if largest else ZERO if not reason and denominator and denominator > 0 else None
    add(
        "concentration",
        "max_weight",
        maximum,
        decimal(policy["max_weight"]) if policy["max_weight"] is not None else None,
        instrument=largest[0][0] if largest else "",
    )
    cash_ratio = None
    if not reason and nav is not None and nav > 0:
        rates = {currency: row[1] for (_, currency), row in values.items()}
        settled = sum((amount * rates[currency] for currency, amount in state["book"]["cash"].items()), ZERO)
        payments = sum(
            (
                e.cash * rates[e.currency]
                for e in state["events"]
                if e.day.isoformat() <= cut["cutoff"] < e.settled.isoformat() and e.cash < 0
            ),
            ZERO,
        )
        result["cash_available"] = str(settled + payments)
        cash_ratio = (settled + payments) / nav
    add("cash", "cash", cash_ratio, decimal(policy["min_cash"]) if policy["min_cash"] is not None else None)
    return result
