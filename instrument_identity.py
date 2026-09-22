"""Strict, non-identifying security metadata for the quoted-price universe."""

import re
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO

import pandas as pd

from currencies import SUPPORTED
from portfolio_core import PortfolioError

MAX_IDENTITY_CSV_BYTES = 100_000
IDENTITY_COLUMNS = (
    "Instrumento",
    "ISIN",
    "MercadoNegociacion",
    "SimboloNegociacion",
    "MercadoSerie",
    "MonedaSerie",
    "TipoSerie",
    "FechaVerificacion",
    "Fuente",
)
TRADE_MARKETS = {"BMV", "BIVA", "SIC"}
SERIES_MARKETS = TRADE_MARKETS | {"ORIGEN_EXTRANJERO"}
LOCAL_SERIES = "CIERRE_LOCAL_AJUSTADO"
FOREIGN_PROXY = "PROXY_ORIGEN_AJUSTADO"
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.*-]{0,29}$")
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class InstrumentIdentityProfile:
    detail: pd.DataFrame
    proxy_assets: tuple[str, ...]
    fingerprint: str


def valid_isin(value: str) -> bool:
    """Check ISO 6166 format and modulus-10 check digit; not registry authenticity."""
    if not ISIN_PATTERN.fullmatch(value):
        return False
    digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = 0
    for position, character in enumerate(reversed(digits)):
        number = int(character)
        if position % 2 == 1:
            number *= 2
            number = number // 10 + number % 10
        total += number
    return total % 10 == 0


def _clean_source(value: str) -> str:
    text = value.strip()
    if (
        not text or len(text) > 300 or text[0] in "=+-@"
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError("Fuente debe ser texto válido, no una fórmula CSV.")
    return text


def read_instrument_identity_csv(
    contents: bytes,
    expected_assets: tuple[str, ...],
    declared_quotes: dict[str, str],
) -> InstrumentIdentityProfile:
    """Validate instrument identity and whether a price series is local or a proxy."""
    if not contents:
        raise PortfolioError("El manifiesto de instrumentos está vacío.")
    if len(contents) > MAX_IDENTITY_CSV_BYTES:
        raise PortfolioError("El manifiesto de instrumentos debe ocupar menos de 100 KB.")
    expected = tuple(str(asset).strip().upper() for asset in expected_assets)
    if not expected or len(set(expected)) != len(expected) or any(not item for item in expected):
        raise PortfolioError("El universo esperado de instrumentos es inválido.")
    if set(declared_quotes) != set(expected) or any(
        declared_quotes[asset] not in SUPPORTED for asset in expected
    ):
        raise PortfolioError("Las monedas declaradas deben cubrir exactamente los instrumentos.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el manifiesto de instrumentos.") from exc
    if tuple(frame.columns) != IDENTITY_COLUMNS:
        raise PortfolioError("El manifiesto debe usar exactamente las columnas de la plantilla.")
    if frame.empty:
        raise PortfolioError("El manifiesto de instrumentos no contiene filas.")

    frame = frame.map(lambda value: value.strip())
    frame["Instrumento"] = frame["Instrumento"].str.upper()
    frame["ISIN"] = frame["ISIN"].str.upper()
    frame["MercadoNegociacion"] = frame["MercadoNegociacion"].str.upper()
    frame["SimboloNegociacion"] = frame["SimboloNegociacion"].str.upper()
    frame["MercadoSerie"] = frame["MercadoSerie"].str.upper()
    frame["MonedaSerie"] = frame["MonedaSerie"].str.upper()
    frame["TipoSerie"] = frame["TipoSerie"].str.upper()
    if frame["Instrumento"].duplicated().any() or set(frame["Instrumento"]) != set(expected):
        raise PortfolioError("El manifiesto debe contener cada instrumento esperado una sola vez.")
    if frame["ISIN"].duplicated().any() or not frame["ISIN"].map(valid_isin).all():
        raise PortfolioError("Cada instrumento requiere un ISIN válido y único.")
    if not frame["SimboloNegociacion"].map(
        lambda value: bool(SYMBOL_PATTERN.fullmatch(value))
    ).all():
        raise PortfolioError("SimboloNegociacion contiene una clave inválida.")
    if not set(frame["MercadoNegociacion"]).issubset(TRADE_MARKETS):
        raise PortfolioError("MercadoNegociacion debe ser BMV, BIVA o SIC.")
    if not set(frame["MercadoSerie"]).issubset(SERIES_MARKETS):
        raise PortfolioError("MercadoSerie no reconocido.")
    if not set(frame["TipoSerie"]).issubset({LOCAL_SERIES, FOREIGN_PROXY}):
        raise PortfolioError("TipoSerie no reconocido.")
    if not set(frame["MonedaSerie"]).issubset(SUPPORTED):
        raise PortfolioError("MonedaSerie no reconocida.")

    raw_dates = frame["FechaVerificacion"]
    if not raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise PortfolioError("FechaVerificacion debe usar YYYY-MM-DD.")
    verified = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if verified.isna().any() or (verified.dt.date > date.today()).any():
        raise PortfolioError("FechaVerificacion debe ser válida y no futura.")
    frame["Fuente"] = frame["Fuente"].map(_clean_source)

    for row in frame.itertuples(index=False):
        if row.MonedaSerie != declared_quotes[row.Instrumento]:
            raise PortfolioError(
                f"MonedaSerie de {row.Instrumento} no coincide con la cotización declarada."
            )
        if row.TipoSerie == FOREIGN_PROXY:
            if row.MercadoNegociacion != "SIC" or row.MercadoSerie != "ORIGEN_EXTRANJERO":
                raise PortfolioError(
                    "PROXY_ORIGEN_AJUSTADO requiere negociación SIC y serie ORIGEN_EXTRANJERO."
                )
        elif row.MercadoSerie != row.MercadoNegociacion or row.MonedaSerie != "MXN":
            raise PortfolioError(
                "CIERRE_LOCAL_AJUSTADO requiere el mismo mercado negociable y serie en MXN."
            )
    detail = frame.set_index("Instrumento").loc[list(expected)].reset_index()
    return InstrumentIdentityProfile(
        detail=detail,
        proxy_assets=tuple(detail.loc[detail["TipoSerie"].eq(FOREIGN_PROXY), "Instrumento"]),
        fingerprint=sha256(contents).hexdigest(),
    )
