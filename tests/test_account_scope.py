from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256

import pytest

from account_scope import read_account_scope_csv
from broker_tariffs import read_order_tariffs_csv
from holdings import read_current_holdings_csv
from portfolio_core import PortfolioError

HEADER = (
    "AliasCuenta,Intermediario,PuntoPartida,FechaCorte,FechaRevision,"
    "HuellaCarteraSHA256,HuellaTarifasSHA256,FuenteAlcance\n"
)
TARIFF_HEADER = (
    "Activo,Intermediario,Producto,Mercado,Operacion,TipoTarifa,VigenteDesde,"
    "VigenteHasta,FechaConsulta,ComisionOperacionPct,IVAPctComision,"
    "ComisionMinimaMXN,CostoMercadoPbSupuesto,Fuente\n"
)


def _inputs():
    cutoff = (date.today() - timedelta(days=1)).isoformat()
    holdings_csv = (
        "FechaCorte,Instrumento,ValorMXN\n"
        f"{cutoff},AAA,60000\n{cutoff},BBB,40000\n"
    ).encode()
    tariff_csv = (
        TARIFF_HEADER
        + f"AAA,Casa de prueba,Acciones,BMV,AMBAS,CONTRACTUAL,{cutoff},,"
        f"{cutoff},0.12,16,0,2,Contrato de prueba\n"
        + f"BBB,Casa de prueba,ETF,SIC,AMBAS,CONTRACTUAL,{cutoff},,"
        f"{cutoff},0.30,16,0,5,Contrato de prueba\n"
    ).encode()
    holdings = read_current_holdings_csv(holdings_csv, ("AAA", "BBB"))
    rules = read_order_tariffs_csv(tariff_csv, ("AAA", "BBB"))
    return cutoff, holdings_csv, tariff_csv, holdings, rules


def _manifest(cutoff, holdings_csv, tariff_csv, *, intermediary="Casa de prueba"):
    return (
        HEADER
        + f"Cuenta_A,{intermediary},CARTERA,{cutoff},{date.today().isoformat()},"
        f"{sha256(holdings_csv).hexdigest()},{sha256(tariff_csv).hexdigest()},"
        "Estado de prueba revisado\n"
    ).encode()


def test_single_account_scope_binds_exact_holdings_and_tariffs():
    cutoff, holdings_csv, tariff_csv, holdings, rules = _inputs()
    scope = read_account_scope_csv(
        _manifest(cutoff, holdings_csv, tariff_csv),
        holdings_contents=holdings_csv, tariff_contents=tariff_csv,
        holdings=holdings, order_rules=rules,
    )
    assert scope.alias == "Cuenta_A"
    assert scope.starting_point == "CARTERA"
    assert scope.holdings_as_of == date.fromisoformat(cutoff)
    assert scope.holdings_fingerprint == sha256(holdings_csv).hexdigest()
    assert scope.tariff_fingerprint == sha256(tariff_csv).hexdigest()


def test_scope_rejects_swapped_files_or_broker():
    cutoff, holdings_csv, tariff_csv, holdings, rules = _inputs()
    manifest = _manifest(cutoff, holdings_csv, tariff_csv)
    with pytest.raises(PortfolioError, match="huella de tarifas"):
        read_account_scope_csv(
            manifest, holdings_contents=holdings_csv,
            tariff_contents=tariff_csv + b"\n", holdings=holdings, order_rules=rules,
        )
    with pytest.raises(PortfolioError, match="huella de cartera"):
        read_account_scope_csv(
            manifest, holdings_contents=holdings_csv + b"\n",
            tariff_contents=tariff_csv, holdings=holdings, order_rules=rules,
        )
    with pytest.raises(PortfolioError, match="intermediario"):
        read_account_scope_csv(
            _manifest(cutoff, holdings_csv, tariff_csv, intermediary="Otra casa"),
            holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings, order_rules=rules,
        )
    with pytest.raises(PortfolioError, match="intermediario"):
        read_account_scope_csv(
            manifest, holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings,
            order_rules=(rules[0], replace(rules[1], intermediary="Otra casa")),
        )


def test_scope_requires_imported_holdings_for_portfolio_and_no_holdings_for_cash():
    cutoff, holdings_csv, tariff_csv, holdings, rules = _inputs()
    with pytest.raises(PortfolioError, match="cartera valuada"):
        read_account_scope_csv(
            _manifest(cutoff, holdings_csv, tariff_csv),
            holdings_contents=b"", tariff_contents=tariff_csv,
            holdings=None, order_rules=rules,
        )
    cash_manifest = (
        HEADER
        + f"Cuenta_A,Casa de prueba,EFECTIVO,,{date.today().isoformat()},,"
        f"{sha256(tariff_csv).hexdigest()},Contrato de prueba\n"
    ).encode()
    cash_scope = read_account_scope_csv(
        cash_manifest, holdings_contents=b"", tariff_contents=tariff_csv,
        holdings=None, order_rules=rules,
    )
    assert cash_scope.starting_point == "EFECTIVO"
    with pytest.raises(PortfolioError, match="no debe incluir cartera"):
        read_account_scope_csv(
            cash_manifest, holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings, order_rules=rules,
        )


def test_scope_rejects_bad_cutoff_and_account_like_alias():
    cutoff, holdings_csv, tariff_csv, holdings, rules = _inputs()
    manifest = _manifest(cutoff, holdings_csv, tariff_csv)
    with pytest.raises(PortfolioError, match="FechaCorte"):
        read_account_scope_csv(
            manifest.replace(cutoff.encode(), b"2020-01-01"),
            holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings, order_rules=rules,
        )
    with pytest.raises(PortfolioError, match="cuentas ni correos"):
        read_account_scope_csv(
            manifest.replace(b"Cuenta_A", b"123456789012"),
            holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings, order_rules=rules,
        )
    with pytest.raises(PortfolioError, match="FuenteAlcance"):
        read_account_scope_csv(
            manifest.replace(b"Estado de prueba revisado", b"EDITAR_FUENTE"),
            holdings_contents=holdings_csv, tariff_contents=tariff_csv,
            holdings=holdings, order_rules=rules,
        )
