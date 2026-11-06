"""Approved local-feed refresh and durable, deduplicated in-app alerts.

Sources are administrator-configured files, never arbitrary user URLs. A
failed refresh preserves the last good payload and marks its age explicitly.
"""

import base64
import json
import logging
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic

import numpy as np
import pandas as pd

from case_workspace import WorkspaceError
from portfolio_core import PortfolioError

LOGGER = logging.getLogger(__name__)


def monitor_drift(data, monitor):
    """Value last confirmed quantities with same-date unadjusted quotes."""
    if data.get("price_basis") != "raw":
        raise PortfolioError("El seguimiento por cantidades requiere cotizaciones sin ajuste.")
    frame = pd.read_csv(BytesIO(base64.b64decode(data["bytes"])), keep_default_na=False)
    quantity = pd.Series(monitor["quantities"], dtype=float)
    reference = pd.Series(monitor["weights"], dtype=float).reindex(quantity.index)
    if (
        quantity.empty
        or not np.isfinite(quantity).all()
        or (quantity <= 0).any()
        or reference.isna().any()
        or not np.isfinite(reference).all()
        or (reference < 0).any()
        or not np.isclose(reference.sum(), 1)
        or not 0 <= monitor["tolerance"] <= 1
    ):
        raise PortfolioError("Las cantidades y referencia de seguimiento requieren revisión.")
    selected = frame[frame["Instrumento"].isin(quantity.index) & frame["Moneda"].eq(monitor["currency"])]
    matrix = selected.pivot(index="Fecha", columns="Instrumento", values="Precio").reindex(
        columns=quantity.index
    )
    complete = matrix.dropna().sort_index()
    if complete.empty or str(complete.index[-1]) < monitor["as_of"]:
        raise PortfolioError("Falta un cierre común posterior a las cantidades confirmadas.")
    values = complete.iloc[-1].astype(float) * quantity
    drift = values / values.sum() - reference
    return {
        "max_abs_drift": float(drift.abs().max()),
        "quote_date": str(complete.index[-1]),
        "quantities_as_of": monitor["as_of"],
        "exceeded": bool(drift.abs().max() > monitor["tolerance"]),
    }


def read_approved_feed(source: dict, *, now: datetime):
    folder, path = Path(source["approved_folder"]), Path(source["path"])
    if not folder.is_absolute() or not path.is_absolute() or not path.is_relative_to(folder):
        raise PortfolioError("La fuente no está dentro de su carpeta aprobada.")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise PortfolioError("Una fuente aprobada no admite enlaces ni junctions.")
    if not path.resolve().is_relative_to(folder.resolve()) or not 0 < path.stat().st_size <= 2_000_000:
        raise PortfolioError("La fuente está vacía, excede 2 MB o está fuera de la carpeta aprobada.")
    if date.fromisoformat(source["rights_valid_until"]) < now.date():
        raise PortfolioError("Los derechos de uso de la fuente han vencido.")
    raw = path.read_bytes()
    frame = pd.read_csv(BytesIO(raw), keep_default_na=False)
    if frame.empty or len(frame) > 10000:
        raise PortfolioError("La fuente no tiene filas válidas dentro del límite.")
    kind = source["kind"]
    if kind == "catalogue":
        from instrument_catalogue import read_catalogue

        frame = read_catalogue(raw, cutoff=now.date())
    elif kind == "components":
        from portfolio_exposure import read_components

        frame = read_components(raw, tuple(frame["Fondo"].unique()), as_of=now.date())
    elif kind == "quotes":
        if (
            not {"Fecha", "Instrumento", "Precio", "Moneda"}.issubset(frame)
            or source.get("price_basis") not in {"raw", "adjusted"}
            or frame.duplicated(["Fecha", "Instrumento"]).any()
            or not set(frame["Moneda"]).issubset({"MXN", "USD"})
        ):
            raise PortfolioError("Cotizaciones inválidas o sin declaración de ajuste.")
        price = pd.to_numeric(frame["Precio"], errors="raise")
        if not np.isfinite(price).all() or (price <= 0).any():
            raise PortfolioError("Una cotización no es positiva y finita.")
    else:
        raise PortfolioError("Tipo de fuente no aprobado.")
    days = pd.to_datetime(frame["Fecha"], format="%Y-%m-%d", errors="raise").dt.date
    if (days > now.date()).any():
        raise PortfolioError("La fuente contiene fechas futuras.")
    # Conservative freshness: a single old instrument must remain visible.
    latest_per_asset = days.groupby(frame["Fondo"] if kind == "components" else frame["Instrumento"]).max()
    oldest = min(latest_per_asset)
    return {
        "sha256": sha256(raw).hexdigest(),
        "bytes": base64.b64encode(raw).decode(),
        "oldest_latest_date": oldest.isoformat(),
        "newest_date": max(days).isoformat(),
        "rows": len(frame),
        "price_basis": source.get("price_basis", "not_applicable"),
    }


