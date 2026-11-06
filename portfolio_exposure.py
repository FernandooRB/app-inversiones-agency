"""Dated, partial look-through with explicit unknown weights, never invented constituents."""

from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd

from currencies import SUPPORTED
from portfolio_core import PortfolioError, validate_weights

COMPONENT_COLUMNS = ("Fondo", "Componente", "Peso", "Emisor", "Sector", "Pais", "Moneda", "Fecha", "Fuente")
ASSET_KINDS = ("Sin clasificar", "Acción", "ETF/Fondo", "Deuda", "Liquidez")
UNKNOWN = "Sin cobertura"


def validate_metadata(metadata, assets, as_of=None):
    if not isinstance(metadata, dict) or not set(metadata).issubset(set(assets)):
        raise PortfolioError("La clasificación debe corresponder a los instrumentos de la cartera.")
    fields = {"Tipo", "Emisor", "EmisorID", "Sector", "Pais", "Moneda", "Fuente", "Fecha"}
    for value in metadata.values():
        if not isinstance(value, dict) or not set(value).issubset(fields):
            raise PortfolioError("La clasificación del instrumento no tiene el formato esperado.")
        if any(
            not isinstance(item, str) or len(item) > 200 or any(ord(c) < 32 for c in item)
            for item in value.values()
        ):
            raise PortfolioError("La clasificación necesita texto válido y acotado.")
        if value.get("Moneda", "") not in SUPPORTED | {""}:
            raise PortfolioError("La moneda económica de la clasificación no está soportada.")
        if value.get("Fecha"):
            try:
                if date.fromisoformat(value["Fecha"]) > (as_of or date.today()):
                    raise ValueError
            except ValueError:
                raise PortfolioError("La fecha de clasificación es inválida o posterior al corte.") from None


def _text(value):
    return (
        isinstance(value, str)
        and 0 < len(value.strip()) <= 200
        and value[0] not in "=+-@"
        and all(ord(c) >= 32 for c in value)
    )


