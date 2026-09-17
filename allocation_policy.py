"""Strict parsing and presentation of declared asset-class allocation policies."""

from __future__ import annotations

import re

import pandas as pd

from portfolio_core import AllocationGroup, PortfolioError

CLASS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def parse_asset_classes(raw: str, asset_count: int) -> tuple[str, ...]:
    """Parse one normalized class identifier per user-supplied asset."""
    values = tuple(part.strip().lower() for part in raw.split(","))
    if len(values) != asset_count:
        raise PortfolioError(
            f"Ingresa exactamente {asset_count} clases, en el mismo orden que los activos."
        )
    invalid = [value for value in values if not CLASS_PATTERN.fullmatch(value)]
    if invalid:
        raise PortfolioError(
            "Las clases usan minúsculas, números y guion bajo; revisa: "
            + ", ".join(dict.fromkeys(invalid))
        )
    return values


def parse_class_limits(raw: str, asset_classes: tuple[str, ...]) -> tuple[AllocationGroup, ...]:
    """Parse `clase,mínimo %,máximo %` rows for a complete class partition."""
    expected = set(asset_classes)
    rows: dict[str, tuple[float, float]] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip().lower() for part in line.split(",")]
        if len(parts) != 3:
            raise PortfolioError(
                f"La línea {line_number} debe tener clase, mínimo % y máximo %."
            )
        name = parts[0]
        if not CLASS_PATTERN.fullmatch(name):
            raise PortfolioError(f"La clase de la línea {line_number} tiene formato inválido.")
        if name in rows:
            raise PortfolioError(f"La clase {name} aparece más de una vez.")
        try:
            minimum, maximum = float(parts[1]) / 100, float(parts[2]) / 100
        except ValueError as exc:
            raise PortfolioError(
                f"Los límites de la línea {line_number} deben ser porcentajes numéricos."
            ) from exc
        rows[name] = (minimum, maximum)
    missing, extra = expected - rows.keys(), rows.keys() - expected
    if missing:
        raise PortfolioError("Faltan límites para: " + ", ".join(sorted(missing)))
    if extra:
        raise PortfolioError("Hay límites para clases no utilizadas: " + ", ".join(sorted(extra)))
    return tuple(
        AllocationGroup(
            name,
            tuple(index for index, value in enumerate(asset_classes) if value == name),
            *rows[name],
        )
        for name in sorted(expected)
    )


def policy_table(groups: tuple[AllocationGroup, ...]) -> pd.DataFrame:
    """Return a concise, report-ready table."""
    return pd.DataFrame({
        "Clase": [group.name for group in groups],
        "Mínimo": [group.minimum for group in groups],
        "Máximo": [group.maximum for group in groups],
        "Activos": [len(group.asset_indices) for group in groups],
    })
