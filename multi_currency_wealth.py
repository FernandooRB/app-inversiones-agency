"""Same-cut multi-account wealth in MXN/USD and conservative internal-flow matching."""

from datetime import date

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError


def consolidate_wealth(
    positions: pd.DataFrame, fx: pd.DataFrame, *, cutoff: date, base="MXN", allowed_accounts=None
):
    required = {"Fecha", "Cuenta", "Instrumento", "Moneda", "Valor", "EmisorID"}
    if base not in {"MXN", "USD"} or not required.issubset(positions) or positions.empty:
        raise PortfolioError(
            "El patrimonio requiere fecha, cuenta, instrumento, moneda, valor e identidad de emisor."
        )
    frame = positions.copy()
    try:
        days = pd.to_datetime(frame["Fecha"], format="%Y-%m-%d", errors="raise").dt.date
        frame["Valor"] = pd.to_numeric(frame["Valor"], errors="raise")
        if (
            (days != cutoff).any()
            or not np.isfinite(frame["Valor"]).all()
            or not set(frame["Moneda"]).issubset({"MXN", "USD"})
            or frame.duplicated(["Cuenta", "Instrumento", "Moneda"]).any()
            or frame["Cuenta"].astype(str).str.strip().eq("").any()
            or (allowed_accounts is not None and not set(frame["Cuenta"]).issubset(allowed_accounts))
        ):
            raise ValueError
        rates = {}
        if not fx.empty:
            if not {"Fecha", "Moneda", "Base", "Tasa", "Fuente"}.issubset(fx):
                raise ValueError
            for row in fx.to_dict("records"):
                key = row["Moneda"], row["Base"]
                if (
                    key in rates
                    or date.fromisoformat(str(row["Fecha"])) != cutoff
                    or not str(row["Fuente"]).strip()
                    or not np.isfinite(float(row["Tasa"]))
                    or float(row["Tasa"]) <= 0
                    or key[0] not in {"MXN", "USD"}
                    or key[1] not in {"MXN", "USD"}
                ):
                    raise ValueError
                rates[key] = float(row["Tasa"])
        frame["FX"] = [1.0 if currency == base else rates[(currency, base)] for currency in frame["Moneda"]]
        frame["ValorBase"] = frame["Valor"] * frame["FX"]
    except (ValueError, TypeError, KeyError) as exc:
        raise PortfolioError(
            "No se pueden mezclar cortes, cuentas ajenas, filas duplicadas o FX sin fuente del corte."
        ) from exc
    nav = float(frame["ValorBase"].sum())
    if nav <= 0:
        raise PortfolioError("El patrimonio neto consolidado debe ser positivo.")
    frame["Peso"] = frame["ValorBase"] / nav
    known = frame["EmisorID"].fillna("").astype(str).str.strip().ne("")
    frame["EmisorID"] = frame["EmisorID"].where(known, "Sin cobertura")
    return {
        "nav": nav,
        "base": base,
        "detail": frame,
        "accounts": frame.groupby("Cuenta")["ValorBase"].sum(),
        "currencies": frame.groupby("Moneda")["ValorBase"].sum(),
        "issuers": frame.groupby("EmisorID")["Peso"].sum().sort_values(ascending=False),
        "identity_coverage": float(
            frame.loc[known, "ValorBase"].abs().sum() / frame["ValorBase"].abs().sum()
        ),
    }


def match_internal_flows(legs: pd.DataFrame):
    """Match two opposite legs by reference, currency, date and exact cents.

    Wealth NAV is never reduced by a transfer. Only matched flow legs are
    excluded from external-flow performance; unmatched legs require review.
    Cross-currency conversions require their own explicit FX records.
    """
    required = {"Fecha", "Cuenta", "Tipo", "Moneda", "Importe", "Referencia"}
    if not required.issubset(legs):
        raise PortfolioError(
            "Las transferencias necesitan fecha, cuenta, tipo, moneda, importe y referencia."
        )
    from transaction_ledger import decimal

    frame = legs.copy()
    try:
        frame["Fecha"] = pd.to_datetime(frame["Fecha"], format="%Y-%m-%d", errors="raise").dt.date
        frame["Importe"] = frame["Importe"].map(decimal)
        if (
            (frame["Importe"] <= 0).any()
            or frame["Referencia"].astype(str).str.strip().eq("").any()
            or not set(frame["Tipo"]).issubset({"TRANSFER_IN", "TRANSFER_OUT"})
            or not set(frame["Moneda"]).issubset({"MXN", "USD"})
        ):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise PortfolioError("Una transferencia tiene importe, referencia, tipo o fecha inválidos.") from exc
    frame["Estado"] = "SIN_PAREJA_VERIFICADA"
    for _, group in frame.groupby(["Fecha", "Moneda", "Referencia"], dropna=False):
        if (
            len(group) == 2
            and group["Cuenta"].nunique() == 2
            and set(group["Tipo"]) == {"TRANSFER_IN", "TRANSFER_OUT"}
            and group["Importe"].nunique() == 1
        ):
            frame.loc[group.index, "Estado"] = "INTERNA_VERIFICADA"
    return frame


