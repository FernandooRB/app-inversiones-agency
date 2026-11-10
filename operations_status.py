"""Current-run review findings, derived from existing operation checks without recalculation."""

import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

LABELS = {
    "ledger": "Libro de movimientos", "controls": "Controles de cierre",
    "quotes": "Cotizaciones de cierre", "fx": "FX del cierre",
    "repo_values": "Valuaciones de reportos", "nav": "Valuaciones históricas",
    "flow_fx": "FX de los flujos",
}
KINDS = {"CASH": "Efectivo liquidado", "PENDING": "Efectivo pendiente",
         "POSITION": "Títulos", "REPO": "Capital de reporto"}


@dataclass
class OperationStatus:
    inputs: dict = field(default_factory=dict)
    cutoff: str | None = None
    base: str | None = None
    book: dict | None = None
    reconciliation: dict | None = None
    calendar: dict | None = None
    events: list = field(default_factory=list)
    raw_confirmed: bool = False
    flows_confirmed: bool = False
    valuation: dict | None = None
    returns: dict | None = None
    errors: list = field(default_factory=list)
    documents: list = field(default_factory=list)
    failed_ledger: bool = False

    def input(self, role, source):
        if source is not None:
            raw = source.getvalue()
            self.inputs[role] = {"label": LABELS[role], "sha256": sha256(raw).hexdigest(), "bytes": len(raw)}

    def fail(self, area, stage, reason):
        self.errors.append({"area": area, "stage": stage, "reason": reason})
        if area == "ledger":
            self.failed_ledger = True
            self.book = self.valuation = self.returns = None

    def evidence(self, role):
        source = self.inputs.get(role)
        return f"{LABELS[role]} · SHA-256 {source['sha256']}" if source else f"{LABELS[role]} no aportado"

    def issues(self):
        rows = []

        def add(key, title, state, reason, evidence, action, *, step="ledger", area="Movimientos"):
            rows.append({"id": key, "title": title, "state": state, "reason": reason,
                         "evidence": evidence, "action": action, "step": step, "area": area})

        for index, error in enumerate(self.errors):
            add(f"error:{index}", "Insumo o herramienta rechazados", "Corregir",
                error["reason"], error["stage"], "Revisar " + error["stage"],
                area={"ledger": "Movimientos", "implementation": "Implementación",
                      "feeds": "Fuentes y alertas", "wealth": "Patrimonio",
                      "documents": "Originales GBM"}[error["area"]])
        if not self.inputs.get("ledger") and not self.failed_ledger:
            add("ledger", "Libro de movimientos", "Falta dato", "Carga un libro o retoma un paquete ZIP.",
                self.evidence("ledger"), "Abrir Movimientos")
        if self.book is not None:
            if self.reconciliation is None:
                add("controls", "Controles de cierre", "Falta dato",
                    "Aporta los saldos y fuentes del mismo cierre y cuenta para contrastar el libro.",
                    self.evidence("controls"), "Revisar controles de cierre", step="controls")
            else:
                for index, row in enumerate(self.reconciliation["rows"]):
                    if row["Estado"] == "COINCIDE":
                        continue
                    identity = " · ".join(filter(None, [KINDS[row["Tipo"]], row["InstrumentoReferencia"],
                                                       row["Moneda"]]))
                    values = f"{identity}. Libro: {row['Libro']} {row['Unidad']}. "
                    if row["Estado"] == "SIN_CONTROL":
                        reason = values + "Falta el saldo de control; no se interpreta como cero."
                    else:
                        reason = values + (f"Control: {row['Control']}. Diferencia libro − control: "
                                           f"{row['Diferencia']} {row['Unidad']}.")
                    add(f"control:{index}", "Saldo sin control" if row["Estado"] == "SIN_CONTROL"
                        else "Saldo con diferencia", "Falta dato" if row["Estado"] == "SIN_CONTROL"
                        else "Diferencia", reason,
                        self.evidence("controls") + (" · Fuente: " + row["Fuente"] if row["Fuente"] else ""),
                        "Revisar controles de cierre", step="controls")
            for role, needed in (("quotes", bool(self.book["positions"])),
                                 ("repo_values", bool(self.book["repos"]))):
                if needed and role not in self.inputs:
                    add(role, LABELS[role], "Falta dato", "Aporta valores documentados del cierre elegido.",
                        self.evidence(role), "Revisar valuación al cierre", step="valuation")
            currencies = set(self.book["cash"]) | set(self.book["pending"])
            currencies |= {c for _, c in self.book["positions"]} | {c for _, c in self.book["repos"]}
            if self.base and currencies - {self.base} and "fx" not in self.inputs:
                add("fx", LABELS["fx"], "Falta dato", "La conversión requiere FX fechado y fuente.",
                    self.evidence("fx"), "Revisar valuación al cierre", step="valuation")
            if not self.raw_confirmed:
                role = "quotes" if self.book["positions"] else (
                    "controls" if "controls" in self.inputs else "ledger"
                )
                add("prices-confirmation", "Fuentes de la valuación al cierre", "Por confirmar",
                    "Revisa los saldos y, cuando correspondan, precios sin ajuste, FX y valores de reportos.",
                    self.evidence(role), "Revisar valuación al cierre", step="valuation")
            if "nav" not in self.inputs:
                add("nav", LABELS["nav"], "Falta dato",
                    "Aporta cierres históricos para revisar el rendimiento.",
                    self.evidence("nav"), "Revisar valuaciones históricas", step="calendar")
            if self.calendar is not None:
                for row in self.calendar["rows"]:
                    if row["available"] or (row["required"] and "nav" not in self.inputs):
                        continue
                    add("date:" + row["date"], "Cierre " + row["date"],
                        "Falta dato" if row["required"] else "Condicional",
                        "; ".join(row["reasons"]), self.evidence("nav"),
                        "Revisar calendario de valuaciones", step="calendar")
            for event in self.events:
                if event.timing == "UNKNOWN":
                    add("timing:" + event.id, "Momento del flujo", "Por confirmar",
                        f"{event.settled.isoformat()} · {event.id}: confirma BOD o EOD contra su evidencia.",
                        self.evidence("ledger"), "Revisar flujos y calendario", step="calendar")
            if any(event.kind in {"TRANSFER_IN", "TRANSFER_OUT"} for event in self.events):
                add("transfers", "Alcance de los traspasos", "Por revisar",
                    "El libro conserva los traspasos declarados. Para excluirlos de los flujos de un "
                    "patrimonio consolidado se requiere una pareja acreditada entre cuentas.",
                    self.evidence("ledger"), "Revisar transferencias del patrimonio", area="Patrimonio")
            if any(e.currency != self.base for e in self.events) and "flow_fx" not in self.inputs:
                add("flow-fx", LABELS["flow_fx"], "Falta dato",
                    "Aporta FX documentado en cada fecha de flujo.",
                    self.evidence("flow_fx"), "Revisar flujos y calendario", step="calendar")
            if "nav" in self.inputs and not self.flows_confirmed:
                add("flows-confirmation", "Flujos y valuaciones del periodo", "Por confirmar",
                    "Revisa el periodo, moneda y todos los flujos externos antes de confirmar.",
                    self.evidence("nav"), "Revisar flujos y calendario", step="calendar")
            if self.returns is not None and self.returns["xirr"] is None:
                add("xirr", "XIRR anualizada", "Revisar", self.returns["xirr_status"],
                    self.evidence("nav"), "Revisar rendimiento histórico", step="calendar")
        for document in self.documents:
            digest = document["sha256"]
            for index, row in enumerate(document.get("differences", [])):
                add(f"document:{digest}:{index}", "Diferencia en original GBM", "Diferencia",
                    f"Página {row['Pagina']} · fila {row['Fila']} · diferencia: {row['Diferencia']} "
                    "MXN por confirmar. Requiere revisión de la fila original.",
                    f"{document['name']} · SHA-256 {digest}", "Revisar originales GBM", area="Originales GBM")
            add("document:" + digest, "Vinculación y revisión documental", "Por revisar",
                document["notice"], f"{document['name']} · SHA-256 {digest}",
                "Revisar originales GBM", area="Originales GBM")
        return rows

    def snapshot(self, scope):
        balances = []
        if self.book is not None:
            for section, label in (("cash", "Efectivo liquidado"), ("pending", "Efectivo pendiente"),
                                   ("positions", "Títulos"), ("repos", "Capital de reporto")):
                for key, value in self.book[section].items():
                    item, currency = ("", key) if section in {"cash", "pending"} else key
                    balances.append({"type": label, "item": item, "currency": currency,
                                     "value": str(value),
                                     "unit": "títulos" if section == "positions" else currency})
        issues = self.issues()
        return {"schema": 1, "scope": scope, "cutoff": self.cutoff, "base": self.base,
                "input_count": len(self.inputs), "inputs": self.inputs, "balances": balances,
                "issues": issues, "issue_count": len(issues),
                "conditional_count": sum(row["state"] == "Condicional" for row in issues),
                "ledger_failed": self.failed_ledger, "valuation": self.valuation, "returns": self.returns,
                "calendar": self.calendar, "documents": self.documents,
                "human_approval": None, "postings_created": 0,
                "notice": "Comprobaciones parciales de esta sesión; no acreditan aprobación humana ni "
                          "vinculación de los originales con el libro. Los importes no se ajustan.",
                "code_sha256": {name: sha256(Path(__file__).with_name(name).read_bytes()
                                            .replace(b"\r\n", b"\n")).hexdigest()
                                for name in ("operations_status.py", "operations_ui.py",
                                             "transaction_ledger.py",
                                             "ledger_reconciliation.py", "realized_performance.py")}}


