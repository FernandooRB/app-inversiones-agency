from datetime import date, timedelta

import pytest

from data_rights import read_data_rights_csv
from portfolio_core import PortfolioError

HEADER = (
    "Fuente,Producto,Mercados,FechaRevision,VigenciaHasta,EstadoDerechos,"
    "AlcanceAutorizado,AjusteCorporativo,HoraCorteZona,ReferenciaContractual\n"
)


def row(**changes) -> bytes:
    reviewed = (date.today() - timedelta(days=10)).isoformat()
    expires = (date.today() + timedelta(days=365)).isoformat()
    values = {
        "source": "Proveedor de prueba",
        "product": "Cierres diarios",
        "markets": "BMV y SIC",
        "reviewed": reviewed,
        "expires": expires,
        "status": "CONFIRMADO",
        "scope": "ENTREGABLES_DERIVADOS",
        "adjustment": "AJUSTADO",
        "cutoff": "Cierre oficial America/Mexico_City",
        "reference": "Contrato ficticio sección 4",
    }
    values.update(changes)
    return (HEADER + ",".join(values.values()) + "\n").encode()


def test_reads_confirmed_profile_and_exposes_permissions():
    result = read_data_rights_csv(row())
    assert result.source == "Proveedor de prueba"
    assert result.reviewed_on == date.today() - timedelta(days=10)
    assert result.expires_on == date.today() + timedelta(days=365)
    assert result.allows_client_deliverables
    assert not result.allows_data_redistribution
    assert len(result.fingerprint) == 64


def test_allows_blank_expiry_for_indefinite_contract():
    result = read_data_rights_csv(row(expires="", scope="INVESTIGACION_INTERNA"))
    assert result.expires_on is None
    assert not result.allows_client_deliverables


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "PENDIENTE"}, "CONFIRMADO"),
        ({"scope": "PUBLICO"}, "AlcanceAutorizado"),
        ({"adjustment": "NO_AJUSTADO"}, "AJUSTADO"),
        ({"expires": (date.today() - timedelta(days=11)).isoformat()}, "anterior"),
    ],
)
def test_rejects_unusable_rights_profiles(changes, message):
    with pytest.raises(PortfolioError, match=message):
        read_data_rights_csv(row(**changes))


def test_rejects_expired_and_future_reviews():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(PortfolioError, match="vencido"):
        read_data_rights_csv(row(expires=yesterday))
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(PortfolioError, match="futuro"):
        read_data_rights_csv(row(reviewed=tomorrow, expires=""))