def refresh_subscription(store, principal, case_id, account_id, record, sources, *, now=None, force=False):
    now = now or datetime.now(UTC)
    settings = dict(record["data"])
    if not settings.get("enabled") and not force:
        return None
    interval = int(settings.get("interval_minutes", 60))
    if not 15 <= interval <= 10080 or not 0 <= int(settings.get("max_age_days", 7)) <= 366:
        raise PortfolioError("La periodicidad o antigüedad de la revisión no es válida.")
    last = settings.get("last_attempt")
    if not force and last and (now - datetime.fromisoformat(last)).total_seconds() < interval * 60:
        return None
    source_id = settings.get("source_id")
    if source_id not in sources:
        raise PortfolioError("La suscripción no corresponde a una fuente aprobada vigente.")
    started = monotonic()
    cache_rows = store.working_records(principal, case_id, account_id, "feed")
    prior = next((row for row in cache_rows if row["name"] == source_id), None)
    data = dict(prior["data"]) if prior else {}
    code = "AVAILABLE"
    try:
        received = read_approved_feed(sources[source_id], now=now)
        data.update(received, received_at=now.isoformat())
    except (OSError, ValueError, KeyError, TypeError):
        code = "REFRESH_FAILED"
    data["last_attempt"] = now.isoformat()
    age = (now.date() - date.fromisoformat(data["oldest_latest_date"])).days if data.get("bytes") else None
    stale = age is None or age > int(settings.get("max_age_days", 7))
    data.update(status=code, stale=stale, age_days=age)
    condition = "NO_MONITOR"
    if settings.get("monitor"):
        try:
            drift = monitor_drift(data, settings["monitor"])
            data["drift"] = drift
            condition = "DRIFT_EXCEEDED" if drift["exceeded"] else "DRIFT_WITHIN_LIMIT"
        except (PortfolioError, ValueError, KeyError, TypeError):
            condition = "MONITOR_PENDING"
    data["monitor_state"] = condition
    store.save_working(
        principal,
        case_id,
        account_id,
        "feed",
        source_id,
        data,
        expected_version=prior["version"] if prior else 0,
    )
    # Identical failure/staleness state creates one alert, not one per scheduled run.
    signature = sha256(
        json.dumps(
            [code, stale, condition, data.get("sha256") if settings.get("notify_updates") else None]
        ).encode()
    ).hexdigest()
    if settings.get("last_signature") != signature:
        alerts = store.working_records(principal, case_id, account_id, "alert")
        existing = next((row for row in alerts if row["name"] == source_id), None)
        alert = {
            "source_id": source_id,
            "code": code,
            "stale": stale,
            "at": now.isoformat(),
            "signature": signature,
            "read": False,
            "message": "Revisa la fuente: no disponible o antigua."
            if code != "AVAILABLE" or stale
            else "La fuente vuelve a estar disponible y dentro de antigüedad.",
        }
        # Do not notify a first successful healthy poll unless new-data alerts were selected.
        if condition == "DRIFT_EXCEEDED":
            alert["message"] = "El desvío supera la tolerancia de la referencia confirmada."
        elif condition == "MONITOR_PENDING":
            alert["message"] = "El seguimiento requiere cantidades, referencia o cotizaciones compatibles."
        if (
            code != "AVAILABLE"
            or stale
            or existing
            or settings.get("notify_updates")
            or condition in {"DRIFT_EXCEEDED", "MONITOR_PENDING"}
        ):
            store.save_working(
                principal,
                case_id,
                account_id,
                "alert",
                source_id,
                alert,
                expected_version=existing["version"] if existing else 0,
            )
    settings.update(last_attempt=now.isoformat(), last_signature=signature)
    store.save_working(
        principal,
        case_id,
        account_id,
        "subscription",
        record["name"],
        settings,
        expected_version=record["version"],
    )
    LOGGER.info(
        "operations_stage=feed_refresh result=%s duration_ms=%d", code, (monotonic() - started) * 1000
    )
    return {key: data[key] for key in ("status", "stale", "age_days", "last_attempt")}


def scheduler_tick(store, principals, sources):
    """Only currently configured identities and current case memberships may run jobs."""
    for principal in principals:
        if principal.role not in {"ADMIN", "ANALYST"}:
            continue
        try:
            cases = store.list_cases(principal)
        except WorkspaceError:
            continue
        for case in cases:
            if case["archived"]:
                continue
            state = store.read(principal, case["id"])
            for account in state["accounts"]:
                for record in store.working_records(principal, case["id"], account["id"], "subscription"):
                    try:
                        refresh_subscription(store, principal, case["id"], account["id"], record, sources)
                    except (WorkspaceError, PortfolioError):
                        LOGGER.warning("operations_stage=feed_refresh result=REVIEW_REQUIRED")
