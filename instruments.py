"""Validated metadata catalog for Mexican and SIC instruments.

The catalog separates the security a client can trade from the time series used
by the current research engine. Those two things are not interchangeable for
SIC securities or fixed-income instruments.
"""

from pathlib import Path

import pandas as pd

from portfolio_core import PortfolioError

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "instrument_catalog.csv"
CATALOG_COLUMNS = (
    "instrument_id", "display_name", "asset_class", "market", "trade_symbol",
    "trade_currency", "analysis_symbol", "analysis_currency", "analysis_method",
    "valuation_model", "integration_status", "source_name", "source_url", "notes",
)
SUPPORTED_CURRENCIES = {"MXN", "USD", "EUR", "GBP", "CAD", "JPY", "CHF", "N/A"}
INTEGRATION_STATUSES = {
    "DIRECTO_ACTUAL", "DIRECTO_CON_PROXY", "PREPARACION_ARCHIVO", "REQUIERE_ADAPTADOR",
    "REFERENCIA_NO_INVERTIBLE",
}
DIRECT_STATUSES = {"DIRECTO_ACTUAL", "DIRECTO_CON_PROXY"}


def validate_catalog(catalog: pd.DataFrame) -> None:
    """Reject incomplete or internally inconsistent instrument metadata."""
    missing = set(CATALOG_COLUMNS) - set(catalog.columns)
    if missing:
        raise PortfolioError("Al catálogo le faltan columnas: " + ", ".join(sorted(missing)))
    if catalog.empty:
        raise PortfolioError("El catálogo de instrumentos está vacío.")
    if catalog["instrument_id"].isna().any() or catalog["instrument_id"].duplicated().any():
        raise PortfolioError("Cada instrumento debe tener un identificador único.")
    if not set(catalog["integration_status"]).issubset(INTEGRATION_STATUSES):
        raise PortfolioError("El catálogo contiene un estado de integración desconocido.")
    currencies = set(catalog["trade_currency"]) | set(catalog["analysis_currency"])
    if not currencies.issubset(SUPPORTED_CURRENCIES):
        raise PortfolioError("El catálogo contiene una moneda no admitida.")
    if not catalog["source_url"].str.startswith("https://").all():
        raise PortfolioError("Cada instrumento debe incluir una fuente HTTPS.")

    direct = catalog["integration_status"].isin(DIRECT_STATUSES)
    required = catalog.loc[direct, ["analysis_symbol", "analysis_currency", "analysis_method"]]
    if required.replace("", pd.NA).isna().any().any():
        raise PortfolioError("Todo instrumento integrado requiere símbolo, moneda y método de análisis.")
    fixed_income = catalog["valuation_model"].isin({"discount_instrument", "fixed_coupon_bond"})
    if (direct & fixed_income).any():
        raise PortfolioError("La deuda no puede entrar al motor de acciones sin un adaptador de valoración.")
    sic_direct = direct & catalog["market"].eq("SIC")
    if not catalog.loc[sic_direct, "integration_status"].eq("DIRECTO_CON_PROXY").all():
        raise PortfolioError("Un valor SIC con serie extranjera debe identificarse como proxy.")


def load_catalog(path: Path = CATALOG_PATH) -> pd.DataFrame:
    """Load and validate the versioned pilot catalog."""
    catalog = pd.read_csv(path, dtype=str, keep_default_na=False)
    validate_catalog(catalog)
    return catalog


def analysis_inputs(catalog: pd.DataFrame) -> pd.DataFrame:
    """Return current-engine symbols while preserving proxy disclosures."""
    validate_catalog(catalog)
    columns = [
        "instrument_id", "display_name", "analysis_symbol", "analysis_currency",
        "integration_status", "notes",
    ]
    return catalog.loc[catalog["integration_status"].isin(DIRECT_STATUSES), columns].reset_index(
        drop=True
    )


def display_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    """Build the concise Spanish table shown in the application."""
    validate_catalog(catalog)
    view = catalog[
        ["display_name", "asset_class", "market", "trade_currency", "analysis_symbol",
         "analysis_currency", "integration_status", "valuation_model"]
    ].copy()
    return view.rename(columns={
        "display_name": "Instrumento", "asset_class": "Clase", "market": "Mercado",
        "trade_currency": "Moneda de operación", "analysis_symbol": "Símbolo de análisis",
        "analysis_currency": "Moneda de la serie", "integration_status": "Integración",
        "valuation_model": "Modelo de valoración",
    })
