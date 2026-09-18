"""Strict declaration of data-source rights and price-series conventions."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO

import pandas as pd

from portfolio_core import PortfolioError

MAX_RIGHTS_CSV_BYTES = 100_000
RIGHTS_COLUMNS = (
    "Fuente",
    "Producto",
    "Mercados",
    "FechaRevision",
    "VigenciaHasta",
    "EstadoDerechos",
    "AlcanceAutorizado",
    "AjusteCorporativo",
    "HoraCorteZona",
    "ReferenciaContractual",
)
ALLOWED_SCOPES = {
    "INVESTIGACION_INTERNA",
    "ENTREGABLES_DERIVADOS",
    "REDISTRIBUCION_DATOS",
}


@dataclass(frozen=True)
class DataRightsProfile:
    source: str
    product: str
    markets: str
    reviewed_on: date
    expires_on: date | None
    authorized_scope: str
    cutoff_convention: str
    contractual_reference: str
    fingerprint: str

    @property
    def allows_client_deliverables(self) -> bool:
        return self.authorized_scope in {"ENTREGABLES_DERIVADOS", "REDISTRIBUCION_DATOS"}

    @property
    def allows_data_redistribution(self) -> bool:
        return self.authorized_scope == "REDISTRIBUCION_DATOS"


def _clean_text(value, field: str, maximum: int) -> str:
    text = str(value).strip()
    if (
        not text or text.lower() == "nan" or len(text) > maximum
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError(f"{field} debe tener entre 1 y {maximum} caracteres válidos.")
    return text


def _read_date(value, field: str, *, optional: bool = False) -> date | None:
    raw = "" if pd.isna(value) else str(value).strip()
    if optional and not raw:
        return None
    if not pd.Series([raw]).str.fullmatch(r"\d{4}-\d{2}-\d{2}").iloc[0]:
        raise PortfolioError(f"{field} debe usar YYYY-MM-DD.")
    parsed = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        raise PortfolioError(f"{field} debe ser una fecha válida.")
    return parsed.date()


def read_data_rights_csv(contents: bytes) -> DataRightsProfile:
    """Read one confirmed rights profile for a team-supplied adjusted-price file."""
    if not contents:
        raise PortfolioError("El manifiesto de derechos de datos está vacío.")
    if len(contents) > MAX_RIGHTS_CSV_BYTES:
        raise PortfolioError("El manifiesto de derechos debe ocupar menos de 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el manifiesto de derechos de datos.") from exc
    if tuple(frame.columns) != RIGHTS_COLUMNS:
        raise PortfolioError(
            "El manifiesto de derechos debe contener exactamente las columnas de la plantilla "
            "y en el mismo orden."
        )
    if len(frame) != 1:
        raise PortfolioError("El manifiesto debe contener exactamente una fuente y producto.")

    row = frame.iloc[0]
    reviewed = _read_date(row["FechaRevision"], "FechaRevision")
    expires = _read_date(row["VigenciaHasta"], "VigenciaHasta", optional=True)
    if reviewed > date.today():
        raise PortfolioError("FechaRevision no puede estar en el futuro.")
    if expires is not None and expires < reviewed:
        raise PortfolioError("VigenciaHasta no puede ser anterior a FechaRevision.")
    if expires is not None and expires < date.today():
        raise PortfolioError("El manifiesto de derechos está vencido; vuelve a revisar el contrato.")

    status = _clean_text(row["EstadoDerechos"], "EstadoDerechos", 30).upper()
    if status != "CONFIRMADO":
        raise PortfolioError(
            "EstadoDerechos debe ser CONFIRMADO; una licencia pendiente o no autorizada no es válida."
        )
    scope = _clean_text(row["AlcanceAutorizado"], "AlcanceAutorizado", 40).upper()
    if scope not in ALLOWED_SCOPES:
        raise PortfolioError(
            "AlcanceAutorizado debe ser INVESTIGACION_INTERNA, ENTREGABLES_DERIVADOS "
            "o REDISTRIBUCION_DATOS."
        )
    adjustment = _clean_text(row["AjusteCorporativo"], "AjusteCorporativo", 30).upper()
    if adjustment != "AJUSTADO":
        raise PortfolioError(
            "AjusteCorporativo debe ser AJUSTADO para usar el archivo como precios ajustados."
        )

    return DataRightsProfile(
        source=_clean_text(row["Fuente"], "Fuente", 120),
        product=_clean_text(row["Producto"], "Producto", 120),
        markets=_clean_text(row["Mercados"], "Mercados", 120),
        reviewed_on=reviewed,
        expires_on=expires,
        authorized_scope=scope,
        cutoff_convention=_clean_text(row["HoraCorteZona"], "HoraCorteZona", 120),
        contractual_reference=_clean_text(
            row["ReferenciaContractual"], "ReferenciaContractual", 300
        ),
        fingerprint=sha256(contents).hexdigest(),
    )
