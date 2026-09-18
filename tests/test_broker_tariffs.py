from datetime import date, timedelta

import pytest

from broker_tariffs import read_broker_tariff_csv
from portfolio_core import PortfolioError

HEADER = (
    "Intermediario,Producto,Mercado,FechaConsulta,ComisionOperacionPct,"
    "IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,"
    "CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente\n"
)


def test_reads_one_contractual_profile_and_converts_percentages():
    contents = (
        HEADER
        + "Casa de Bolsa,Cuenta digital,Capitales MX y SIC,2026-09-01,0.25,16,20,8,1032,1.0,"
        + "Guía contractual vigente\n"
    ).encode()
    result = read_broker_tariff_csv(contents)
    assert result.intermediary == "Casa de Bolsa"
    assert result.consulted_on == date(2026, 9, 1)
    assert result.assumptions.commission_bps == pytest.approx(25)
    assert result.assumptions.vat_rate == pytest.approx(0.16)
    assert result.assumptions.annual_recurring_cost(100_000) == pytest.approx(2_032)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("", "exactamente un perfil"),
        (
            "Casa,Producto,Capitales,2026-09-01,-0.1,16,0,0,0,0,Fuente\n",
            "[Cc]omisión",
        ),
        (
            "Casa,Producto,Capitales,2026-09-01,0.1,16,0,0,0,21,Fuente\n",
            "administración anual",
        ),
    ],
)
def test_rejects_invalid_profiles(row, message):
    with pytest.raises(PortfolioError, match=message):
        read_broker_tariff_csv((HEADER + row).encode())


def test_rejects_future_consultation_date():
    future = (date.today() + timedelta(days=1)).isoformat()
    row = f"Casa,Producto,Capitales,{future},0.1,16,0,0,0,0,Fuente\n"
    with pytest.raises(PortfolioError, match="futuro"):
        read_broker_tariff_csv((HEADER + row).encode())
