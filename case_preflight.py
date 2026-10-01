"""Non-persistent, fail-closed inventory of evidence for one account analysis.

This inventory never authorizes a client deliverable. Uploaded manifests and
arithmetical reconciliations still require independent document review.
"""

from dataclasses import dataclass
from datetime import date

from account_scope import AccountScope
from cash_bridge import CashBridge
from data_rights import DataRightsProfile
from holdings import CurrentHoldings
from holdings_control import (
    HoldingsCoverageControl,
    HoldingsDetailControl,
    HoldingsTotalControl,
)
from implementation_costs import OrderCostRule
from instrument_identity import InstrumentIdentityProfile
from position_bridge import PositionBridge
from price_quality import PriceQualityIssue
from price_source_validation import PriceSourceComparison


@dataclass(frozen=True)
class CasePreflightInputs:
    account_scope: AccountScope | None = None
    account_scope_fingerprint: str | None = None
    holdings: CurrentHoldings | None = None
    holdings_fingerprint: str | None = None
    holdings_detail: HoldingsDetailControl | None = None
    holdings_total: HoldingsTotalControl | None = None
    holdings_coverage: HoldingsCoverageControl | None = None
    cash_bridge: CashBridge | None = None
    position_bridge: PositionBridge | None = None
    price_rights: DataRightsProfile | None = None
    price_fingerprint: str | None = None
    identity: InstrumentIdentityProfile | None = None
    price_comparison: PriceSourceComparison | None = None
    price_quality_issues: tuple[PriceQualityIssue, ...] = ()
    order_rules: tuple[OrderCostRule, ...] | None = None
    order_tariff_fingerprint: str | None = None


@dataclass(frozen=True)
class PreflightControl:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class CasePreflight:
    account_alias: str | None
    controls: tuple[PreflightControl, ...]

    @property
    def unresolved_count(self) -> int:
        return sum(control.status != "EVIDENCIA_CARGADA" for control in self.controls)

    @property
    def client_delivery_allowed(self) -> bool:
        # No application input is a substitute for legal, labor and human signoff.
        return False


def _digest(value: str | None) -> str:
    return f"SHA-256 {value[:12]}" if value else "sin huella"


