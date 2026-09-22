from datetime import date

import pandas as pd
import pytest

from portfolio_core import PortfolioError
from price_source_validation import compare_price_sources

DATES = pd.date_range("2024-01-02", periods=80, freq="B")


def prices(*, changed_day: int | None = None, omit_day: int | None = None) -> bytes:
    lines = ["Fecha,A,B"]
    for index, day in enumerate(DATES):
        if index == omit_day:
            continue
        value = 100 + index * 0.1
        if index == changed_day:
            value *= 1.03
        lines.append(f"{day.date().isoformat()},{value:.5f},{200 + index * 0.2:.5f}")
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def rights(source: str, *, market: str = "BMV", cutoff: str = "Cierre local") -> bytes:
    return (
        "Fuente,Producto,Mercados,FechaRevision,VigenciaHasta,EstadoDerechos,"
        "AlcanceAutorizado,AjusteCorporativo,HoraCorteZona,ReferenciaContractual\n"
        f"{source},Cierres,{market},{date.today().isoformat()},,CONFIRMADO,"
        f"INVESTIGACION_INTERNA,AJUSTADO,{cutoff},Contrato de prueba\n"
    ).encode("utf-8-sig")


def identity(source: str = "Ficha A") -> bytes:
    today = date.today().isoformat()
    return (
        "Instrumento,ISIN,MercadoNegociacion,SimboloNegociacion,MercadoSerie,"
        "MonedaSerie,TipoSerie,FechaVerificacion,Fuente\n"
        f"A,US0378331005,BMV,A,BMV,MXN,CIERRE_LOCAL_AJUSTADO,{today},{source}\n"
        f"B,US5949181045,SIC,B,SIC,MXN,CIERRE_LOCAL_AJUSTADO,{today},{source}\n"
    ).encode("utf-8-sig")


def compare(reference=None, reference_rights=None, **kwargs):
    return compare_price_sources(
        prices(), rights("Proveedor A"),
        reference if reference is not None else prices(),
        reference_rights if reference_rights is not None else rights("Proveedor B"),
        ("A", "B"), {"A": "MXN", "B": "MXN"},
        date(2024, 1, 2), date(2024, 4, 30),
        tolerance_pct=1.0, minimum_coverage_pct=95.0, **kwargs,
    )


def test_identical_licensed_sources_have_no_automatic_alerts_but_no_certification():
    result = compare()
    assert result.status == "SIN_ALERTAS_AUTOMATICAS"
    assert result.common_sessions == 80
    assert result.coverage_ratio == 1
    assert result.discrepancies.empty
    assert (result.summary["Fechas fuera de umbral"] == 0).all()
    assert len(result.primary_fingerprint) == 64
    assert result.primary_source != result.reference_source
    assert result.identity_fingerprints is None
    assert "identidad entre fuentes no contrastada" in result.audit_note
    assert result.reference_fingerprint[:12] in result.audit_note
    assert "cobertura 100.0%" in result.audit_note


def test_compares_exact_security_and_series_identity_when_both_manifests_are_given():
    result = compare(
        primary_identity_csv=identity("Registro A"),
        reference_identity_csv=identity("Registro B"),
    )
    assert result.status == "SIN_ALERTAS_AUTOMATICAS"
    assert result.identity_fingerprints is not None
    assert result.identity_fingerprints[0] != result.identity_fingerprints[1]
    assert "identidad principal/referencia SHA-256" in result.audit_note
    assert result.identity_fingerprints[1][:12] in result.audit_note


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("US0378331005", "US0231351067", "ISIN"),
        (
            "SIC,B,SIC,MXN,CIERRE_LOCAL_AJUSTADO",
            "SIC,B,ORIGEN_EXTRANJERO,MXN,PROXY_ORIGEN_AJUSTADO",
            "MercadoSerie",
        ),
    ],
)
def test_rejects_comparison_of_different_security_or_market_series(old, new, field):
    reference = identity().replace(old.encode(), new.encode())
    with pytest.raises(PortfolioError, match=field):
        compare(primary_identity_csv=identity(), reference_identity_csv=reference)


def test_rejects_single_identity_manifest():
    with pytest.raises(PortfolioError, match="manifiestos de ambas fuentes"):
        compare(primary_identity_csv=identity())


def test_flags_one_material_difference_and_keeps_raw_prices_out_of_export():
    result = compare(reference=prices(changed_day=30))
    assert result.status == "REVISAR"
    assert result.summary.loc[0, "Fechas fuera de umbral"] == 1
    assert result.summary.loc[1, "Fechas fuera de umbral"] == 0
    assert result.discrepancies.iloc[0]["Instrumento"] == "A"
    assert abs(result.discrepancies.iloc[0]["Diferencia relativa"]) > 0.01
    assert not any("precio" in column.lower() for column in result.discrepancies.columns)
    assert "alertas:" in result.audit_note
    assert "REVISAR" in result.audit_note


def test_exposes_missing_sessions_and_market_convention_mismatch():
    result = compare(
        reference=prices(omit_day=30),
        reference_rights=rights("Proveedor B", market="SIC", cutoff="Cierre Nueva York"),
    )
    assert result.common_sessions == 79
    assert result.coverage_ratio == pytest.approx(79 / 80)
    assert result.missing_in_reference == (DATES[30].date().isoformat(),)
    assert any("mercados diferentes" in reason for reason in result.review_reasons)
    assert any("convenciones de corte" in reason for reason in result.review_reasons)


def test_rejects_same_provider_and_missing_or_invalid_inputs():
    with pytest.raises(PortfolioError, match="independiente"):
        compare(reference_rights=rights("Proveedor A"))
    shifted = prices().decode("utf-8-sig").splitlines()
    later_dates = pd.date_range("2024-03-01", periods=80, freq="B")
    shifted = "\n".join(
        [shifted[0], *[
            f"{day.date().isoformat()},{row.split(',', 1)[1]}"
            for day, row in zip(later_dates, shifted[1:], strict=True)
        ]]
    ).encode("utf-8-sig")
    with pytest.raises(PortfolioError, match="60 fechas comunes"):
        compare_price_sources(
            prices(), rights("Proveedor A"), shifted, rights("Proveedor B"),
            ("A", "B"), {"A": "MXN", "B": "MXN"},
            date(2024, 1, 2), date(2024, 7, 31),
            tolerance_pct=1.0, minimum_coverage_pct=95.0,
        )
    with pytest.raises(PortfolioError, match="moneda"):
        compare_price_sources(
            prices(), rights("Proveedor A"), prices(), rights("Proveedor B"),
            ("A", "B"), {"A": "MXN"}, date(2024, 1, 2), date(2024, 4, 30),
            tolerance_pct=1.0, minimum_coverage_pct=95.0,
        )