def consolidated_performance(valuations, fx, flows, *, base="MXN", allowed_accounts=None):
    """Align account closes, convert each date and remove only verified internal legs.

    Flow FXBase is the explicitly confirmed base-currency rate at that flow's
    moment, distinct from closing valuation FX. No forward filling is applied.
    """
    from realized_performance import Flow, performance

    required = {"Fecha", "Cuenta", "Moneda", "NAV"}
    if not required.issubset(valuations) or valuations.empty:
        raise PortfolioError("El rendimiento consolidado requiere cierres por fecha, cuenta y moneda.")
    if valuations.duplicated(["Fecha", "Cuenta"]).any():
        raise PortfolioError("Una cuenta tiene cierres duplicados en la misma fecha.")
    accounts = set(valuations["Cuenta"])
    if allowed_accounts is not None and not accounts.issubset(allowed_accounts):
        raise PortfolioError("Las valuaciones incluyen cuentas ajenas al expediente.")
    totals = {}
    for day, group in valuations.groupby("Fecha"):
        if set(group["Cuenta"]) != accounts:
            raise PortfolioError(
                "Todas las cuentas deben tener valuación en cada cierre del calendario común."
            )
        wealth = group.rename(columns={"NAV": "Valor"}).assign(Instrumento="NAV", EmisorID="")
        selected_fx = fx[fx["Fecha"].eq(day)] if not fx.empty and "Fecha" in fx else pd.DataFrame()
        totals[day] = consolidate_wealth(
            wealth, selected_fx, cutoff=date.fromisoformat(str(day)), base=base, allowed_accounts=accounts
        )["nav"]
    external, matched = [], pd.DataFrame()
    if not flows.empty:
        required_flow = {
            "Fecha",
            "Cuenta",
            "Tipo",
            "Moneda",
            "Importe",
            "Referencia",
            "MomentoFlujo",
            "FXBase",
            "FuenteFX",
        }
        if not required_flow.issubset(flows) or not set(flows["Cuenta"]).issubset(accounts):
            raise PortfolioError("Los flujos requieren cuenta, tipo, importe, momento y FX explícito.")
        if not set(flows["Tipo"]).issubset({"DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT"}):
            raise PortfolioError("Incluye sólo aportaciones, retiros y patas de transferencias en flujos.")
        transfer = flows[flows["Tipo"].str.startswith("TRANSFER_")]
        if not transfer.empty:
            matched = match_internal_flows(transfer)
            if not matched["Estado"].eq("INTERNA_VERIFICADA").all():
                raise PortfolioError(
                    "Una transferencia no tiene pareja verificada; clasifícala antes de calcular."
                )
        for row in flows[~flows["Tipo"].str.startswith("TRANSFER_")].to_dict("records"):
            amount, rate = float(row["Importe"]), float(row["FXBase"])
            if (
                row["Moneda"] not in {"MXN", "USD"}
                or not np.isfinite([amount, rate]).all()
                or amount <= 0
                or rate <= 0
                or (row["Moneda"] == base and rate != 1)
                or (row["Moneda"] != base and not str(row["FuenteFX"]).strip())
            ):
                raise PortfolioError(
                    "Los flujos necesitan importes positivos y FX compatible con la moneda base."
                )
            signed = amount * rate * (1 if row["Tipo"] == "DEPOSIT" else -1)
            external.append(Flow(date.fromisoformat(str(row["Fecha"])), signed, row["MomentoFlujo"]))
    nav = pd.Series(totals).sort_index()
    return {
        "performance": performance(nav, external),
        "valuations": nav,
        "internal_transfers": matched,
        "external_flows": external,
        "base": base,
    }
