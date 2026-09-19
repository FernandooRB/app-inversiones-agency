from datetime import date

import numpy as np
import pandas as pd
import pytest

from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioError
from tax_impact import estimate_tax_reserve, read_tax_basis_csv

HEADER = (
    "FechaCorte,Instrumento,CostoFiscalActualizadoMXN,TratamientoFiscal,"
    "TasaEscenarioPct,Fuente\n"
)


def profile_csv(second_treatment="ESCENARIO_TASA_DECLARADA", second_rate="30") -> bytes:
    today = date.today().isoformat()
    return (
        HEADER
        + f"{today},AAA,40000,PF_ACCIONES_BOLSA_ART129,10,Estado fiscal ficticio\n"
        + f"{today},BBB,70000,{second_treatment},{second_rate},Cálculo fiscal ficticio\n"
    ).encode("utf-8-sig")


def implementation():
    return estimate_implementation_cost(
        ("AAA", "BBB"),
        np.array([0.2, 0.8]),
        100_000,
        ImplementationCostAssumptions(commission_bps=10),
        alternative_name="Escenario",
        current_weights=np.array([0.6, 0.4]),
    )


def test_estimates_reserve_from_proportional_updated_basis_and_sale_commission():
    profile = read_tax_basis_csv(profile_csv(), ("AAA", "BBB"), date.today())
    result = estimate_tax_reserve(
        implementation(), pd.Series({"AAA": 60_000.0, "BBB": 40_000.0}), profile
    )
    assert result.sell_notional == pytest.approx(40_000)
    row = result.detail.iloc[0]
    assert row["Activo"] == "AAA"
    assert row["Costo fiscal asignado"] == pytest.approx(40_000 * (40_000 / 60_000))
    assert row["Venta neta estimada"] == pytest.approx(39_960)
    assert result.estimated_gross_gain == pytest.approx(13_293.333333)
    assert result.estimated_tax_reserve == pytest.approx(1_329.333333)
    assert result.unestimated_sell_notional == 0


def test_no_estimation_keeps_sale_visible_without_manufacturing_tax():
    profile = read_tax_basis_csv(
        profile_csv("NO_ESTIMADO", ""), ("AAA", "BBB"), date.today()
    )
    target = estimate_implementation_cost(
        ("AAA", "BBB"), np.array([0.8, 0.2]), 100_000,
        ImplementationCostAssumptions(), alternative_name="Escenario",
        current_weights=np.array([0.4, 0.6]),
    )
    result = estimate_tax_reserve(
        target, pd.Series({"AAA": 40_000.0, "BBB": 60_000.0}), profile
    )
    assert result.unestimated_sell_notional == pytest.approx(40_000)
    assert result.estimated_tax_reserve == 0
    assert pd.isna(result.detail.iloc[0]["Reserva fiscal estimada"])


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (profile_csv().replace(b"PF_ACCIONES_BOLSA_ART129,10", b"PF_ACCIONES_BOLSA_ART129,9"), "10%"),
        (profile_csv().replace(b"ESCENARIO_TASA_DECLARADA,30", b"DESCONOCIDO,30"), "no reconocido"),
        (profile_csv().replace(b"ESCENARIO_TASA_DECLARADA,30", b"NO_ESTIMADO,30"), "vacía"),
        (profile_csv().replace(b"ESCENARIO_TASA_DECLARADA,30", b"NO_ESTIMADO,abc"), "vacía"),
    ],
)
def test_rejects_inconsistent_treatments(contents, message):
    with pytest.raises(PortfolioError, match=message):
        read_tax_basis_csv(contents, ("AAA", "BBB"), date.today())


def test_requires_same_date_and_exact_assets_as_holdings():
    with pytest.raises(PortfolioError, match="fecha fiscal"):
        read_tax_basis_csv(profile_csv(), ("AAA", "BBB"), date(2020, 1, 1))
    with pytest.raises(PortfolioError, match="no coinciden"):
        read_tax_basis_csv(profile_csv(), ("AAA", "CCC"), date.today())
