"""Valuation and total-return preparation for Mexican government debt."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError


@dataclass(frozen=True)
class CetesTotalReturn:
    index: pd.Series
    prices: pd.Series
    days_to_maturity: pd.Series
    roll_dates: tuple[pd.Timestamp, ...]
    maturity_dates: tuple[pd.Timestamp, ...]

    @property
    def returns(self) -> pd.Series:
        return self.index.pct_change().dropna().rename(self.index.name)


@dataclass(frozen=True)
class BondTotalReturn:
    index: pd.Series
    clean_prices: pd.Series
    accrued_interest: pd.Series
    coupons: pd.Series
    issue_id: str
    maturity_date: pd.Timestamp

    @property
    def dirty_prices(self) -> pd.Series:
        return (self.clean_prices + self.accrued_interest).rename("Precio sucio")

    @property
    def returns(self) -> pd.Series:
        return self.index.pct_change().dropna().rename(self.index.name)


def cetes_price(
    annual_yield: float | np.ndarray | pd.Series,
    days_to_maturity: float | np.ndarray | pd.Series,
    nominal_value: float = 10.0,
):
    """Value a CETE from its annual simple yield on an actual/360 basis."""
    yields = np.asarray(annual_yield, dtype=float)
    days = np.asarray(days_to_maturity, dtype=float)
    if nominal_value <= 0 or not np.isfinite(nominal_value):
        raise PortfolioError("El valor nominal del CETE debe ser positivo.")
    if np.any(~np.isfinite(yields)) or np.any(yields <= -1):
        raise PortfolioError("La tasa del CETE debe ser finita y mayor que -100%.")
    if np.any(~np.isfinite(days)) or np.any(days < 0):
        raise PortfolioError("El plazo del CETE debe ser finito y no negativo.")
    denominator = 1 + yields * days / 360
    if np.any(denominator <= 0):
        raise PortfolioError("La combinación de tasa y plazo produce un precio inválido.")
    values = nominal_value / denominator
    if np.ndim(annual_yield) == 0 and np.ndim(days_to_maturity) == 0:
        return float(values)
    if isinstance(annual_yield, pd.Series):
        return pd.Series(values, index=annual_yield.index, name="Precio CETE")
    return values


def prepare_cetes_total_return(
    observations: pd.DataFrame,
    *,
    price_column: str,
    term_column: str,
    nominal_value: float = 10.0,
    name: str = "CETES",
) -> CetesTotalReturn:
    """Create an index from Banxico price/term observations.

    The same issue must lose exactly the calendar days elapsed. A reference
    switch is only modeled if the previous issue reached maturity: it redeems
    at nominal value. A switch before maturity has no observable sale price in
    an on-the-run price/term pair and must be rejected.
    """
    if price_column not in observations or term_column not in observations:
        raise PortfolioError("El archivo debe contener las columnas de precio y plazo indicadas.")
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise PortfolioError("El índice de observaciones debe contener fechas.")
    frame = observations[[price_column, term_column]].copy().sort_index()
    if frame.index.has_duplicates:
        raise PortfolioError("La serie CETES contiene fechas duplicadas.")
    frame.columns = ["price", "term"]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any():
        raise PortfolioError(
            "El archivo CETES contiene precio o plazo no numérico o faltante. "
            "Corrige las observaciones; no se eliminan filas silenciosamente."
        )
    if len(frame) < 3:
        raise PortfolioError("Se requieren al menos tres observaciones válidas de CETES.")
    if nominal_value <= 0 or not np.isfinite(nominal_value):
        raise PortfolioError("El valor nominal del CETE debe ser positivo.")
    if (frame["price"] <= 0).any():
        raise PortfolioError("Los precios de CETES deben ser positivos.")
    if (frame["price"] > nominal_value * 2).any():
        raise PortfolioError("El precio CETES excede el doble del valor nominal; revisa las unidades.")
    if (frame["term"] < 0).any() or not np.allclose(frame["term"], np.round(frame["term"])):
        raise PortfolioError("Los plazos de CETES deben ser días enteros no negativos.")

    elapsed = frame.index.to_series().diff().dt.days
    previous_term = frame["term"].shift(1)
    expected_term = previous_term - elapsed
    roll = frame["term"].ne(expected_term)
    roll.iloc[0] = False
    maturity = roll & previous_term.le(elapsed)
    early_switch = roll & ~maturity
    if early_switch.any():
        first = frame.index[early_switch][0].date().isoformat()
        raise PortfolioError(
            f"La emisión representativa de CETES cambió antes de vencer el {first}. "
            "Precio y plazo no identifican el precio de venta de la emisión anterior; "
            "se necesitan cotizaciones por emisión para calcular el retorno realizado."
        )

    gross = frame["price"].div(frame["price"].shift(1))
    gross.loc[maturity] = nominal_value / frame["price"].shift(1).loc[maturity]
    gross.iloc[0] = 1.0
    if (~np.isfinite(gross)).any() or (gross <= 0).any():
        raise PortfolioError("No fue posible construir factores válidos para la serie CETES.")

    total_return_index = (100.0 * gross.cumprod()).rename(name)
    return CetesTotalReturn(
        total_return_index,
        frame["price"].rename("Precio"),
        frame["term"].astype(int).rename("Plazo"),
        tuple(frame.index[roll]),
        tuple(frame.index[maturity]),
    )


def read_banxico_cetes_csv(
    contents: bytes,
    *,
    date_column: str,
    price_column: str,
    term_column: str,
    nominal_value: float = 10.0,
    name: str = "CETES",
) -> CetesTotalReturn:
    """Read a user-supplied Banxico export without requiring an API token."""
    if not contents:
        raise PortfolioError("El archivo CETES está vacío.")
    if len(contents) > 5_000_000:
        raise PortfolioError("El archivo CETES debe ocupar menos de 5 MB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de CETES.") from exc
    if date_column not in frame:
        raise PortfolioError("El archivo no contiene la columna de fecha indicada.")
    if price_column not in frame or term_column not in frame:
        raise PortfolioError("El archivo no contiene las columnas de precio y plazo indicadas.")
    raw_dates = frame.pop(date_column).astype(str).str.strip()
    iso = raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    spanish = raw_dates.str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    if not iso and not spanish:
        raise PortfolioError("Usa fechas únicas YYYY-MM-DD o DD/MM/YYYY en el archivo CETES.")
    dates = pd.to_datetime(
        raw_dates,
        format="%Y-%m-%d" if iso else "%d/%m/%Y",
        errors="coerce",
    )
    if dates.isna().any():
        raise PortfolioError("El archivo CETES contiene fechas inválidas.")
    frame.index = pd.DatetimeIndex(dates)
    if "Tasa" in frame:
        annual_yield = pd.to_numeric(frame["Tasa"], errors="coerce")
        if annual_yield.isna().any():
            raise PortfolioError("La columna Tasa CETES contiene observaciones inválidas.")
        term = pd.to_numeric(frame[term_column], errors="coerce")
        if term.isna().any():
            raise PortfolioError("El archivo CETES contiene plazos faltantes o inválidos.")
        implied = cetes_price(annual_yield / 100, term)
        reported = pd.to_numeric(frame[price_column], errors="coerce")
        if not np.isfinite(reported).all() or (abs(implied - reported) > 0.0001).any():
            raise PortfolioError(
                "Precio, plazo y tasa CETES no coinciden con la fórmula actual/360; "
                "revisa serie, unidades y fechas."
            )
    return prepare_cetes_total_return(
        frame,
        price_column=price_column,
        term_column=term_column,
        nominal_value=nominal_value,
        name=name,
    )


def prepare_bond_total_return(
    observations: pd.DataFrame,
    *,
    clean_price_column: str,
    accrued_interest_column: str,
    coupon_column: str,
    issue_id: str,
    maturity_date,
    nominal_value: float = 100.0,
    name: str = "BONO_M",
) -> BondTotalReturn:
    """Create a single-issue bond total-return index from dirty value and cash coupons.

    A coupon on date t is the cash received per nominal unit between the
    previous observation and the close on t. Therefore the gross factor is
    `(dirty_t + coupon_t) / dirty_(t-1)`.
    """
    required = [clean_price_column, accrued_interest_column, coupon_column]
    if any(column not in observations for column in required):
        raise PortfolioError(
            "El archivo del bono debe contener precio limpio, interés devengado y cupón."
        )
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise PortfolioError("El índice de observaciones del bono debe contener fechas.")
    if observations.index.isna().any() or observations.index.tz is not None:
        raise PortfolioError("Las fechas del bono deben ser válidas y no tener zona horaria.")
    frame = observations[required].copy().sort_index()
    if frame.index.has_duplicates:
        raise PortfolioError("La serie del bono contiene fechas duplicadas.")
    frame.columns = ["clean", "accrued", "coupon"]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any():
        raise PortfolioError(
            "El archivo del bono contiene valores no numéricos o faltantes; "
            "no se eliminan filas silenciosamente."
        )
    if len(frame) < 3:
        raise PortfolioError("Se requieren al menos tres observaciones válidas del bono.")
    if issue_id is None or pd.isna(issue_id):
        raise PortfolioError("La emisión del bono debe tener un identificador válido.")
    issue = str(issue_id).strip().upper()
    if not issue or len(issue) > 40 or any(ord(char) < 32 for char in issue):
        raise PortfolioError("La emisión del bono debe tener un identificador válido.")
    try:
        maturity = pd.Timestamp(maturity_date).normalize()
    except (TypeError, ValueError) as exc:
        raise PortfolioError("La fecha de vencimiento del bono es inválida.") from exc
    if pd.isna(maturity) or maturity.tz is not None or (frame.index.normalize() > maturity).any():
        raise PortfolioError("La serie del bono contiene fechas posteriores al vencimiento.")
    if not np.isfinite(nominal_value) or nominal_value <= 0:
        raise PortfolioError("El valor nominal del bono debe ser positivo.")
    if (frame["clean"] <= 0).any() or (frame["clean"] > nominal_value * 3).any():
        raise PortfolioError("Los precios limpios del bono tienen unidades o valores inválidos.")
    if (frame["accrued"] < 0).any() or (frame["accrued"] >= nominal_value).any():
        raise PortfolioError("El interés devengado del bono debe estar entre 0 y el valor nominal.")
    if (frame["coupon"] < 0).any() or (frame["coupon"] > nominal_value).any():
        raise PortfolioError("Los cupones del bono deben estar entre 0 y el valor nominal.")
    if not np.isclose(frame["coupon"].iloc[0], 0.0):
        raise PortfolioError("El cupón de la primera observación debe ser cero.")
    dirty = frame["clean"] + frame["accrued"]
    gross = (dirty + frame["coupon"]) / dirty.shift(1)
    gross.iloc[0] = 1.0
    if not np.isfinite(gross).all() or (gross <= 0).any():
        raise PortfolioError("No fue posible construir factores válidos para la serie del bono.")
    index = (100.0 * gross.cumprod()).rename(name)
    return BondTotalReturn(
        index=index,
        clean_prices=frame["clean"].rename("Precio limpio"),
        accrued_interest=frame["accrued"].rename("Interés devengado"),
        coupons=frame["coupon"].rename("Cupón"),
        issue_id=issue,
        maturity_date=maturity,
    )


def read_bond_total_return_csv(
    contents: bytes,
    *,
    date_column: str = "Fecha",
    issue_column: str = "Emision",
    maturity_column: str = "Vencimiento",
    clean_price_column: str = "PrecioLimpio",
    accrued_interest_column: str = "InteresDevengado",
    coupon_column: str = "Cupon",
    nominal_value: float = 100.0,
    name: str = "BONO_M",
) -> BondTotalReturn:
    """Read a reviewable CSV for one fixed-rate Mexican government bond issue."""
    if not contents:
        raise PortfolioError("El archivo del bono está vacío.")
    if len(contents) > 5_000_000:
        raise PortfolioError("El archivo del bono debe ocupar menos de 5 MB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV del bono.") from exc
    required = {
        date_column, issue_column, maturity_column, clean_price_column,
        accrued_interest_column, coupon_column,
    }
    if not required.issubset(frame.columns):
        raise PortfolioError("El archivo del bono no contiene todas las columnas requeridas.")
    raw_dates = frame.pop(date_column).astype(str).str.strip()
    iso = raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    spanish = raw_dates.str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    if not iso and not spanish:
        raise PortfolioError("Usa fechas únicas YYYY-MM-DD o DD/MM/YYYY en el archivo del bono.")
    dates = pd.to_datetime(
        raw_dates, format="%Y-%m-%d" if iso else "%d/%m/%Y", errors="coerce"
    )
    if dates.isna().any():
        raise PortfolioError("El archivo del bono contiene fechas inválidas.")
    raw_issues = frame.pop(issue_column)
    if raw_issues.isna().any():
        raise PortfolioError("El archivo debe contener una sola emisión de bono identificada.")
    issues = raw_issues.astype(str).str.strip().str.upper()
    if issues.eq("").any() or issues.nunique() != 1:
        raise PortfolioError("El archivo debe contener una sola emisión de bono identificada.")
    raw_maturities = frame.pop(maturity_column).astype(str).str.strip()
    maturities = pd.to_datetime(raw_maturities, format="%Y-%m-%d", errors="coerce")
    if maturities.isna().any() or maturities.nunique() != 1:
        raise PortfolioError(
            "El vencimiento debe usar YYYY-MM-DD y ser constante para toda la emisión."
        )
    frame.index = pd.DatetimeIndex(dates)
    return prepare_bond_total_return(
        frame,
        clean_price_column=clean_price_column,
        accrued_interest_column=accrued_interest_column,
        coupon_column=coupon_column,
        issue_id=issues.iloc[0],
        maturity_date=maturities.iloc[0],
        nominal_value=nominal_value,
        name=name,
    )


def merge_cetes_index(market_prices: pd.DataFrame, cetes_index: pd.Series) -> pd.DataFrame:
    """Align a prepared CETES index without hiding internal observation gaps."""
    return merge_prepared_index(market_prices, cetes_index, "CETES")


def merge_bond_index(market_prices: pd.DataFrame, bond_index: pd.Series) -> pd.DataFrame:
    """Align a prepared bond index without hiding internal observation gaps."""
    return merge_prepared_index(market_prices, bond_index, "bono")


def merge_prepared_index(
    market_prices: pd.DataFrame,
    fixed_income_index: pd.Series,
    series_kind: str,
) -> pd.DataFrame:
    """Align a prepared positive-value index to market dates without filling gaps."""
    if market_prices.empty or fixed_income_index.empty:
        raise PortfolioError(f"Las series de mercado y {series_kind} no pueden estar vacías.")
    if not isinstance(market_prices.index, pd.DatetimeIndex) or not isinstance(
        fixed_income_index.index, pd.DatetimeIndex
    ):
        raise PortfolioError(f"Las series de mercado y {series_kind} requieren fechas.")
    if (
        market_prices.index.has_duplicates
        or fixed_income_index.index.has_duplicates
        or not market_prices.index.is_monotonic_increasing
        or not fixed_income_index.index.is_monotonic_increasing
    ):
        raise PortfolioError("Las series mixtas requieren fechas únicas y ordenadas.")
    if fixed_income_index.name is None or not str(fixed_income_index.name).strip():
        raise PortfolioError(f"La serie de {series_kind} requiere un nombre.")
    if fixed_income_index.name in market_prices.columns:
        raise PortfolioError(
            f"El nombre de {series_kind} coincide con otro activo del análisis."
        )
    start = max(market_prices.index.min(), fixed_income_index.index.min())
    end = min(market_prices.index.max(), fixed_income_index.index.max())
    if start > end:
        raise PortfolioError(
            f"La serie de {series_kind} no coincide con el periodo de los demás activos."
        )
    market_window = market_prices.loc[start:end]
    missing = market_window.index.difference(fixed_income_index.index)
    if len(missing):
        raise PortfolioError(
            f"La serie de {series_kind} omite {len(missing)} fecha(s) de mercado "
            "dentro del periodo común. "
            "Corrige el archivo; no se rellenan huecos."
        )
    combined = market_window.join(
        fixed_income_index.rename(str(fixed_income_index.name)), how="left"
    )
    if len(combined) < 60:
        raise PortfolioError(
            f"Solo hay {len(combined)} observaciones mixtas; se requieren al menos 60."
        )
    if not np.isfinite(combined.to_numpy()).all() or (combined <= 0).any().any():
        raise PortfolioError("Las series mixtas deben contener valores positivos y finitos.")
    return combined
