"""Auditable fiscal cash-flow ledger for interest, dividends, and fund distributions."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError

MAX_TAX_CASH_FLOW_BYTES = 2_000_000
TAX_CASH_FLOW_COLUMNS = (
    "FechaPago",
    "Instrumento",
    "TipoFlujo",
    "ImporteBrutoMXN",
    "ISRRetenidoMXN",
    "ImpuestoExtranjeroRetenidoMXN",
    "TratamientoFiscal",
    "BaseRetencionMXN",
    "DiasPeriodo",
    "TasaControlPct",
    "TasaReservaAdicionalPct",
    "Fuente",
)

INTEREST = "INTERES"
MEXICAN_DIVIDEND = "DIVIDENDO_MEX"
FOREIGN_DIVIDEND_SIC = "DIVIDENDO_EXTRANJERO_SIC"
DEBT_FUND_DISTRIBUTION = "DISTRIBUCION_FONDO_DEUDA"
EQUITY_FUND_DISTRIBUTION = "DISTRIBUCION_FONDO_RV"
ALLOWED_FLOW_TYPES = {
    INTEREST,
    MEXICAN_DIVIDEND,
    FOREIGN_DIVIDEND_SIC,
    DEBT_FUND_DISTRIBUTION,
    EQUITY_FUND_DISTRIBUTION,
}

ARTICLE_140_DIVIDEND = "PF_DIVIDENDO_MEX_ART140"
LIF_2026_INTEREST = "PF_INTERES_LIF2026"
DOCUMENTED_WITHHOLDING = "RETENCION_DOCUMENTADA"
ADDITIONAL_RATE_SCENARIO = "ESCENARIO_TASA_ADICIONAL"
NOT_ESTIMATED = "NO_ESTIMADO"
ALLOWED_TREATMENTS = {
    ARTICLE_140_DIVIDEND,
    LIF_2026_INTEREST,
    DOCUMENTED_WITHHOLDING,
    ADDITIONAL_RATE_SCENARIO,
    NOT_ESTIMATED,
}


@dataclass(frozen=True)
class TaxCashFlowLedger:
    fiscal_year: int
    cutoff_date: pd.Timestamp
    detail: pd.DataFrame
    summary: pd.DataFrame
    gross_income: float
    domestic_withholding: float
    foreign_withholding: float
    expected_control_withholding: float
    additional_reserve: float
    unestimated_gross_income: float
    fingerprint: str


def _clean_text(value, field: str, maximum: int) -> str:
    text = str(value).strip()
    if (
        not text or text.lower() == "nan" or len(text) > maximum
        or text[0] in "=+-@"
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError(
            f"{field} debe tener entre 1 y {maximum} caracteres válidos y no ser una fórmula CSV."
        )
    return text


def _blank(value) -> bool:
    return bool(pd.isna(value) or str(value).strip() == "")


def _required_numbers(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.loc[:, columns].apply(pd.to_numeric, errors="coerce")
    if result.isna().any().any() or not np.isfinite(result.to_numpy(dtype=float)).all():
        raise PortfolioError("Los importes brutos y retenciones deben ser números finitos.")
    return result.astype(float)


def _optional_number(raw, field: str) -> float:
    if _blank(raw):
        return np.nan
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PortfolioError(f"{field} debe ser numérico o quedar vacío.") from exc
    if not np.isfinite(value):
        raise PortfolioError(f"{field} debe ser finito o quedar vacío.")
    return value


def read_tax_cash_flows_csv(
    contents: bytes,
    expected_assets: tuple[str, ...],
    cutoff_date: date | pd.Timestamp,
) -> TaxCashFlowLedger:
    """Read and classify fiscal cash flows without calculating annual income tax."""
    if not contents:
        raise PortfolioError("El archivo de flujos fiscales está vacío.")
    if len(contents) > MAX_TAX_CASH_FLOW_BYTES:
        raise PortfolioError("El archivo de flujos fiscales debe ocupar menos de 2 MB.")
    expected = tuple(str(asset).strip().upper() for asset in expected_assets)
    if not expected or len(set(expected)) != len(expected) or any(not item for item in expected):
        raise PortfolioError("El universo esperado para los flujos fiscales es inválido.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de flujos fiscales.") from exc
    if tuple(frame.columns) != TAX_CASH_FLOW_COLUMNS:
        raise PortfolioError(
            "El archivo de flujos fiscales debe contener exactamente las columnas de la plantilla "
            "y en el mismo orden."
        )
    if frame.empty:
        raise PortfolioError("El archivo de flujos fiscales no contiene movimientos.")

    raw_dates = frame["FechaPago"].str.strip()
    if not raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise PortfolioError("FechaPago debe usar YYYY-MM-DD.")
    dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise PortfolioError("FechaPago contiene una fecha inválida.")
    cutoff = pd.Timestamp(cutoff_date).normalize()
    if cutoff > pd.Timestamp.now().normalize():
        raise PortfolioError("La fecha de corte de los flujos fiscales no puede estar en el futuro.")
    if (dates.dt.normalize() > cutoff).any():
        raise PortfolioError("Ningún flujo fiscal puede ser posterior a la fecha de corte.")
    years = dates.dt.year.unique()
    if len(years) != 1:
        raise PortfolioError("El archivo de flujos fiscales debe cubrir un solo ejercicio fiscal.")
    fiscal_year = int(years[0])

    assets = frame["Instrumento"].str.strip().str.upper()
    if assets.eq("").any():
        raise PortfolioError("Instrumento no puede quedar vacío.")
    unexpected_assets = sorted(set(assets) - set(expected))
    if unexpected_assets:
        raise PortfolioError(
            "Los flujos fiscales contienen instrumentos fuera del análisis: "
            + ", ".join(unexpected_assets) + "."
        )

    flow_types = frame["TipoFlujo"].str.strip().str.upper()
    invalid_flow_types = sorted(set(flow_types) - ALLOWED_FLOW_TYPES)
    if invalid_flow_types:
        raise PortfolioError("TipoFlujo no reconocido: " + ", ".join(invalid_flow_types) + ".")
    treatments = frame["TratamientoFiscal"].str.strip().str.upper()
    invalid_treatments = sorted(set(treatments) - ALLOWED_TREATMENTS)
    if invalid_treatments:
        raise PortfolioError(
            "TratamientoFiscal de flujo no reconocido: " + ", ".join(invalid_treatments) + "."
        )

    required = _required_numbers(frame, (
        "ImporteBrutoMXN", "ISRRetenidoMXN", "ImpuestoExtranjeroRetenidoMXN",
    ))
    if (required["ImporteBrutoMXN"] <= 0).any():
        raise PortfolioError("ImporteBrutoMXN debe ser mayor que cero.")
    if (required[["ISRRetenidoMXN", "ImpuestoExtranjeroRetenidoMXN"]] < 0).any().any():
        raise PortfolioError("Las retenciones documentadas no pueden ser negativas.")
    total_withholding = required["ISRRetenidoMXN"] + required["ImpuestoExtranjeroRetenidoMXN"]
    if (total_withholding > required["ImporteBrutoMXN"] + 1e-8).any():
        raise PortfolioError("Las retenciones documentadas no pueden exceder el importe bruto.")

    sources = frame["Fuente"].map(lambda value: _clean_text(value, "Fuente", 300))
    details = []
    for row_number in range(len(frame)):
        flow_type = flow_types.iloc[row_number]
        treatment = treatments.iloc[row_number]
        gross = float(required.iloc[row_number]["ImporteBrutoMXN"])
        domestic = float(required.iloc[row_number]["ISRRetenidoMXN"])
        foreign = float(required.iloc[row_number]["ImpuestoExtranjeroRetenidoMXN"])
        base = _optional_number(frame.iloc[row_number]["BaseRetencionMXN"], "BaseRetencionMXN")
        days = _optional_number(frame.iloc[row_number]["DiasPeriodo"], "DiasPeriodo")
        control_rate_pct = _optional_number(
            frame.iloc[row_number]["TasaControlPct"], "TasaControlPct"
        )
        additional_rate_pct = _optional_number(
            frame.iloc[row_number]["TasaReservaAdicionalPct"], "TasaReservaAdicionalPct"
        )
        control_values = np.array([base, days, control_rate_pct], dtype=float)

        expected_control = np.nan
        additional_reserve = 0.0
        if treatment == ARTICLE_140_DIVIDEND:
            if flow_type != MEXICAN_DIVIDEND:
                raise PortfolioError("PF_DIVIDENDO_MEX_ART140 sólo admite DIVIDENDO_MEX.")
            if (
                not np.isfinite(base) or not np.isclose(base, gross, atol=0.01, rtol=0)
                or np.isfinite(days) or not np.isclose(control_rate_pct, 10.0, atol=1e-12, rtol=0)
                or np.isfinite(additional_rate_pct)
            ):
                raise PortfolioError(
                    "PF_DIVIDENDO_MEX_ART140 requiere base igual al importe bruto, tasa de control "
                    "10%, días vacíos y reserva adicional vacía."
                )
            expected_control = base * control_rate_pct / 100
        elif treatment == LIF_2026_INTEREST:
            if flow_type != INTEREST or fiscal_year != 2026:
                raise PortfolioError("PF_INTERES_LIF2026 sólo admite INTERES pagado en 2026.")
            if (
                not np.isfinite(base) or base <= 0 or not np.isfinite(days)
                or not float(days).is_integer() or not 1 <= days <= 366
                or not np.isclose(control_rate_pct, 0.90, atol=1e-12, rtol=0)
                or np.isfinite(additional_rate_pct)
            ):
                raise PortfolioError(
                    "PF_INTERES_LIF2026 requiere base positiva, 1 a 366 días enteros, tasa de "
                    "control 0.90% y reserva adicional vacía."
                )
            expected_control = base * control_rate_pct / 100 * days / 365
        elif treatment in {DOCUMENTED_WITHHOLDING, NOT_ESTIMATED}:
            if np.isfinite(control_values).any() or np.isfinite(additional_rate_pct):
                raise PortfolioError(
                    f"{treatment} requiere bases, días y tasas de escenario vacíos."
                )
            additional_reserve = np.nan if treatment == NOT_ESTIMATED else 0.0
        elif treatment == ADDITIONAL_RATE_SCENARIO:
            if np.isfinite(control_values).any():
                raise PortfolioError(
                    "ESCENARIO_TASA_ADICIONAL requiere base, días y tasa de control vacíos."
                )
            if (
                not np.isfinite(additional_rate_pct)
                or not 0 <= additional_rate_pct <= 100
            ):
                raise PortfolioError(
                    "TasaReservaAdicionalPct debe estar entre 0 y 100 para el escenario adicional."
                )
            additional_reserve = gross * additional_rate_pct / 100

        details.append({
            "Fecha de pago": dates.iloc[row_number].normalize(),
            "Instrumento": assets.iloc[row_number],
            "Tipo de flujo": flow_type,
            "Importe bruto": gross,
            "ISR retenido": domestic,
            "Impuesto extranjero retenido": foreign,
            "Neto documentado": gross - domestic - foreign,
            "Tratamiento fiscal": treatment,
            "Base de retención": base,
            "Días del periodo": days,
            "Tasa de control": control_rate_pct / 100,
            "Retención esperada de control": expected_control,
            "Diferencia contra control": (
                domestic - expected_control if np.isfinite(expected_control) else np.nan
            ),
            "Tasa de reserva adicional": additional_rate_pct / 100,
            "Reserva adicional": additional_reserve,
            "Fuente": sources.iloc[row_number],
        })

    detail = pd.DataFrame(details)
    summary = (
        detail.groupby("Tipo de flujo", sort=True, as_index=False)
        .agg({
            "Importe bruto": "sum",
            "ISR retenido": "sum",
            "Impuesto extranjero retenido": "sum",
            "Reserva adicional": lambda values: values.sum(skipna=True),
        })
    )
    return TaxCashFlowLedger(
        fiscal_year=fiscal_year,
        cutoff_date=cutoff,
        detail=detail,
        summary=summary,
        gross_income=float(detail["Importe bruto"].sum()),
        domestic_withholding=float(detail["ISR retenido"].sum()),
        foreign_withholding=float(detail["Impuesto extranjero retenido"].sum()),
        expected_control_withholding=float(
            detail["Retención esperada de control"].sum(skipna=True)
        ),
        additional_reserve=float(detail["Reserva adicional"].sum(skipna=True)),
        unestimated_gross_income=float(
            detail.loc[
                detail["Tratamiento fiscal"].eq(NOT_ESTIMATED), "Importe bruto"
            ].sum()
        ),
        fingerprint=sha256(contents).hexdigest(),
    )
