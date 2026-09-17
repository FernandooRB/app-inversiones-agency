import pandas as pd
import pytest

from instruments import analysis_inputs, load_catalog, validate_catalog
from portfolio_core import PortfolioError


def test_builtin_catalog_is_valid_and_has_pilot_asset_types():
    catalog = load_catalog()
    assert {"BMV", "SIC", "MERCADO_DINERO"}.issubset(set(catalog["market"]))
    assert {"discount_instrument", "fixed_coupon_bond", "total_return_price"}.issubset(
        set(catalog["valuation_model"])
    )


def test_analysis_inputs_excludes_debt_cash_and_reference_rates():
    inputs = analysis_inputs(load_catalog())
    assert set(inputs["analysis_symbol"]) == {"AMXB.MX", "AAPL", "SPY"}
    assert not inputs["analysis_symbol"].str.startswith("BANXICO").any()
    bond = load_catalog().loc[lambda table: table["instrument_id"].eq("MX_BONOS_M")].iloc[0]
    assert bond["integration_status"] == "PREPARACION_ARCHIVO"
    assert bond["analysis_method"] == "user_clean_accrued_coupon"
    liquidity = load_catalog().loc[
        lambda table: table["instrument_id"].eq("MX_CASH")
    ].iloc[0]
    assert liquidity["integration_status"] == "PREPARACION_ARCHIVO"
    assert liquidity["analysis_method"] == "user_annual_rate_accrual"
    fund = load_catalog().loc[
        lambda table: table["instrument_id"].eq("FUND_MXN_TEMPLATE")
    ].iloc[0]
    assert fund["integration_status"] == "PREPARACION_ARCHIVO"
    assert fund["analysis_method"] == "user_share_value_distribution"


def test_sic_rows_are_explicit_foreign_market_proxies():
    catalog = load_catalog()
    sic = catalog[catalog["market"].eq("SIC")]
    assert sic["trade_currency"].eq("MXN").all()
    assert sic["analysis_currency"].eq("USD").all()
    assert sic["integration_status"].eq("DIRECTO_CON_PROXY").all()
    assert sic["notes"].str.contains("no es el precio local").all()


def test_validation_rejects_direct_fixed_income():
    catalog = load_catalog()
    index = catalog.index[catalog["instrument_id"].eq("MX_CETES_28")][0]
    catalog.loc[index, "integration_status"] = "DIRECTO_ACTUAL"
    with pytest.raises(PortfolioError, match="deuda"):
        validate_catalog(catalog)


def test_validation_rejects_missing_columns():
    with pytest.raises(PortfolioError, match="faltan columnas"):
        validate_catalog(pd.DataFrame({"instrument_id": ["X"]}))