def read_components(contents, assets, *, as_of=None):
    if not contents or len(contents) > 2_000_000:
        raise PortfolioError("Los componentes deben ser un CSV de hasta 2 MB.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
        extended = (*COMPONENT_COLUMNS, "EmisorID")
        if tuple(frame.columns) not in {COMPONENT_COLUMNS, extended} or frame.empty or len(frame) > 10000:
            raise ValueError
        frame = frame.map(lambda value: value.strip())
        if not all(frame[column].map(_text).all() for column in COMPONENT_COLUMNS if column != "Peso"):
            raise ValueError
        if "EmisorID" in frame and not frame["EmisorID"].map(_text).all():
            raise ValueError
        frame["Peso"] = pd.to_numeric(frame["Peso"], errors="raise")
        if (
            not np.isfinite(frame["Peso"]).all()
            or (frame["Peso"] <= 0).any()
            or (frame["Peso"] > 1).any()
            or frame.duplicated(["Fondo", "Componente"]).any()
            or not set(frame["Fondo"]).issubset(set(assets))
        ):
            raise ValueError
        if (frame.groupby("Fondo")["Peso"].sum() > 1 + 1e-10).any():
            raise ValueError
        if not frame["Fecha"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            raise ValueError
        dates = pd.to_datetime(frame["Fecha"], format="%Y-%m-%d", errors="raise")
        cutoff = as_of or date.today()
        if (dates.dt.date > cutoff).any() or (frame.groupby("Fondo")["Fecha"].nunique() > 1).any():
            raise ValueError
        if not set(frame["Moneda"]).issubset(SUPPORTED):
            raise ValueError
        return frame
    except (ValueError, TypeError, UnicodeError, pd.errors.ParserError):
        raise PortfolioError(
            "Componentes inválidos: pesos entre 0 y 1, suma por fondo ≤ 1, una fecha por fondo "
            "no posterior al corte, componentes únicos y fuente para cada fila."
        ) from None


def analyze_exposure(assets, weights, metadata, components=None, *, as_of=None):
    validate_metadata(metadata, assets, as_of)
    weights = validate_weights(weights, len(assets))
    rows = []
    for asset, weight in zip(assets, weights, strict=True):
        meta = metadata.get(asset, {})
        kind = meta.get("Tipo", "Sin clasificar")
        if kind not in ASSET_KINDS:
            raise PortfolioError("La clasificación del instrumento no es reconocida.")
        sub = components.loc[components["Fondo"] == asset] if components is not None else None
        if sub is not None and not sub.empty:
            if kind != "ETF/Fondo":
                raise PortfolioError("Confirma ETF/Fondo para los instrumentos con componentes aportados.")
            if as_of and (pd.to_datetime(sub["Fecha"]).dt.date > as_of).any():
                raise PortfolioError("Los componentes son posteriores al corte de la cartera.")
            for item in sub.to_dict(orient="records"):
                rows.append(
                    {
                        "Instrumento": asset,
                        "Componente": item["Componente"],
                        "Peso": float(weight * item["Peso"]),
                        "Emisor": item["Emisor"],
                        "EmisorID": item.get("EmisorID", ""),
                        "Sector": item["Sector"],
                        "Pais": item["Pais"],
                        "Moneda": item["Moneda"],
                        "Fecha": item["Fecha"],
                        "Fuente": item["Fuente"],
                        "Cubierto": True,
                    }
                )
            missing = max(0.0, 1 - sub["Peso"].sum())
        elif kind not in {"Sin clasificar", "ETF/Fondo"} and all(
            _text(meta.get(field, "")) for field in ("Emisor", "Sector", "Pais", "Moneda", "Fuente")
        ):
            rows.append(
                {
                    "Instrumento": asset,
                    "Componente": asset,
                    "Peso": float(weight),
                    **{key: meta[key] for key in ("Emisor", "Sector", "Pais", "Moneda", "Fuente")},
                    "Fecha": meta.get("Fecha", "Declarada"),
                    "EmisorID": meta.get("EmisorID", ""),
                    "Cubierto": True,
                }
            )
            missing = 0
        else:
            missing = 1
        if missing * weight > 1e-12:
            rows.append(
                {
                    "Instrumento": asset,
                    "Componente": UNKNOWN,
                    "Peso": float(weight * missing),
                    **dict.fromkeys(("Emisor", "Sector", "Pais", "Moneda"), UNKNOWN),
                    "Fecha": "",
                    "Fuente": "No aportada",
                    "Cubierto": False,
                    "EmisorID": "",
                }
            )
    detail = pd.DataFrame(rows)
    aggregates = {
        field: detail.groupby(field, sort=True)["Peso"].sum().sort_values(ascending=False)
        for field in ("Emisor", "Sector", "Pais", "Moneda")
    }
    # Preserve display names while grouping verified catalogue IDs across aliases.
    detail["ClaveEmisor"] = ("ID: " + detail["EmisorID"]).where(detail["EmisorID"].ne(""), detail["Emisor"])
    aggregates["Emisor"] = detail.groupby("ClaveEmisor")["Peso"].sum().sort_values(ascending=False)
    dated = pd.to_datetime(detail["Fecha"], errors="coerce")
    detail["AntiguedadDias"] = ((pd.Timestamp(as_of or date.today()) - dated).dt.days).astype("Int64")
    known = detail[detail["Cubierto"]]
    counts = known.groupby("ClaveEmisor")["Instrumento"].nunique()
    overlap = (
        known[known["ClaveEmisor"].isin(counts[counts > 1].index)]
        .groupby("ClaveEmisor")
        .agg(Peso=("Peso", "sum"), Vehiculos=("Instrumento", "nunique"))
    )
    return {
        "detail": detail,
        "coverage": float(known["Peso"].sum()),
        "identity_coverage": float(known.loc[known["EmisorID"].ne(""), "Peso"].sum()),
        "fresh_coverage_90_days": float(
            known.loc[known["AntiguedadDias"].le(90).fillna(False), "Peso"].sum()
        ),
        "aggregates": aggregates,
        "overlap": overlap,
    }
