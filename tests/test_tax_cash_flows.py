from datetime import date

import pandas as pd
import pytest

from portfolio_core import PortfolioError
from tax_cash_flows import read_tax_cash_flows_csv

HEADER = (
    "FechaPago,Instrumento,TipoFlujo,ImporteBrutoMXN,ISRRetenidoMXN,"
    "ImpuestoExtranjeroRetenidoMXN,TratamientoFiscal,BaseRetencionMXN,"
    "DiasPeriodo,TasaControlPct,TasaReservaAdicionalPct,Fuente\n"
)


def ledger_csv() -> bytes:
    return (
        HEADER
        + "2026-09-01,AAA,DIVIDENDO_MEX,10000,1000,0,"
        "PF_DIVIDENDO_MEX_ART140,10000,,10,,Constancia nacional\n"
        + "2026-09-02,BBB,INTERES,5000,443.84,0,"
        "PF_INTERES_LIF2026,100000,180,0.90,,Constancia de intereses\n"
        + "2026-09-03,CCC,DIVIDENDO_EXTRANJERO_SIC,6000,0,900,"
        "ESCENARIO_TASA_ADICIONAL,,,,20,Estado de cuenta SIC\n"
        + "2026-09-04,DDD,DISTRIBUCION_FONDO_DEUDA,3000,100,0,"
        "RETENCION_DOCUMENTADA,,,,,Constancia del fondo\n"
        + "2026-09-05,EEE,DISTRIBUCION_FONDO_RV,4000,0,0,"
        "NO_ESTIMADO,,,,,Pendiente de clasificación\n"
    ).encode("utf-8-sig")


ASSETS = ("AAA", "BBB", "CCC", "DDD", "EEE")


def test_ledger_separates_documented_withholding_controls_and_additional_reserve():
    result = read_tax_cash_flows_csv(ledger_csv(), ASSETS, date(2026, 9, 19))

    assert result.fiscal_year == 2026
    assert result.gross_income == pytest.approx(28_000)
    assert result.domestic_withholding == pytest.approx(1_543.84)
    assert result.foreign_withholding == pytest.approx(900)
    assert result.expected_control_withholding == pytest.approx(
        1_000 + 100_000 * 0.009 * 180 / 365
    )
    assert result.additional_reserve == pytest.approx(1_200)
    assert result.unestimated_gross_income == pytest.approx(4_000)
    assert len(result.summary) == 5
    assert len(result.fingerprint) == 64

    dividend = result.detail.iloc[0]
    assert dividend["Retención esperada de control"] == pytest.approx(1_000)
    assert dividend["Diferencia contra control"] == pytest.approx(0)
    foreign = result.detail.iloc[2]
    assert foreign["Neto documentado"] == pytest.approx(5_100)
    assert foreign["Reserva adicional"] == pytest.approx(1_200)
    assert pd.isna(result.detail.iloc[4]["Reserva adicional"])


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("PF_DIVIDENDO_MEX_ART140,10000,,10,", "PF_DIVIDENDO_MEX_ART140,9000,,10,", "base igual"),
        ("PF_INTERES_LIF2026,100000,180,0.90,", "PF_INTERES_LIF2026,100000,180,1.0,", "0.90%"),
        ("ESCENARIO_TASA_ADICIONAL,,,,20", "ESCENARIO_TASA_ADICIONAL,,,,101", "entre 0 y 100"),
        ("NO_ESTIMADO,,,,,", "NO_ESTIMADO,,,,10,", "tasas de escenario vacíos"),
    ],
)
def test_rejects_inconsistent_treatment_inputs(old, new, message):
    with pytest.raises(PortfolioError, match=message):
        read_tax_cash_flows_csv(
            ledger_csv().replace(old.encode(), new.encode()), ASSETS, date(2026, 9, 19)
        )


def test_requires_one_fiscal_year_known_assets_and_no_future_flows():
    with pytest.raises(PortfolioError, match="un solo ejercicio"):
        read_tax_cash_flows_csv(
            ledger_csv().replace(b"2026-09-05,EEE", b"2025-09-05,EEE"),
            ASSETS,
            date(2026, 9, 19),
        )
    with pytest.raises(PortfolioError, match="fuera del análisis"):
        read_tax_cash_flows_csv(
            ledger_csv().replace(b"2026-09-05,EEE", b"2026-09-05,ZZZ"),
            ASSETS,
            date(2026, 9, 19),
        )
    with pytest.raises(PortfolioError, match="posterior"):
        read_tax_cash_flows_csv(ledger_csv(), ASSETS, date(2026, 9, 3))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("10000,1000,0", "10000,10001,0", "exceder"),
        ("5000,443.84,0", "5000,-1,0", "negativas"),
        ("Constancia del fondo", "=HYPERLINK(foo)", "fórmula CSV"),
        ("2026-09-02,BBB", "2026-02-30,BBB", "fecha inválida"),
    ],
)
def test_rejects_invalid_amounts_sources_and_dates(old, new, message):
    with pytest.raises(PortfolioError, match=message):
        read_tax_cash_flows_csv(
            ledger_csv().replace(old.encode(), new.encode()), ASSETS, date(2026, 9, 19)
        )
