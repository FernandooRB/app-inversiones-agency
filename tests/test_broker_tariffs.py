from datetime import date, timedelta

import pytest

from broker_tariffs import read_broker_tariff_csv
from implementation_costs import estimate_implementation_cost
from portfolio_core import PortfolioError

HEADER = (
    "Intermediario,Producto,Mercado,FechaConsulta,ComisionOperacionPct,"
    "IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,"
    "CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente\n"
)
DATED_HEADER = (
    "Intermediario,Producto,Mercado,TipoTarifa,VigenteDesde,VigenteHasta,"
    "FechaConsulta,ComisionOperacionPct,IVAPctComision,ComisionMinimaMXN,"
    "CostoMercadoPbSupuesto,CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente\n"
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
    assert result.tariff_kind == "SIN_ALCANCE"
    assert result.valid_from is None


def test_reads_client_negotiated_rate_with_explicit_validity():
    today = date.today()
    contents = (
        DATED_HEADER
        + f"Casa,Capitales,SIC,NEGOCIADA_CLIENTE,{today - timedelta(days=10)},"
        + f"{today + timedelta(days=10)},{today},0.12,16,0,5,0,0,Acuerdo interno\n"
    ).encode()
    result = read_broker_tariff_csv(contents)
    assert result.tariff_kind == "NEGOCIADA_CLIENTE"
    assert result.valid_from == today - timedelta(days=10)
    assert result.valid_until == today + timedelta(days=10)
    assert result.assumptions.commission_bps == pytest.approx(12)


def test_client_rate_changes_estimated_order_cost_for_the_same_portfolio():
    today = date.today()
    row = (
        "Casa,Capitales,BMV,{kind},{today},,{today},{rate},16,0,0,0,0,{source}\n"
    )
    public = read_broker_tariff_csv((DATED_HEADER + row.format(
        kind="PUBLICA", today=today, rate="0.25", source="Guia publica",
    )).encode())
    negotiated = read_broker_tariff_csv((DATED_HEADER + row.format(
        kind="NEGOCIADA_CLIENTE", today=today, rate="0.12", source="Acuerdo interno",
    )).encode())
    public_cost = estimate_implementation_cost(
        ("AAA",), [1], 100_000, public.assumptions, alternative_name="Objetivo",
    )
    client_cost = estimate_implementation_cost(
        ("AAA",), [1], 100_000, negotiated.assumptions, alternative_name="Objetivo",
    )
    assert public_cost.commission == pytest.approx(250)
    assert client_cost.commission == pytest.approx(120)
    assert client_cost.vat == pytest.approx(19.2)
    assert client_cost.total_cost < public_cost.total_cost


@pytest.mark.parametrize("offset", [-1, 11])
def test_rejects_rate_outside_declared_validity(offset):
    today = date.today()
    contents = (
        DATED_HEADER
        + f"Casa,Capitales,BMV,CONTRACTUAL,{today},"
        + f"{today + timedelta(days=10)},{today},0.15,16,0,0,0,0,Contrato\n"
    ).encode()
    with pytest.raises(PortfolioError, match="no está vigente"):
        read_broker_tariff_csv(contents, as_of=today + timedelta(days=offset))


def test_rejects_unrecognized_rate_kind_and_reversed_validity():
    today = date.today()
    base = f"Casa,Capitales,BMV,{{kind}},{{start}},{{end}},{today},0.15,16,0,0,0,0,Contrato\n"
    with pytest.raises(PortfolioError, match="TipoTarifa"):
        read_broker_tariff_csv((DATED_HEADER + base.format(
            kind="OFERTA", start=today, end="",
        )).encode())
    with pytest.raises(PortfolioError, match="VigenteHasta"):
        read_broker_tariff_csv((DATED_HEADER + base.format(
            kind="CONTRACTUAL", start=today, end=today - timedelta(days=1),
        )).encode())


def test_rejects_formula_like_source_instead_of_exposing_it_in_report():
    today = date.today()
    contents = (
        DATED_HEADER
        + f"Casa,Capitales,BMV,PUBLICA,{today},,{today},0.25,16,0,0,0,0,=HYPERLINK()\n"
    ).encode()
    with pytest.raises(PortfolioError, match="Fuente"):
        read_broker_tariff_csv(contents)


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