def status_text(snapshot):
    """Readable plain text: uploaded identifiers are never treated as HTML, Markdown or formulas."""
    lines = ["Resumen de revisión de Operación", snapshot["notice"], "",
             f"Alcance: {snapshot['scope']}", f"Corte: {snapshot['cutoff'] or '—'}",
             f"Moneda: {snapshot['base'] or '—'}", f"Archivos CSV incluidos: {snapshot['input_count']}",
             f"Pendientes: {snapshot['issue_count']} · Condicionales: {snapshot['conditional_count']}", "",
             "Saldos del libro (sin sumar monedas ni convertir capital de reporto a NAV)"]
    for row in snapshot["balances"]:
        lines.append(f"{row['type']} · {row['item']} · {row['currency']}: {row['value']} {row['unit']}")
    if not snapshot["balances"]:
        lines.append("Sin saldos disponibles en esta revisión.")
    lines += ["", "Resultados disponibles"]
    if snapshot["valuation"] is not None:
        lines.append(f"Patrimonio neto al cierre: {snapshot['valuation']['nav']:,.2f} {snapshot['base']}")
    else:
        lines.append("Valuación al cierre: pendiente o no disponible en esta ejecución.")
    returns = snapshot["returns"]
    if returns is None:
        lines.append("Rendimiento: pendiente o no disponible en esta ejecución.")
    else:
        lines.append(f"Ganancia separada de flujos: {returns['gain']:,.2f} {snapshot['base']}")
        for label, key in (("TWR del periodo", "twr"), ("XIRR anualizada", "xirr")):
            value = f"{returns[key]:.2%}" if returns[key] is not None else "Pendiente"
            lines.append(f"{label}: {value} · {returns[key + '_status']}")
    if snapshot["calendar"] is not None:
        lines.append(f"Periodo: {snapshot['calendar']['start']} a {snapshot['calendar']['end']}")
    lines += ["", "Pendientes de revisión"]
    for row in snapshot["issues"]:
        lines.extend([f"{row['title']} · {row['state']}", row["reason"], "Evidencia: " + row["evidence"],
                      f"Siguiente acción: {row['action']} · {row['area']}", ""])
    lines += ["Resultados del motor y calendario", json.dumps(
        {key: snapshot[key] for key in ("valuation", "returns", "calendar")},
        ensure_ascii=False, default=str, allow_nan=False, indent=2), "", "Huellas de los insumos y el código",
        json.dumps({key: snapshot[key] for key in ("inputs", "code_sha256")}, ensure_ascii=False, indent=2),
        "", "Aprobación humana: pendiente. Movimientos de ajuste creados: 0."]
    return ("\n".join(lines) + "\n").encode("utf-8")
