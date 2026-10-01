from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from account_scope import AccountScope
from case_preflight import CasePreflightInputs, evaluate_case_preflight
from cash_bridge import CashBridge
from data_rights import DataRightsProfile
from holdings import CurrentHoldings
from holdings_control import (
    HoldingsCoverageControl,
    HoldingsDetailControl,
    HoldingsTotalControl,
)
from implementation_costs import ImplementationCostAssumptions, OrderCostRule
from instrument_identity import InstrumentIdentityProfile
from position_bridge import PositionBridge, PositionBridgeLine
from price_quality import PriceQualityIssue
from price_source_validation import PriceSourceComparison

CUT = date(2026, 8, 31)
START = date(2026, 8, 1)
CENT = Decimal("0.00")


def _complete_evidence() -> CasePreflightInputs:
    values = pd.Series([100.0], index=["ACTIVO_A"])
    holdings = CurrentHoldings(values / 100, values, pd.Timestamp(CUT), 100.0)
    scope = AccountScope("Cuenta_Prueba", "Intermediario ficticio", "CARTERA", CUT,
                         CUT, "a" * 64, "b" * 64, "Estado de prueba")
    rights = DataRightsProfile("Proveedor ficticio", "Cierres", "BMV", CUT, None,
                               "ENTREGABLES_DERIVADOS", "Cierre", "Contrato prueba", "c" * 64)
    coverage = HoldingsCoverageControl(CUT, Decimal("100.00"), Decimal("0.00"),
                                       CENT, CENT, Decimal("100.00"), "Estado prueba", "d" * 64)
    cash = CashBridge(START, CUT, CENT, CENT, CENT, 0, 0, "Estado prueba", "e" * 64)
    line = PositionBridgeLine("ACTIVO_A", "TITULO", Decimal(1), CENT,
                              Decimal(1), Decimal("100.00"))
    bridge = PositionBridge(START, CUT, (line,), 0, 0, "Estado prueba", "f" * 64,
                            "Estado prueba", "1" * 64)
    rule = OrderCostRule("ACTIVO_A", "Ambas", "Intermediario ficticio", "Trading MX",
                         "BMV", START, None, CUT, "CONTRACTUAL", "Contrato prueba",
                         ImplementationCostAssumptions(commission_bps=25))
    comparison = PriceSourceComparison(
        "Principal", "Referencia", "2" * 64, "3" * 64, "4" * 64, "5" * 64,
        ("6" * 64, "7" * 64), 10, 10, 10, 1.0, (), (), 0.01,
        pd.DataFrame(), pd.DataFrame(), (),
    )
    return CasePreflightInputs(
        account_scope=scope, account_scope_fingerprint="8" * 64,
        holdings=holdings, holdings_fingerprint="a" * 64,
        holdings_detail=HoldingsDetailControl(CUT, 1, "9" * 64),
        holdings_total=HoldingsTotalControl(CUT, Decimal("100.00"),
                                            Decimal("100.00"), "Estado prueba", "0" * 64),
        holdings_coverage=coverage, cash_bridge=cash, position_bridge=bridge,
        price_rights=rights, price_fingerprint="2" * 64,
        identity=InstrumentIdentityProfile(pd.DataFrame(), (), "6" * 64),
        price_comparison=comparison, order_rules=(rule,), order_tariff_fingerprint="b" * 64,
    )


def _statuses(inputs: CasePreflightInputs, *, today: date = CUT) -> dict[str, str]:
    result = evaluate_case_preflight(inputs, today=today)
    return {item.name: item.status for item in result.controls}


def test_empty_case_lists_missing_controls_and_never_allows_delivery():
    result = evaluate_case_preflight(CasePreflightInputs(), today=CUT)
    statuses = {item.name: item.status for item in result.controls}
    assert result.account_alias is None
    assert statuses["Alcance de cuenta"] == "PENDIENTE"
    assert statuses["Alertas de precios"] == "PENDIENTE"
    assert statuses["Permiso de entrega"] == "PENDIENTE"
    assert not result.client_delivery_allowed


def test_loaded_evidence_still_requires_document_review_and_delivery_permission():
    evidence = _complete_evidence()
    result = evaluate_case_preflight(evidence, today=CUT)
    assert result.account_alias == "Cuenta_Prueba"
    assert result.unresolved_count == 2
    assert all(item.status == "EVIDENCIA_CARGADA" for item in result.controls[:-2])
    assert not result.client_delivery_allowed
    assert "SHA-256" in result.controls[0].detail


def test_scope_rights_cost_and_market_alerts_remain_open():
    evidence = _complete_evidence()
    scope = replace(evidence.account_scope, holdings_fingerprint="x" * 64)
    rights = replace(evidence.price_rights, authorized_scope="INVESTIGACION_INTERNA")
    identity = replace(evidence.identity, proxy_assets=("ACTIVO_A",))
    cash = replace(evidence.cash_bridge, other_movement_count=1)
    bridge = replace(evidence.position_bridge, adjustment_count=1)
    rules = (replace(evidence.order_rules[0], tariff_kind="PUBLICA"),)
    comparison = replace(evidence.price_comparison, identity_fingerprints=None)
    issue = PriceQualityIssue("ACTIVO_A", "Salto", "2026-08-01", "2026-08-02", "+30%")
    bad = replace(evidence, account_scope=scope, price_rights=rights, identity=identity,
                  cash_bridge=cash, position_bridge=bridge, order_rules=rules,
                  price_comparison=comparison, price_quality_issues=(issue,))
    statuses = _statuses(bad)
    for name in ("Alcance de cuenta", "Derechos de precios", "Identidad de instrumentos",
                 "Efectivo", "Cantidades de títulos", "Costos por orden",
                 "Contraste de precios", "Alertas de precios"):
        assert statuses[name] == "ALERTA"


def test_expired_rights_and_mismatched_dates_are_not_loaded():
    evidence = _complete_evidence()
    expired = replace(evidence.price_rights, expires_on=CUT)
    stale_total = replace(evidence.holdings_total, as_of=CUT - timedelta(days=1))
    stale_cash = replace(evidence.cash_bridge, end_date=CUT - timedelta(days=1))
    statuses = _statuses(replace(evidence, price_rights=expired,
                                 holdings_total=stale_total, cash_bridge=stale_cash),
                         today=CUT + timedelta(days=1))
    assert statuses["Derechos de precios"] == "ALERTA"
    assert statuses["Subtotal de posiciones"] == "ALERTA"
    assert statuses["Efectivo"] == "ALERTA"
