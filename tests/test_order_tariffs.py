from datetime import date, timedelta

import pytest

from broker_tariffs import read_order_tariffs_csv
from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from portfolio_core import PortfolioError

HEADER = (
    "Activo,Intermediario,Producto,Mercado,Operacion,TipoTarifa,VigenteDesde,"
    "VigenteHasta,FechaConsulta,ComisionOperacionPct,IVAPctComision,"
    "ComisionMinimaMXN,CostoMercadoPbSupuesto,Fuente\n"
)


def _row(asset, operation, commission, *, valid_from=None, valid_until="", source="Acuerdo"):
    today = date.today().isoformat()
    return (
        f"{asset},Casa de prueba,Capitales,BMV,{operation},NEGOCIADA_CLIENTE,"
        f"{valid_from or today},{valid_until},{today},{commission},16,0,0,{source}\n"
    )


def test_imported_rules_drive_distinct_buy_and_sell_commissions():
    contents = (
        HEADER + _row("AAA", "COMPRA", "0.12") + _row("BBB", "VENTA", "0.30")
    ).encode("utf-8-sig")
    rules = read_order_tariffs_csv(contents, ("AAA", "BBB"))
    result = estimate_implementation_cost(
        ("AAA", "BBB"), [0.7, 0.3], 100_000,
        ImplementationCostAssumptions(), alternative_name="Rebalanceo",
        current_weights=[0.4, 0.6], order_rules=rules,
    )
    assert len(rules) == 2
    assert result.detail["Comisión"].tolist() == pytest.approx([36, 90])
    assert result.commission == pytest.approx(126)
    assert result.vat == pytest.approx(20.16)
    assert result.detail["Intermediario"].tolist() == ["Casa de prueba"] * 2


def test_importer_rejects_unknown_assets_and_overlapping_directions():
    with pytest.raises(PortfolioError, match="ajeno al análisis"):
        read_order_tariffs_csv((HEADER + _row("XXX", "AMBAS", "0.15")).encode(), ("AAA",))
    with pytest.raises(PortfolioError, match="duplicadas o superpuestas"):
        read_order_tariffs_csv((
            HEADER + _row("AAA", "AMBAS", "0.15") + _row("AAA", "VENTA", "0.20")
        ).encode(), ("AAA",))


def test_importer_rejects_expired_terms_and_later_consultation():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(PortfolioError, match="no está vigente"):
        read_order_tariffs_csv((HEADER + _row(
            "AAA", "AMBAS", "0.15", valid_from=yesterday, valid_until=yesterday,
        )).encode(), ("AAA",))
    with pytest.raises(PortfolioError, match="consulta posterior"):
        read_order_tariffs_csv((HEADER + _row(
            "AAA", "AMBAS", "0.15", valid_from=yesterday,
        )).encode(), ("AAA",), as_of=date.today() - timedelta(days=1))


def test_importer_rejects_incomplete_or_unsafe_terms():
    with pytest.raises(PortfolioError, match="ComisionOperacionPct"):
        read_order_tariffs_csv((HEADER + _row("AAA", "AMBAS", "")).encode(), ("AAA",))
    with pytest.raises(PortfolioError, match="Fuente"):
        read_order_tariffs_csv((HEADER + _row(
            "AAA", "AMBAS", "0.15", source="=HYPERLINK()",
        )).encode(), ("AAA",))
    with pytest.raises(PortfolioError, match="columnas requeridas"):
        incomplete = _row("AAA", "AMBAS", "0.15").rsplit(",", 1)[0] + "\n"
        read_order_tariffs_csv((HEADER + incomplete).encode(), ("AAA",))


def test_importer_never_falls_back_to_a_general_rate_for_missing_trade():
    rules = read_order_tariffs_csv((HEADER + _row("AAA", "COMPRA", "0.12")).encode(),
                                   ("AAA", "BBB"))
    with pytest.raises(PortfolioError, match="BBB.*compra"):
        estimate_implementation_cost(
            ("AAA", "BBB"), [0.5, 0.5], 100_000,
            ImplementationCostAssumptions(), alternative_name="Objetivo",
            order_rules=rules,
        )
