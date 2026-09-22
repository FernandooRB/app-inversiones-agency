from datetime import date

import pytest

from instrument_identity import read_instrument_identity_csv, valid_isin
from portfolio_core import PortfolioError

HEADER = (
    "Instrumento,ISIN,MercadoNegociacion,SimboloNegociacion,MercadoSerie,"
    "MonedaSerie,TipoSerie,FechaVerificacion,Fuente\n"
)


def identity_csv() -> bytes:
    today = date.today().isoformat()
    return (
        HEADER
        + f"AAPL,US0378331005,SIC,AAPL,ORIGEN_EXTRANJERO,USD,"
        f"PROXY_ORIGEN_AJUSTADO,{today},Ficha ficticia del instrumento\n"
        + f"MSFT,US5949181045,SIC,MSFT,SIC,MXN,"
        f"CIERRE_LOCAL_AJUSTADO,{today},Ficha ficticia del instrumento\n"
    ).encode("utf-8-sig")


def read(contents: bytes):
    return read_instrument_identity_csv(
        contents, ("MSFT", "AAPL"), {"MSFT": "MXN", "AAPL": "USD"}
    )


def test_isin_modulus_10_checks_structure_but_not_registry_authenticity():
    assert valid_isin("US0378331005")
    assert valid_isin("US5949181045")
    assert not valid_isin("US0378331006")
    assert not valid_isin("US037833100")


def test_profile_reorders_assets_and_discloses_origin_proxy():
    result = read(identity_csv())
    assert result.detail["Instrumento"].tolist() == ["MSFT", "AAPL"]
    assert result.proxy_assets == ("AAPL",)
    assert len(result.fingerprint) == 64


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("US0378331005", "US0378331006", "ISIN válido"),
        ("AAPL,US0378331005", "ZZZ,US0378331005", "cada instrumento"),
        ("ORIGEN_EXTRANJERO,USD,PROXY_ORIGEN_AJUSTADO", "SIC,USD,PROXY_ORIGEN_AJUSTADO", "requiere"),
        ("SIC,MXN,CIERRE_LOCAL_AJUSTADO", "SIC,USD,CIERRE_LOCAL_AJUSTADO", "MonedaSerie"),
        ("Ficha ficticia del instrumento", "=HIPERVINCULO(foo)", "fórmula CSV"),
    ],
)
def test_rejects_wrong_identity_units_or_export_formula(old, new, message):
    changed = identity_csv().replace(old.encode(), new.encode(), 1)
    with pytest.raises(PortfolioError, match=message):
        read(changed)


def test_rejects_future_verification_and_duplicate_security():
    future = identity_csv().replace(date.today().isoformat().encode(), b"2999-01-01")
    with pytest.raises(PortfolioError, match="no futura"):
        read(future)
    repeated = identity_csv().replace(b"US5949181045", b"US0378331005")
    with pytest.raises(PortfolioError, match="único"):
        read(repeated)