def evaluate_case_preflight(inputs: CasePreflightInputs, *, today: date | None = None) -> CasePreflight:
    """List what the existing application actually checked and what remains open."""
    today = today or date.today()
    rows: list[PreflightControl] = []

    def add(name: str, status: str, detail: str) -> None:
        rows.append(PreflightControl(name, status, detail))

    scope = inputs.account_scope
    if scope is None or not inputs.account_scope_fingerprint:
        add("Alcance de cuenta", "PENDIENTE", "Carga el manifiesto de una cuenta y sus archivos vinculados.")
    elif (scope.tariff_fingerprint != inputs.order_tariff_fingerprint
          or (scope.holdings_fingerprint is not None
              and scope.holdings_fingerprint != inputs.holdings_fingerprint)):
        add("Alcance de cuenta", "ALERTA", "Las huellas de cartera o tarifas no coinciden con el alcance.")
    else:
        add("Alcance de cuenta", "EVIDENCIA_CARGADA", _digest(inputs.account_scope_fingerprint))

    rights = inputs.price_rights
    if rights is None or not inputs.price_fingerprint:
        add("Derechos de precios", "PENDIENTE", "Faltan precios aportados y manifiesto de derechos.")
    elif rights.expires_on is not None and rights.expires_on < today:
        add("Derechos de precios", "ALERTA", "El manifiesto declarado está vencido; revisa el contrato.")
    elif not rights.allows_client_deliverables:
        add("Derechos de precios", "ALERTA", "El alcance declarado permite sólo uso interno.")
    else:
        add("Derechos de precios", "EVIDENCIA_CARGADA", (
            f"Datos {_digest(inputs.price_fingerprint)}; manifiesto {_digest(rights.fingerprint)}. "
            "El contrato debe verificarse fuera de la app."
        ))

    identity = inputs.identity
    if identity is None:
        add("Identidad de instrumentos", "PENDIENTE", "Falta el manifiesto de series e ISIN.")
    elif identity.proxy_assets:
        add("Identidad de instrumentos", "ALERTA", (
            f"{len(identity.proxy_assets)} serie(s) proxy; confirmar cierre local y negociabilidad."
        ))
    else:
        add("Identidad de instrumentos", "EVIDENCIA_CARGADA", (
            f"{_digest(identity.fingerprint)}; cubre sólo tickers del CSV de precios. "
            "Verificar fuente oficial, serie exacta y vehículos preparados."
        ))

    holdings = inputs.holdings
    if holdings is None or not inputs.holdings_fingerprint:
        add("Cartera actual", "PENDIENTE", "Falta la cartera valuada de la cuenta.")
    else:
        add("Cartera actual", "EVIDENCIA_CARGADA", (
            f"Corte {holdings.as_of.date().isoformat()}; {_digest(inputs.holdings_fingerprint)}."
        ))

    cutoff = holdings.as_of.date() if holdings is not None else None
    for name, control, detail in (
        ("Detalle de posiciones", inputs.holdings_detail, "Falta cotejar importes por instrumento."),
        ("Subtotal de posiciones", inputs.holdings_total, "Falta cotejar subtotal con el estado."),
        ("Cobertura de cuenta", inputs.holdings_coverage, "Falta ligar cartera, efectivo y total."),
    ):
        if control is None:
            add(name, "PENDIENTE", detail)
        elif cutoff is None or control.as_of != cutoff:
            add(name, "ALERTA", "La fecha del control no coincide con la cartera cargada.")
        else:
            add(name, "EVIDENCIA_CARGADA", _digest(control.fingerprint))

    cash = inputs.cash_bridge
    coverage = inputs.holdings_coverage
    if cash is None:
        add("Efectivo", "PENDIENTE", "Falta conciliar saldo inicial, movimientos y cierre.")
    elif coverage is None or cash.end_date != coverage.as_of or cash.closing_cash != coverage.outside_cash:
        add("Efectivo", "ALERTA", "El puente no coincide con la cobertura cargada.")
    elif cash.other_movement_count:
        add("Efectivo", "ALERTA", "Hay movimientos clasificados como OTRA_ENTRADA u OTRA_SALIDA.")
    else:
        add("Efectivo", "EVIDENCIA_CARGADA", _digest(cash.fingerprint))

    bridge = inputs.position_bridge
    if bridge is None:
        add("Cantidades de títulos", "PENDIENTE", "Falta conciliar movimientos y cantidades finales.")
    elif cutoff is None or bridge.end_date != cutoff:
        add("Cantidades de títulos", "ALERTA", "El cierre del puente no coincide con la cartera.")
    elif bridge.adjustment_count:
        add("Cantidades de títulos", "ALERTA", "Hay ajustes de cantidad que requieren soporte.")
    else:
        add("Cantidades de títulos", "EVIDENCIA_CARGADA", (
            f"Movimientos {_digest(bridge.ledger_fingerprint)}; "
            f"cierre {_digest(bridge.closing_fingerprint)}."
        ))

    rules = inputs.order_rules
    if not rules or not inputs.order_tariff_fingerprint or scope is None:
        add("Costos por orden", "PENDIENTE", "Faltan reglas vinculadas a la cuenta.")
    elif any(rule.tariff_kind == "PUBLICA" for rule in rules):
        add("Costos por orden", "ALERTA", "Hay tarifas públicas; verificar la comisión aplicable al cliente.")
    else:
        add("Costos por orden", "EVIDENCIA_CARGADA", (
            f"{len(rules)} regla(s); {_digest(inputs.order_tariff_fingerprint)}. "
            "Contrato y costos recurrentes requieren revisión."
        ))

    comparison = inputs.price_comparison
    if comparison is None:
        add("Contraste de precios", "PENDIENTE", "Falta una fuente independiente comparable.")
    elif comparison.review_reasons:
        add("Contraste de precios", "ALERTA", (
            f"{len(comparison.review_reasons)} motivo(s) de revisión entre fuentes."
        ))
    elif comparison.identity_fingerprints is None:
        add("Contraste de precios", "ALERTA", "No se contrastó identidad de serie entre fuentes.")
    else:
        add("Contraste de precios", "EVIDENCIA_CARGADA", (
            f"Principal {_digest(comparison.primary_fingerprint)}; "
            f"referencia {_digest(comparison.reference_fingerprint)}."
        ))

    if not inputs.price_fingerprint:
        add("Alertas de precios", "PENDIENTE", "No hay archivo de precios para revisar alertas.")
    elif inputs.price_quality_issues:
        add("Alertas de precios", "ALERTA", (
            f"{len(inputs.price_quality_issues)} alerta(s) heurística(s) pendientes de revisar."
        ))
    else:
        add("Alertas de precios", "EVIDENCIA_CARGADA", (
            "Sin alertas heurísticas en los precios cargados; no certifica su exactitud."
        ))

    add("Revisión del expediente", "PENDIENTE", (
        "Revisar originales, excepciones, costos, impuestos y PDF; registrar dos responsables."
    ))
    add("Permiso de entrega", "PENDIENTE", (
        "Resolver alcance jurídico y laboral, privacidad y derechos de datos antes de usar con clientes."
    ))
    return CasePreflight(scope.alias if scope is not None else None, tuple(rows))
