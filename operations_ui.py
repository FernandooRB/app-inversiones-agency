"""Account operations: reviewed evidence, ledger, implementation, feeds and wealth."""

import base64
import json
import logging
import re
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pandas as pd
import streamlit as st

from account_workflow import code_fingerprint
from analysis_session import analysis_key, session_compute
from case_workspace import WorkspaceError
from executable_allocation import cost_aware_target, executable_plan
from gbm_documents import read_cfdi_evidence, read_statement
from gbm_movement_ui import render_movement_import
from implementation_costs import ImplementationCostAssumptions
from ledger_reconciliation import COLUMNS as CONTROL_COLUMNS
from ledger_reconciliation import read_closing_controls, reconcile_book
from multi_currency_wealth import consolidate_wealth, consolidated_performance, match_internal_flows
from operations_comparison import compare_plans, plan_risk, strategy_from_analysis, validate_strategy
from operations_demo import DEMO_CONTEXT, DEMO_NAV_COMPLETE, DEMO_NAV_INVALID, demo_operations, demo_url
from operations_input_forms import complete_input
from operations_jobs import refresh_subscription
from operations_proposal import portable_proposal, proposal_pdf
from operations_proposal_ui import prepare_book_proposal
from operations_report import explain_performance, performance_pdf, summary_lines
from operations_review import review_code_fingerprints
from operations_review_ui import (
    download_review,
    new_review,
    open_review,
    proposal_key,
    recovered_proposal,
    reset_confirmation,
    review_defaults,
    review_key,
    review_upload,
)
from operations_status import OperationStatus, status_text
from portfolio_core import PortfolioError
from portfolio_exposure import _text
from realized_performance import Flow, normalize_valuations, performance, valuation_requirements
from transaction_ledger import COLUMNS, REPO_VALUE_COLUMNS, book_at, read_ledger, read_repo_values, value_book

EXTERNAL_EVENT_KINDS = {"DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT", "ASSET_IN", "ASSET_OUT"}
LOGGER = logging.getLogger(__name__)


def _key(name):
    return name + "_" + st.session_state.get("_ops_context_key", "temporary")


class _OperationInputError(PortfolioError):
    def __init__(self, stage, error):
        self.stage = stage
        self.error = error
        # Unexpected exception text may contain uploaded values or private paths.
        message = str(error) if isinstance(error, PortfolioError) else "No se pudo validar este insumo."
        super().__init__(message)


def _checked_input(stage, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (WorkspaceError, MemoryError, _OperationInputError):
        raise
    except Exception as error:
        raise _OperationInputError(stage, error) from None


def _cached_calculation(stage, function, *args, **kwargs):
    signature = analysis_key(review_key("calculation"), stage, review_code_fingerprints(), args, kwargs)
    return _checked_input(
        stage,
        session_compute,
        st.session_state,
        _key("operations_calculations"),
        signature,
        lambda: function(*args, **kwargs),
        max_entries=8,
    )


def _forget_book_reference():
    st.session_state.pop(_key("_ops_last_book"), None)
    st.session_state.pop(_key("_ops_book_signature"), None)


def _remember_book(book, cutoff, source):
    signature = analysis_key(
        {
            "ledger": sha256(source).hexdigest(),
            "cutoff": cutoff.isoformat(),
            "review": review_key("book_source"),
        }
    )
    if st.session_state.get(_key("_ops_book_signature")) != signature:
        # The monitor checkbox is rendered later, in Fuentes y alertas.
        st.session_state[_key("monitor_confirmation")] = False
    st.session_state[_key("_ops_book_signature")] = signature
    st.session_state[_key("_ops_last_book")] = {
        "book": book,
        "cutoff": cutoff.isoformat(),
        "ledger_sha256": sha256(source).hexdigest(),
    }


def _status_upload(label, role, *, key):
    source = review_upload(label, role, key=key)
    status = st.session_state.get(_key("_ops_status"))
    if status is not None:
        status.input(role, source)
    return source


def _open_review_step(area, step):
    st.session_state["operations_tabs"] = area
    st.session_state[_key("_ops_focus_step")] = step
    if step == "save":
        st.session_state[review_key("ops_review_save_panel")] = True


def _explanation_table(rows, name):
    key = _key(name)
    with st.container(key=key):
        st.html(f"""<style>
          .st-key-{key} table td:last-child, .st-key-{key} table th:last-child {{
            text-align:right!important;font-variant-numeric:tabular-nums;
          }}
        </style>""")
        st.table(pd.DataFrame(rows, columns=["Concepto", "Resultado"]).style.hide(axis="index"))


def _status_panel(context, *, demo=False, review_available=False):
    status = st.session_state.get(_key("_ops_status"))
    if status is None:
        return
    _store, _principal, state, account = context
    chosen = next((row for row in state["accounts"] if row["id"] == account), None) if state else None
    scope = "Sesión temporal · sin cuenta vinculada"
    if chosen:
        scope = f"{state['alias']} · {chosen['portfolio']} · {chosen['product']} · {chosen['currency']}"
    if demo:
        scope = "DEMO · datos de práctica SIG · sin cuenta vinculada"
    snapshot = status.snapshot(scope)
    snapshot["demo"] = demo
    if status.performance_summary is not None:
        st.header("Cuánto gané y por qué")
        st.caption(status.performance_summary["state"])
        explanation = status.performance_summary
        figures, meaning = st.columns([2, 1], gap="large")
        with figures:
            st.caption("Ganancia monetaria")
            rows = summary_lines(explanation)
            st.subheader(rows[4][1])
            _explanation_table(rows[:4] + [rows[9]], "performance_primary")
            with st.expander("Ingresos, cargos y detalle del rendimiento"):
                _explanation_table(rows[5:9] + [rows[10]], "performance_detail")
        with meaning:
            st.write("**Qué explica el cambio**")
            st.write("Separamos lo que aportaste o retiraste de la variación de tu patrimonio.")
            st.caption(
                "Los ingresos y cargos se muestran cuando su moneda permite compararlos. "
                "La variación no desglosada conserva lo que aún no se ha atribuido."
            )
            st.caption("Revisa los pendientes antes de utilizar el resultado.")
    if demo:
        snapshot["code_sha256"]["operations_demo.py"] = sha256(
            Path(__file__).with_name("operations_demo.py").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
    st.header("Estado de la revisión")
    st.text(f"{scope}\nCorte del libro: {status.cutoff or '—'} · Moneda: {status.base or '—'}")
    if status.calendar is not None:
        st.caption(f"Periodo del rendimiento: {status.calendar['start']} a {status.calendar['end']}.")
    guidance = snapshot["guidance"]
    st.write("**Siguiente paso: " + guidance["title"] + "**")
    st.button(
        guidance["action"],
        key=_key("guidance_next"),
        type="primary",
        on_click=_open_review_step,
        args=("Movimientos", guidance["step"]),
    )
    st.caption("Valuaciones → Revisión de flujos → Resultado → Resumen")
    st.text(guidance["detail"])
    st.caption(
        f"Calendario: {guidance['states']['calendar']} · "
        f"Flujos: {guidance['states']['flows']} · TWR: {guidance['states']['returns']}"
    )
    pending_label = "pendiente" if snapshot["issue_count"] == 1 else "pendientes"
    conditional_label = "condicional" if snapshot["conditional_count"] == 1 else "condicionales"
    files_label = "archivo CSV incluido" if snapshot["input_count"] == 1 else "archivos CSV incluidos"
    st.write(
        f"**{snapshot['issue_count']} {pending_label} de revisión** · "
        f"{snapshot['conditional_count']} {conditional_label} · "
        f"{snapshot['input_count']} {files_label}"
    )
    if review_available and not demo:
        st.button(
            "Guardar para continuar después",
            key=_key("review_save_next"),
            on_click=_open_review_step,
            args=("Movimientos", "save"),
        )
        st.caption(
            "Descarga el ZIP para retomar los CSV, el corte y la moneda. "
            "La sesión es temporal; el TXT sólo resume la revisión."
        )
    if status.failed_ledger:
        st.caption("La revisión de Movimientos falló; se retiraron sus saldos y resultados de este resumen.")
    issues = snapshot["issues"]
    if issues:
        first = issues[0]
        if first["action"] != guidance["action"]:
            st.button(
                first["action"],
                key=_key("status_next"),
                on_click=_open_review_step,
                args=(first["area"], first["step"]),
            )
    with st.expander("Pendientes y evidencia", expanded=not st.session_state.get(_key("_ops_focus_step"))):
        show_all = len(issues) > 3 and st.checkbox("Ver todos los pendientes", key=_key("status_show_all"))
        start, end = 0, min(3, len(issues))
        if show_all:
            pages = (len(issues) + 9) // 10
            # A replacement may shrink the list; bound the view before constructing its widget.
            page_key = _key("status_page")
            st.session_state[page_key] = min(max(st.session_state.get(page_key, 1), 1), pages)
            page = st.number_input("Página de pendientes", 1, pages, key=page_key) if pages > 1 else 1
            start, end = (page - 1) * 10, min(page * 10, len(issues))
            st.caption(f"Pendientes {start + 1} a {end} de {len(issues)}.")
        for item in issues[start:end]:
            with st.container(border=True):
                st.write(f"**{item['title']}** · {item['state']}")
                st.text(item["reason"])
                short_evidence = re.sub(
                    r"(SHA-256 )([a-f0-9]{64})", lambda m: m[1] + m[2][:12] + "…", item["evidence"]
                )
                st.text("Evidencia: " + short_evidence)
                if item["id"] == first["id"]:
                    st.caption(item["action"] + " · " + item["area"])
                else:
                    label = {
                        "controls": "Ver control",
                        "calendar": "Ver calendario",
                        "flows": "Ver revisión de flujos",
                        "valuation": "Ver valuación",
                    }.get(item["step"], "Ver etapa")
                    if item["area"] == "Originales GBM":
                        label = "Ver original"
                    elif item["area"] == "Patrimonio":
                        label = "Ver patrimonio"
                    st.button(
                        label,
                        key=_key("status_item_" + sha256(item["id"].encode()).hexdigest()[:12]),
                        on_click=_open_review_step,
                        args=(item["area"], item["step"]),
                    )
        if not issues:
            st.write(
                "Sin pendientes detectados por estas comprobaciones. La aprobación humana sigue pendiente."
            )
        st.caption(snapshot["notice"])
    with st.expander(
        "Archivos y resumen descargable", expanded=st.session_state.get(_key("_ops_focus_step")) == "summary"
    ):
        for source in status.inputs.values():
            st.text(f"{source['label']} · {source['bytes']:,} bytes · SHA-256 {source['sha256']}")
        if not status.inputs:
            st.write("Sin archivos CSV aportados en esta revisión.")
        st.caption(
            "Los archivos aportados conservan la validación y las confirmaciones de su etapa. "
            "El resumen contiene datos privados de la sesión actual y las huellas completas. "
            "El TXT no permite retomar los archivos."
        )
        st.download_button(
            "Descargar resumen de revisión",
            status_text(snapshot),
            f"{'demo_' if demo else ''}resumen_revision_{status.cutoff or 'sin_corte'}.txt",
            "text/plain",
            key=_key("status_download"),
            on_click="ignore",
        )
        if st.button("Preparar PDF breve", key=_key("performance_pdf_prepare")):
            raw = session_compute(
                st.session_state, "operations_pdf", analysis_key(snapshot), lambda: performance_pdf(snapshot)
            )
            st.download_button(
                "Descargar PDF de rendimiento",
                raw,
                f"{'demo_' if demo else ''}rendimiento_{status.cutoff or 'borrador'}.pdf",
                "application/pdf",
                key=_key("performance_pdf_download"),
                on_click="ignore",
            )


def _show_operation_error(area, label, error, *, public_validation=True):
    stage = error.stage if isinstance(error, _OperationInputError) else label
    original = error.error if isinstance(error, _OperationInputError) else error
    if public_validation and isinstance(original, PortfolioError):
        st.error(f"Revisa {stage}.")
        # Plain text prevents uploaded identifiers being interpreted as Markdown.
        st.text(str(original))
        reason = str(original)
    else:
        reference = uuid4().hex[:12]
        LOGGER.error(
            "Unexpected operation error area=%s type=%s reference=%s",
            area,
            type(original).__name__,
            reference,
        )
        st.error(f"No se pudo completar {stage}.")
        st.caption(f"Vuelve a intentarlo. Si persiste, conserva esta referencia: {reference}.")
        reason = f"No se pudo completar esta etapa. Referencia de soporte: {reference}."
    status = st.session_state.get(_key("_ops_status"))
    if status is not None and area != "workspace":
        status.fail(area, stage, reason)


def _render_operation_area(context, area, label, render):
    try:
        return render(context)
    except (WorkspaceError, MemoryError):
        raise
    except Exception as error:
        if area == "ledger":
            _forget_book_reference()
        _show_operation_error(area, label, error)


def _csv(upload):
    if upload is None:
        return None
    if len(upload.getvalue()) > 2_000_000:
        raise PortfolioError("El archivo supera 2 MB.")
    try:
        return pd.read_csv(BytesIO(upload.getvalue()), keep_default_na=False)
    except (ValueError, UnicodeError, pd.errors.ParserError):
        raise PortfolioError("No se pudo leer el CSV con encabezados.") from None


def _read_nav(upload):
    frame = _csv(upload)
    if not {"Fecha", "NAV"}.issubset(frame):
        raise PortfolioError("Las valuaciones requieren Fecha y NAV.")
    return normalize_valuations(frame.set_index("Fecha")["NAV"])


def _template(label, columns, key):
    st.download_button(
        label, (",".join(columns) + "\n").encode(), key + ".csv", "text/csv", key=key, on_click="ignore"
    )


def _context():
    from workspace_ui import configured_workspace

    try:
        store, principal, _ = configured_workspace()
    except WorkspaceError:
        st.caption("Operación temporal · abre Expedientes para configurar conservación cifrada por cuenta.")
        return None, None, None, None
    cases = {item["id"]: item["alias"] for item in store.list_cases(principal) if not item["archived"]}
    if not cases:
        st.info("Crea un expediente y una cuenta para conservar los resultados de operación.")
        return store, principal, None, None
    chosen = st.selectbox("Expediente de operación", list(cases), format_func=cases.get)
    state = store.read(principal, chosen)
    accounts = {
        item["id"]: f"{item['portfolio']} · {item['product']} · {item['currency']}"
        for item in state["accounts"]
    }
    account = (
        st.selectbox("Cuenta de operación", list(accounts), format_func=accounts.get) if accounts else None
    )
    return store, principal, state, account


def _save_evidence(context, label, payload):
    store, principal, state, account = context
    if store and state and account and principal.role in {"ADMIN", "ANALYST"}:
        if st.button(label):
            modules = (
                "transaction_ledger.py",
                "ledger_reconciliation.py",
                "realized_performance.py",
                "executable_allocation.py",
                "multi_currency_wealth.py",
                "gbm_documents.py",
                "instrument_catalogue.py",
            )
            payload = {
                "schema": 1,
                "code_sha256": {
                    name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in modules
                },
                **payload,
            }
            store.attach(
                principal,
                state["id"],
                state["revision"],
                f"operacion_{date.today()}_{uuid4().hex}.json",
                json.dumps(payload, ensure_ascii=False, default=str, allow_nan=False).encode(),
                account_id=account,
            )
            st.success(
                "Evidencia cifrada y versionada en el expediente; requiere las revisiones correspondientes."
            )


def _closing_reconciliation(context, book, cutoff, ledger_bytes, files=None):
    with st.expander(
        "Conciliar contra el estado de cuenta",
        expanded=st.session_state.get(_key("_ops_focus_step")) == "controls",
    ):
        st.caption(
            "Compara CASH (efectivo liquidado), PENDING (efectivo pendiente), POSITION (títulos) "
            "y REPO (capital por referencia). Usa saldos y fuentes del mismo cierre y cuenta."
        )
        _template("Plantilla de controles de cierre", CONTROL_COLUMNS, "closing_controls_template")
        source = _status_upload("Controles de cierre", "controls", key="ops_closing_controls")
        if st.session_state.get("_ops_context_key") != DEMO_CONTEXT:
            complete_input("controls", source, day=cutoff)
        if files is not None:
            files["controls"] = source
        if not source:
            st.info("Carga los saldos de control para contrastarlos con el libro, sin ajustar movimientos.")
            return None
        controls = _checked_input("Controles de cierre", read_closing_controls, source.getvalue(), cutoff)
        result = _checked_input("Controles de cierre", reconcile_book, book, controls, cutoff=cutoff)
        if result["status"] == "COINCIDENCIA_ARITMETICA":
            st.success(f"Controles con coincidencia aritmética: {result['exact']}.")
        else:
            st.warning(
                f"Revisión pendiente · Con diferencia: {result['differences']} "
                f"· Sin control: {result['missing']}."
            )
        view = pd.DataFrame(result["rows"]).rename(
            columns={"InstrumentoReferencia": "Instrumento / referencia"}
        )
        view["Tipo"] = view["Tipo"].replace(
            {
                "CASH": "Efectivo liquidado",
                "PENDING": "Efectivo pendiente",
                "POSITION": "Títulos",
                "REPO": "Capital de reporto",
            }
        )
        view["Estado"] = view["Estado"].replace(
            {
                "COINCIDE": "Coincide",
                "SIN_CONTROL": "Sin control",
                "DIFERENCIA": "Diferencia",
            }
        )
        st.dataframe(
            view.style.format(
                {
                    "Libro": "{:,.12g}",
                    "Control": "{:,.12g}",
                    "Diferencia": lambda value: f"{value:+,.12g}" if value else "0",
                },
                na_rep="—",
            ).set_properties(subset=["Libro", "Control", "Diferencia"], **{"text-align": "right"}),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Cada saldo conserva su unidad y moneda. Un control ausente sigue pendiente; "
            "la coincidencia aritmética no acredita integridad del estado ni aprobación de la cuenta."
        )
        payload = {
            **result,
            "ledger_sha256": sha256(ledger_bytes).hexdigest(),
            "controls_sha256": sha256(source.getvalue()).hexdigest(),
            "code_sha256": {
                name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("transaction_ledger.py", "ledger_reconciliation.py")
            },
        }
        st.download_button(
            "Descargar conciliación de cierre",
            json.dumps(payload, ensure_ascii=False, default=str).encode(),
            f"conciliacion_cierre_{cutoff}.json",
            "application/json",
            key=_key("closing_reconciliation_download"),
            on_click="ignore",
        )
        _save_evidence(context, "Conservar conciliación de cierre", payload)
        return payload


def _native_flow_amount(event):
    value = event.quantity * event.price if event.kind.startswith("ASSET_") else event.amount
    return float(value) * (-1 if event.kind in {"WITHDRAWAL", "TRANSFER_OUT", "ASSET_OUT"} else 1)


def _valuation_calendar(start, end, flows, available_dates=()):
    with st.expander(
        "Valuaciones necesarias para TWR",
        expanded=st.session_state.get(_key("_ops_focus_step")) == "calendar",
    ):
        if start >= end:
            st.info("Selecciona un cierre posterior a la apertura del libro para planear el periodo.")
            return None
        result = valuation_requirements(start, end, flows, available_dates=available_dates)
        st.caption(f"Periodo del plan: {start.isoformat()} a {end.isoformat()}.")
        if result["twr_coverage_ready"]:
            st.success("Las fechas y los momentos declarados cubren el calendario de TWR.")
            st.caption(
                "Calendario completo se refiere a fechas y momentos. "
                "Sigue en Revisión de flujos y resultado: revisa importes, moneda y fuentes "
                "antes de marcar la confirmación."
            )
        else:
            st.warning(
                "Calendario pendiente · Cierres obligatorios faltantes: "
                f"{len(result['missing_required_dates'])} "
                f"· Flujos sin momento: {result['unknown_flow_count']}."
            )
        view = pd.DataFrame(
            [
                {
                    "Fecha": row["date"],
                    "Requisito": "Obligatorio" if row["required"] else "Si el flujo se confirma BOD",
                    "Fecha en CSV": "Aportada" if row["available"] else "Falta",
                    "Motivo": "; ".join(row["reasons"]),
                }
                for row in result["rows"]
            ]
        )
        st.dataframe(view, hide_index=True, width="stretch")
        st.caption(
            "BOD requiere el cierre del día calendario anterior; EOD usa el cierre de la fecha del flujo. "
            "UNKNOWN conserva ambos escenarios pendientes. El plan sólo revisa fechas: no aprueba "
            "saldos, clasificación de flujos, FX ni eventos corporativos."
        )
        st.download_button(
            "Descargar plan de valuaciones",
            view.to_csv(index=False).encode("utf-8-sig"),
            f"plan_valuaciones_{start}_{end}.csv",
            "text/csv",
            key=_key("valuation_calendar_download"),
            on_click="ignore",
        )
        return result


def _ledger(context, *, demo=False):
    status = OperationStatus()
    st.session_state[_key("_ops_status")] = status
    # Rebuild the reference from current inputs before another tab may use it.
    st.session_state.pop(_key("_ops_last_book"), None)
    st.header("Movimientos y rendimiento histórico")
    st.caption("Títulos a fecha de operación, efectivo a liquidación y pendientes separados. MXN y USD.")
    if not demo:
        new_review()
        open_review(context)
        render_movement_import(context)
        from operations_review_ui import movement_draft

        if movement_draft():
            for document in movement_draft()["documents"]:
                status.documents.append(
                    {
                        "name": "Estado GBM · " + document["end"],
                        "sha256": document["sha256"],
                        "differences": [],
                        "notice": " ".join(document["warnings"])
                        or "Cotejo de procedencia y aprobación independiente pendientes.",
                    }
                )
    _template("Plantilla de libro normalizado", COLUMNS, "ledger_template")
    with st.expander("Cómo registrar reportos"):
        st.write(
            "OPEN_REPO registra el capital inicial sin mover efectivo; REPO_START invierte capital; "
            "REPO_MATURITY cobra el bruto, con Interes ya incluido. Usa una referencia única por reporto."
        )
    source = _status_upload("Libro normalizado de movimientos", "ledger", key="ops_ledger")
    if not source:
        _forget_book_reference()
        st.info(
            "Importa el libro para revisar saldos y flujos. "
            "Las compras, ventas y dividendos son movimientos internos."
        )
        return
    events = _cached_calculation("Libro de movimientos", read_ledger, source.getvalue())
    defaults = review_defaults()
    cutoff = st.date_input(
        "Cierre del libro",
        value=date.fromisoformat(defaults["cutoff"]) if defaults else date.today(),
        max_value=date.today(),
        key=review_key("ops_cutoff"),
    )
    files = {"ledger": source}
    book = _cached_calculation("Cierre del libro", book_at, events, cutoff)
    status.cutoff, status.book = cutoff.isoformat(), book
    _remember_book(book, cutoff, source.getvalue())
    ledger_view = pd.DataFrame([asdict(event) for event in events]).rename(
        columns={
            "id": "ID",
            "day": "Operación",
            "settled": "Liquidación",
            "kind": "Tipo",
            "asset": "Instrumento",
            "currency": "Moneda",
            "quantity": "Cantidad",
            "price": "Precio",
            "amount": "Importe bruto",
            "fee": "Comisión",
            "tax": "Impuesto",
            "reference": "Referencia",
            "timing": "Momento del flujo",
            "interest": "Interés incluido en bruto",
        }
    )
    st.dataframe(
        ledger_view.style.format(
            {
                "Cantidad": "{:,.6g}",
                "Precio": "{:,.6f}",
                "Importe bruto": "{:,.2f}",
                "Comisión": "{:,.2f}",
                "Impuesto": "{:,.2f}",
                "Interés incluido en bruto": "{:,.2f}",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    repo_file = None
    if book["repos"]:
        st.write("**Reportos vigentes**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Referencia": ref, "Moneda": currency, "Capital": amount}
                    for (ref, currency), amount in book["repos"].items()
                ]
            )
            .style.format({"Capital": "{:,.2f}"})
            .set_properties(subset=["Capital"], **{"text-align": "right"}),
            hide_index=True,
            width="stretch",
        )
        _template("Plantilla de valuación de reportos", REPO_VALUE_COLUMNS, "repo_values_template")
        repo_file = _status_upload(
            "Valuación de reportos al cierre: Fecha,Referencia,Moneda,Valor,Fuente",
            "repo_values",
            key="ops_repo_values",
        )
        complete_input("repo_values", repo_file, day=cutoff)
        if not repo_file:
            st.info(
                "Valuación pendiente: carga el valor total documentado de cada reporto al cierre, "
                "incluidos los intereses devengados que correspondan. El capital no sustituye esa valuación."
            )
    repo_values = (
        _checked_input("Valuación de reportos", read_repo_values, repo_file.getvalue(), cutoff)
        if repo_file
        else None
    )
    st.write("**Efectivo liquidado y pendientes**")
    st.dataframe(
        pd.DataFrame(
            [
                {"Moneda": c, "Liquidado": book["cash"].get(c, 0), "Pendiente": book["pending"].get(c, 0)}
                for c in sorted(set(book["cash"]) | set(book["pending"]))
            ]
        ).style.format({"Liquidado": "{:,.2f}", "Pendiente": "{:,.2f}"}),
        hide_index=True,
    )
    files["repo_values"] = repo_file
    reconciliation = _closing_reconciliation(context, book, cutoff, source.getvalue(), files)
    status.reconciliation = reconciliation
    quotes_file = _status_upload(
        "Cotizaciones de cierre: Fecha,Instrumento,Moneda,Precio", "quotes", key="ops_raw"
    )
    fx_file = _status_upload("FX del cierre: Fecha,Moneda,Base,Tasa,Fuente", "fx", key="ops_book_fx")
    if not demo:
        complete_input("quotes", quotes_file, day=cutoff)
        complete_input("fx", fx_file, day=cutoff)
    base = st.selectbox(
        "Moneda del rendimiento y valuación",
        ["MXN", "USD"],
        index=1 if defaults.get("base") == "USD" else 0,
        key=review_key("ops_base"),
    )
    files.update(quotes=quotes_file, fx=fx_file)
    status.base = base
    reset_confirmation(
        "raw_confirmation",
        [
            source.getvalue(),
            cutoff,
            base,
            *(file.getvalue() if file else b"" for file in (repo_file, quotes_file, fx_file)),
        ],
    )
    raw_confirmed = st.checkbox(
        "Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre",
        key=review_key("raw_confirmation"),
    )
    status.raw_confirmed = raw_confirmed
    if (quotes_file or not book["positions"]) and raw_confirmed and (not book["repos"] or repo_file):
        quotes = (
            _checked_input("Cotizaciones de cierre", _csv, quotes_file)
            if quotes_file
            else pd.DataFrame(columns=["Fecha", "Instrumento", "Moneda", "Precio"])
        )
        if not {"Fecha", "Instrumento", "Moneda", "Precio"}.issubset(quotes):
            raise PortfolioError("Las cotizaciones requieren fecha, instrumento, moneda y precio.")
        if (
            quotes["Fecha"].astype(str).ne(cutoff.isoformat()).any()
            or quotes.duplicated(["Instrumento", "Moneda"]).any()
        ):
            raise PortfolioError("Las cotizaciones deben ser únicas y corresponder al cierre elegido.")
        quote_map = {(row["Instrumento"], row["Moneda"]): row["Precio"] for row in quotes.to_dict("records")}
        fx = _checked_input("FX del cierre", _csv, fx_file) if fx_file else pd.DataFrame()
        if not fx.empty:
            # Reuse exact-cut validation, including source and duplicate-rate rejection.
            currencies = sorted(
                set(book["cash"])
                | {c for _, c in book["positions"]}
                | set(book["pending"])
                | {c for _, c in book["repos"]}
            )
            dummy = pd.DataFrame(
                [
                    {
                        "Fecha": cutoff.isoformat(),
                        "Cuenta": "local",
                        "Instrumento": c,
                        "Moneda": c,
                        "Valor": 1,
                        "EmisorID": "",
                    }
                    for c in currencies
                ]
            )
            _checked_input("FX del cierre", consolidate_wealth, dummy, fx, cutoff=cutoff, base=base)
        rates = {(row["Moneda"], row["Base"]): row["Tasa"] for row in fx.to_dict("records")}
        valued = _checked_input(
            "Valuación al cierre",
            value_book,
            book,
            quote_map,
            rates,
            base=base,
            raw_prices_confirmed=True,
            repo_values=repo_values,
        )
        status.valuation = valued
        st.metric(f"Patrimonio neto al cierre · {base}", f"{valued['nav']:,.2f}")
        st.dataframe(
            pd.DataFrame(valued["detail"]).style.format(
                {"ValorOrigen": "{:,.2f}", "FX": "{:,.6g}", "ValorBase": "{:,.2f}"}
            ),
            hide_index=True,
            width="stretch",
        )
    nav_file = _status_upload("Valuaciones históricas verificadas: Fecha,NAV", "nav", key="ops_nav")
    if not demo:
        complete_input("nav", nav_file, day=cutoff)
    nav = None
    if nav_file:
        nav = _checked_input("Valuaciones históricas", _read_nav, nav_file)
        start, end = nav.index[0].date(), nav.index[-1].date()
    else:
        start = min((event.day for event in events if event.day <= cutoff), default=cutoff)
        end = cutoff
    period_events = [
        event for event in events if event.kind in EXTERNAL_EVENT_KINDS and start < event.settled <= end
    ]
    status.events = period_events
    status.calendar = _valuation_calendar(
        start,
        end,
        [Flow(event.settled, _native_flow_amount(event), event.timing) for event in period_events],
        available_dates=nav.index if nav is not None else (),
    )
    with st.expander(
        "Revisión de flujos y resultado",
        expanded=bool(status.calendar and status.calendar["twr_coverage_ready"])
        or st.session_state.get(_key("_ops_focus_step")) == "flows",
    ):
        st.caption(
            "Revisa los flujos externos, sus importes, moneda y fuentes del periodo. "
            "Tener las fechas completas no confirma esos datos. "
            "Cambiar un archivo exige renovar esta confirmación."
        )
        flow_fx_file = _status_upload(
            "FX por fecha de cada flujo: Fecha,Moneda,Base,Tasa,Fuente", "flow_fx", key="ops_flow_fx"
        )
        if not demo:
            complete_input("flow_fx", flow_fx_file, day=cutoff)
        files.update(nav=nav_file, flow_fx=flow_fx_file)
        reset_confirmation(
            "flows_confirmation",
            [
                cutoff,
                base,
                *(file.getvalue() if file else b"" for file in files.values()),
            ],
        )
        verified = st.checkbox(
            "Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida",
            key=review_key("flows_confirmation"),
        )
        status.flows_confirmed = verified
        flows = []
        if nav_file and verified:
            fx_frame = (
                _checked_input("FX de los flujos", _csv, flow_fx_file) if flow_fx_file else pd.DataFrame()
            )
            flows = []
            for event in period_events:
                amount = _native_flow_amount(event)
                if event.currency != base:
                    needed = {"Fecha", "Moneda", "Base", "Tasa", "Fuente"}
                    if not needed.issubset(fx_frame):
                        raise PortfolioError("Falta FX fechado para convertir los flujos externos.")
                    match = fx_frame[
                        (fx_frame["Fecha"] == event.settled.isoformat())
                        & (fx_frame["Moneda"] == event.currency)
                        & (fx_frame["Base"] == base)
                    ]
                    if (
                        len(match) != 1
                        or not str(match.iloc[0]["Fuente"]).strip()
                        or float(match.iloc[0]["Tasa"]) <= 0
                    ):
                        raise PortfolioError("Un flujo no tiene un único FX positivo y documentado.")
                    amount *= float(match.iloc[0]["Tasa"])
                flows.append(Flow(event.settled, amount, event.timing))
            result = _cached_calculation("Rendimiento histórico", performance, nav, flows)
            status.returns = result
            status.performance_summary = explain_performance(events, nav, result, flows, base=base)
            display_rows = summary_lines(status.performance_summary)
            a, b, c = st.columns(3)
            a.metric("Ganancia separada de flujos", display_rows[4][1])
            b.metric("TWR del periodo", display_rows[9][1])
            c.metric("XIRR anualizada", display_rows[10][1])
            st.caption(
                f"TWR: {result['twr_status']} · XIRR: {result['xirr_status']}. "
                "TWR requiere valuación en cada flujo y momento BOD/EOD confirmado."
            )
            _save_evidence(
                context,
                "Conservar libro y cálculo de rendimiento",
                {
                    "schema": 1,
                    "result": result,
                    "base": base,
                    "flows": [asdict(f) for f in flows],
                    "ledger": base64.b64encode(source.getvalue()).decode(),
                    "valuations": base64.b64encode(nav_file.getvalue()).decode(),
                    "flow_fx": base64.b64encode(flow_fx_file.getvalue()).decode() if flow_fx_file else None,
                    "repo_values": base64.b64encode(repo_file.getvalue()).decode() if repo_file else None,
                    "closing_reconciliation": reconciliation,
                },
            )
        if status.performance_summary is None:
            status.performance_summary = explain_performance(events, nav, status.returns, flows, base=base)
    if not demo:
        _checked_input("Paquete de movimientos", download_review, context, files, cutoff=cutoff, base=base)
        return True


def _implementation(context):
    st.header("Propuesta por títulos y lotes")
    st.caption(
        "Minimiza desvío del objetivo y costos sujetos a efectivo, lotes, concentración y rotación. "
        "Comprueba precios, lotes y tarifas con tu intermediario antes de usar una propuesta."
    )
    recovery = recovered_proposal()
    defaults = recovery["inputs"] if recovery else {}
    default_tariff = defaults.get("tariff", {})
    if recovery:
        st.caption("Propuesta recuperada. Revisa sus datos y vuelve a confirmar para recalcular.")
    prepared = prepare_book_proposal()
    origin = st.radio(
        "Origen de la propuesta",
        ["CSV manual", "Libro de movimientos"],
        index=1 if defaults.get("origin") == "Libro de movimientos" else 0,
        key=proposal_key("proposal_origin"),
    )
    using_book = origin == "Libro de movimientos" and prepared is not None
    _template(
        "Plantilla de posiciones y objetivo",
        ["Instrumento", "Cantidad", "Precio", "Lote", "PesoObjetivo"],
        "execution_template",
    )
    upload = st.file_uploader(
        "Posiciones, cotizaciones sin ajuste y pesos objetivo", ["csv"], key=proposal_key("ops_execution")
    )
    source_raw = (
        prepared["positions"].to_csv(index=False).encode()
        if using_book
        else upload.getvalue()
        if origin == "CSV manual" and upload
        else base64.b64decode(recovery["inputs"]["csv"])
        if origin == "CSV manual" and recovery
        else b""
    )
    recovered_target = (
        recovery["inputs"]["target"] if recovery and origin == "CSV manual" and not upload else None
    )
    if recovery and using_book and defaults.get("book_origin"):
        origin_book = defaults["book_origin"]
        if all(prepared[key] == origin_book[key] for key in ("ledger_sha256", "cutoff", "currency")):
            if list(prepared["positions"]["Instrumento"]) == [
                q["Instrumento"] for q in origin_book["quotes"]
            ]:
                recovered_target = defaults["target"]
    if recovered_target is not None:
        st.caption(
            "Insumos y pesos efectivos recuperados. "
            "Revisa las fuentes y confirma de nuevo antes de recalcular."
        )
    if using_book:
        cash = float(prepared["cash"])
        currency = prepared["currency"]
        quote_day = date.fromisoformat(prepared["cutoff"])
        quote_source = "Fuentes documentadas por instrumento en el libro preparado"
        st.write(f"Efectivo liquidado del libro: **{cash:,.2f} {currency}** · Corte: {quote_day}")
        st.caption("Libro de origen · SHA-256 " + prepared["ledger_sha256"])
        status = st.session_state.get(_key("_ops_status"))
        if status is not None:
            pending_count = status.snapshot("Libro de origen de la propuesta")["issue_count"]
            st.caption(f"Pendientes del libro: {pending_count}. La propuesta conserva esa revisión abierta.")
    else:
        if origin == "Libro de movimientos":
            st.info("Prepara primero las posiciones y sus fuentes en Preparar desde el libro de movimientos.")
        cash = st.number_input(
            "Efectivo disponible para operar",
            min_value=0.0,
            value=float(defaults.get("cash", 0)),
            key=proposal_key("proposal_cash"),
        )
        currency = st.selectbox(
            "Moneda de las órdenes",
            ["MXN", "USD"],
            index=1 if defaults.get("currency") == "USD" else 0,
            key=proposal_key("proposal_currency"),
        )
        quote_day = st.date_input(
            "Fecha de cotización de las órdenes",
            date.fromisoformat(defaults["date"]) if defaults else date.today(),
            max_value=date.today(),
            key=proposal_key("proposal_date"),
        )
        quote_source = st.text_input(
            "Fuente de cotizaciones y lotes",
            value=defaults.get("quote_source", ""),
            key=proposal_key("proposal_quote_source"),
        )
    floor = st.number_input(
        "Efectivo mínimo que deseas conservar",
        min_value=0.0,
        value=float(defaults.get("cash_floor", 0)),
        key=proposal_key("proposal_floor"),
    )
    commission = st.number_input(
        "Comisión · puntos base por operación",
        0.0,
        500.0,
        float(default_tariff.get("commission_bps", 0)),
        key=proposal_key("proposal_commission"),
    )
    minimum = st.number_input(
        "Comisión mínima por orden",
        0.0,
        100000.0,
        float(default_tariff.get("minimum_commission", 0)),
        key=proposal_key("proposal_minimum"),
    )
    market = st.number_input(
        "Costo de mercado · puntos base",
        0.0,
        500.0,
        float(default_tariff.get("market_cost_bps", 0)),
        key=proposal_key("proposal_market"),
    )
    vat = (
        st.number_input(
            "IVA sobre comisión · %",
            0.0,
            100.0,
            float(default_tariff.get("vat_rate", 0)) * 100,
            key=proposal_key("proposal_vat"),
        )
        / 100
    )
    tariff_source = st.text_input(
        "Fuente y vigencia de las tarifas aplicables",
        value=defaults.get("tariff_source", ""),
        key=proposal_key("proposal_tariff_source"),
    )
    flow = st.session_state.get("_account_flow", {})
    completed = flow.get("completed")
    binding = (
        str(context[0].path) if context[0] else None,
        context[1].actor if context[1] else None,
        context[2]["id"] if context[2] else None,
        context[3],
    )
    strategy = None
    analysis_model = None
    analysis_notice = "Abre un análisis calculado de esta misma cuenta, corte, moneda y universo."
    selected_name = flow.get("selected_alternative", "Mínima volatilidad")
    names = [a.name for a in completed["result"]["alternatives"]] if completed else []
    if names and selected_name not in names:
        selected_name = names[0]
    target_origin = st.radio(
        "Pesos objetivo",
        (["Pesos guardados"] if recovery else [])
        + ["Pesos del insumo", "Alternativa del análisis de cuenta"],
        key=proposal_key("target_origin"),
    )
    saved_target_available = recovered_target is not None
    if target_origin != "Pesos guardados":
        recovered_target = None
    if target_origin == "Alternativa del análisis de cuenta" and names:
        selected_name = st.selectbox(
            "Alternativa objetivo del análisis",
            names,
            index=names.index(selected_name),
            key=proposal_key("target_alternative"),
        )
    if completed and source_raw:
        try:
            assets = tuple(_csv(BytesIO(source_raw))["Instrumento"])
            reviewed_strategy = strategy_from_analysis(
                flow, binding, assets, quote_day, currency, selected_name
            )
            analysis_model = completed["result"]["model"]
            if target_origin == "Alternativa del análisis de cuenta":
                strategy = reviewed_strategy
        except (PortfolioError, ValueError, KeyError, TypeError):
            pass
    if target_origin == "Alternativa del análisis de cuenta":
        if strategy:
            st.caption(
                f"Estrategia: {strategy['name']} · ejecución {strategy['run_id'][:12]} · "
                f"historia {strategy['sample_start']} a {strategy['sample_end']}."
            )
            st.caption(
                "Sus pesos objetivo se aplican al capital total disponible, incluido el efectivo. "
                "La referencia Conservar de la comparación mantiene los títulos sin operar."
            )
            st.dataframe(
                pd.DataFrame({"Instrumento": strategy["assets"], "Peso objetivo": strategy["weights"]}),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info(analysis_notice)
    elif target_origin == "Pesos guardados":
        if defaults.get("strategy") and recovered_target is not None:
            try:
                strategy = validate_strategy(
                    defaults["strategy"],
                    tuple(_csv(BytesIO(source_raw))["Instrumento"]),
                    quote_day,
                    currency,
                    recovered_target,
                )
            except (PortfolioError, ValueError, KeyError, TypeError):
                saved_target_available = False
            else:
                st.caption(
                    f"Procedencia guardada: {strategy['name']} · ejecución {strategy['run_id'][:12]}. "
                    "Los pesos se recuperan para revisión; el riesgo necesita el análisis de cuenta."
                )
        if not saved_target_available:
            st.info(
                "Los pesos guardados no coinciden con estos insumos, corte o moneda. "
                "Revisa los pesos del insumo o elige una alternativa de un análisis compatible."
            )
    fraction = (
        st.slider("Acercamiento del cambio parcial · %", 0, 100, 25, key=proposal_key("comparison_fraction"))
        / 100
    )
    turnover = st.slider(
        "Rotación máxima · suma de compras y ventas / patrimonio",
        0.0,
        2.0,
        float(defaults.get("max_turnover", 0.5)),
        key=proposal_key("proposal_turnover"),
    )
    cap = st.slider(
        "Concentración máxima por activo sobre capital inicial",
        0.01,
        1.0,
        float(defaults.get("max_weight", 1)),
        key=proposal_key("proposal_cap"),
    )
    min_trade = st.number_input(
        "Importe mínimo por orden",
        0.0,
        value=float(defaults.get("minimum_trade", 0)),
        key=proposal_key("proposal_min_trade"),
    )
    if target_origin == "Alternativa del análisis de cuenta":
        st.session_state[proposal_key("proposal_optimize")] = False
    optimize = st.checkbox(
        "Usar modelo de costos y riesgo del análisis de cuenta abierto en esta sesión",
        key=proposal_key("proposal_optimize"),
        disabled=target_origin == "Alternativa del análisis de cuenta",
    )
    model_signature = None
    if analysis_model is not None:
        moments = completed["result"]["model"].moments
        model_signature = analysis_key(
            completed["settings"], moments.mean, moments.covariance, flow.get("context"), completed["run_id"]
        )
    inputs = {
        "currency": currency,
        "date": str(quote_day),
        "quote_source": quote_source,
        "tariff_source": tariff_source,
        "tariff": asdict(ImplementationCostAssumptions(commission, market, vat, minimum)),
        "cash": cash,
        "cash_floor": floor,
        "max_turnover": turnover,
        "max_weight": cap,
        "minimum_trade": min_trade,
        "origin": origin,
        "optimize": optimize,
        "book_origin": {key: value for key, value in prepared.items() if key != "positions"}
        if using_book
        else None,
    }
    if strategy and not optimize:
        inputs["strategy"] = strategy
    signature = analysis_key(
        review_key("proposal"),
        source_raw,
        inputs,
        model_signature,
        recovered_target,
        fraction,
        Path(__file__).with_name("executable_allocation.py").read_bytes().replace(b"\r\n", b"\n"),
    )
    if st.session_state.get(_key("orders_signature")) != signature:
        st.session_state[proposal_key("orders_confirmation")] = False
        st.session_state[_key("orders_signature")] = signature
    confirmed = st.checkbox(
        "Confirmé precios sin ajuste, títulos, lotes, moneda y tarifas de esta cuenta",
        key=proposal_key("orders_confirmation"),
    )
    can_calculate = bool(
        source_raw
        and confirmed
        and (target_origin != "Alternativa del análisis de cuenta" or strategy is not None)
        and (target_origin != "Pesos guardados" or saved_target_available)
    )
    calculate = st.button("Calcular propuesta de títulos", disabled=not can_calculate)
    compare = st.button("Comparar alternativas con estos insumos", disabled=not can_calculate)
    if calculate or compare:
        if not all(_text(value.lstrip()) for value in (quote_source, tariff_source)):
            raise PortfolioError("Documenta las fuentes de cotizaciones y tarifas.")
        positions = _csv(BytesIO(source_raw))
        if "PesoObjetivo" not in positions:
            raise PortfolioError("Falta el peso objetivo de cada instrumento.")
        target = pd.to_numeric(positions["PesoObjetivo"], errors="raise").to_numpy()
        if recovered_target is not None:
            target = pd.Series(recovered_target).to_numpy(dtype=float)
        if strategy and not optimize:
            target = pd.Series(strategy["weights"]).to_numpy(dtype=float)
        if optimize:
            _, _, state, account = context
            if (
                analysis_model is None
                or currency != "MXN"
                or flow.get("context", (None,) * 4)[2:] != (state["id"] if state else None, account)
            ):
                raise PortfolioError("Abre primero un análisis MXN de esta misma cuenta.")
            assets = tuple(positions["Instrumento"])
            if assets != completed["settings"].assets:
                raise PortfolioError("Los instrumentos y su orden deben coincidir con el análisis de cuenta.")
            moments = completed["result"]["model"].moments
            current = positions["Cantidad"].astype(float) * positions["Precio"].astype(float)
            if current.sum() <= 0:
                raise PortfolioError("El modelo de costos y riesgo requiere una cartera actual con títulos.")
            target = cost_aware_target(
                moments.mean,
                moments.covariance,
                current / current.sum(),
                cost_rate=(commission * (1 + vat) + market) / 10000,
                max_weight=cap,
                max_turnover=turnover,
            )
        assumptions = ImplementationCostAssumptions(commission, market, vat, minimum)
        limits = dict(
            cash_floor=floor,
            max_turnover=turnover,
            max_weight=cap,
            minimum_trade=min_trade,
            quotes_confirmed=confirmed,
        )
        if calculate:
            result = executable_plan(positions, cash, target, assumptions, **limits)
            st.session_state["_execution_proposal"] = {
                "signature": signature,
                "context": (context[2]["id"] if context[2] else None, context[3]),
                "result": result,
                "inputs": {**inputs, "target": target.tolist(), "csv": base64.b64encode(source_raw).decode()},
            }
        if compare:
            current = st.session_state.get("_execution_proposal")
            reusable = (
                current
                if current and current["signature"] == signature and current["context"] == binding[2:]
                else None
            )
            comparison = compare_plans(
                positions, cash, target, assumptions, fraction=fraction, full_plan=reusable, **limits
            )
            st.session_state["_execution_comparison"] = {
                "signature": signature,
                "binding": binding,
                "result": comparison,
                "inputs": {**inputs, "target": target.tolist(), "csv": base64.b64encode(source_raw).decode()},
                "risks": {
                    name: plan_risk(plan, analysis_model) for name, plan in comparison["plans"].items()
                },
            }
    comparison = st.session_state.get("_execution_comparison")
    if comparison and comparison["signature"] == signature and comparison["binding"] == binding and confirmed:
        st.subheader("Conservar, cambio parcial y propuesta")
        table = comparison["result"]["summary"].copy()
        risks = comparison["risks"]
        table["Media anual del modelo"] = [risks[name]["annual_mean"] for name in table["Alternativa"]]
        table["Volatilidad anual"] = [risks[name]["annual_volatility"] for name in table["Alternativa"]]
        table["Riesgo"] = [risks[name]["status"] for name in table["Alternativa"]]
        table["Fecha"] = str(quote_day)
        table["Moneda"] = currency
        table["Fuente de precios"] = quote_source
        table["Fuente de tarifas"] = tariff_source
        table["Fracción parcial"] = comparison["result"]["fraction"]
        table["Cobertura de títulos"] = [risks[name]["coverage"] for name in table["Alternativa"]]
        formats = {k: "{:,.2f}" for k in ("Compras", "Ventas", "Costo", "Efectivo")}
        formats.update(
            {
                k: "{:.2%}"
                for k in ("Rotación", "Media anual del modelo", "Volatilidad anual", "Cobertura de títulos")
            }
        )
        visible = ["Alternativa", "Estado", "Costo", "Efectivo", "Rotación", "Volatilidad anual", "Riesgo"]
        st.dataframe(
            table[visible].style.format(formats, na_rep="Pendiente"), hide_index=True, width="stretch"
        )
        st.caption(
            f"Corte {quote_day} · {currency}. Cambio parcial: {comparison['result']['fraction']:.0%} "
            "de acercamiento en pesos antes de redondear lotes. Conservar no tiene transacciones. "
            "Los cargos recurrentes e impuestos de una venta requieren revisión aparte."
        )
        if analysis_model is not None:
            sample = next(iter(risks.values()))
            st.caption(
                f"Modelo de riesgo: {analysis_model.moments.description} · "
                f"{sample['observations']} retornos · "
                f"{sample['start']} a {sample['end']}. Pesos finales sobre patrimonio después de cargos. "
                "El modelo supone efectivo constante en términos nominales; "
                "no mide riesgo de contraparte, inflación ni FX."
            )
        else:
            st.caption("Riesgo pendiente: " + analysis_notice)
        with st.expander("Títulos finales y cobertura del riesgo"):
            st.dataframe(table.style.format(formats, na_rep="Pendiente"), hide_index=True, width="stretch")
            for name, plan in comparison["result"]["plans"].items():
                st.write("**" + name + "**")
                if plan is not None:
                    st.dataframe(plan["detail"], hide_index=True, width="stretch")
                risk = risks[name]
                if risk["coverage"] is not None:
                    st.caption(
                        f"Cobertura de títulos: {risk['coverage']:.1%} · "
                        f"Efectivo sobre patrimonio final: {risk['cash_weight']:.1%}."
                    )
                else:
                    st.caption("Cobertura del riesgo pendiente de análisis compatible.")
        st.download_button(
            "Descargar comparación CSV",
            table.to_csv(index=False).encode(),
            "comparacion_titulos.csv",
            "text/csv",
            on_click="ignore",
        )
        st.caption(
            "El ZIP conserva la propuesta y su procedencia. La comparación CSV se descarga por separado. "
            "Para evaluar riesgo al retomar, abre también el análisis de cuenta."
        )
    proposal = st.session_state.get("_execution_proposal")
    binding = (context[2]["id"] if context[2] else None, context[3])
    if proposal and proposal["context"] == binding and proposal.get("signature") == signature and confirmed:
        result = proposal["result"]
        formats = {column: "{:,.2f}" for column in ("Importe firmado", "Comisión e IVA", "Costo de mercado")}
        formats.update({column: "{:.2%}" for column in ("PesoObjetivo", "Peso final sobre capital inicial")})
        formats.update({column: "{:,.6g}" for column in ("Cantidad", "Lote", "Títulos finales")})
        formats["Títulos a operar"] = lambda value: "0" if value == 0 else f"{value:+,.6g}"
        main_columns = [
            "Instrumento",
            "Títulos a operar",
            "Títulos finales",
            "Comisión e IVA",
            "Importe firmado",
        ]
        st.dataframe(result["detail"][main_columns].style.format(formats), hide_index=True, width="stretch")
        with st.expander("Detalle de precios, lotes y pesos"):
            st.dataframe(result["detail"].style.format(formats), hide_index=True, width="stretch")
        st.write(
            f"Efectivo final **{result['cash']:,.2f} {proposal['inputs']['currency']}** · "
            f"costo **{result['cost']:,.2f}** · rotación **{result['turnover']:.2%}**"
        )
        st.caption(
            result["basis"]
            + (" Solución óptima." if result["optimal"] else " Solución factible con límite de tiempo.")
        )
        st.download_button(
            "Descargar propuesta CSV",
            result["detail"].to_csv(index=False).encode(),
            "propuesta_titulos.csv",
            "text/csv",
            on_click="ignore",
        )
        st.download_button(
            "Descargar insumos de propuesta CSV",
            source_raw,
            "insumos_propuesta_titulos.csv",
            "text/csv",
            key=proposal_key("proposal_inputs_download"),
            on_click="ignore",
        )
        portable = portable_proposal(proposal)
        status = st.session_state.get(_key("_ops_status"))
        snapshot = status.snapshot("Libro de origen") if using_book and status else None
        if st.button("Preparar PDF de la propuesta", key=proposal_key("proposal_pdf_prepare")):
            st.session_state[_key("proposal_pdf")] = {
                "signature": analysis_key(portable, snapshot),
                "bytes": proposal_pdf(portable, snapshot),
            }
        pdf = st.session_state.get(_key("proposal_pdf"))
        if pdf and pdf["signature"] == analysis_key(portable, snapshot):
            st.download_button(
                "Descargar PDF de la propuesta",
                pdf["bytes"],
                "propuesta_cartera.pdf",
                "application/pdf",
                on_click="ignore",
            )
        download_review(context, {}, cutoff=quote_day, base=currency, suffix="_proposal", proposal=portable)
        _save_evidence(
            context,
            "Conservar propuesta e insumos",
            {
                "inputs": proposal["inputs"],
                "result": {**result, "detail": result["detail"].to_dict("records")},
            },
        )


def _feeds(context):
    st.header("Fuentes aprobadas y alertas")
    store, principal, state, account = context
    catalogue_file = st.file_uploader(
        "Catálogo de instrumentos e identidades de emisor", ["csv"], key=_key("ops_catalogue")
    )
    if catalogue_file:
        from instrument_catalogue import read_catalogue

        catalogue = read_catalogue(catalogue_file.getvalue())
        st.dataframe(catalogue, hide_index=True, width="stretch")
        flow = st.session_state.get("_account_flow", {})
        binding = (state["id"] if state else None, account)
        if flow.get("context", (None,) * 4)[2:] == binding and flow.get("files", {}).get("holdings"):
            if st.button("Aplicar clasificación a la preparación de esta cuenta"):
                assets = flow["defaults"].get("assets", ())
                subset = catalogue[catalogue["Instrumento"].isin(assets)]
                if len(subset) != len(assets):
                    raise PortfolioError(
                        "El catálogo debe cubrir todos los instrumentos del análisis abierto."
                    )
                for row in subset.to_dict("records"):
                    flow["metadata"][row["Instrumento"]] = {
                        key: row[key]
                        for key in (
                            "Tipo",
                            "Emisor",
                            "EmisorID",
                            "Sector",
                            "Pais",
                            "Moneda",
                            "Fecha",
                            "Fuente",
                        )
                    }
                flow["files"]["catalogue"] = catalogue_file.getvalue()
                flow["token"] = uuid4().hex
                st.success("Clasificación aplicada. Recalcula la cuenta para actualizar sus resultados.")
    if not store or not state or not account:
        st.info("Selecciona expediente y cuenta con almacenamiento persistente para programar revisiones.")
        return
    try:
        config = st.secrets.get("operations", {})
    except FileNotFoundError:
        config = {}
    sources = config.get("sources", {})
    if not sources:
        st.info("Administración debe registrar fuentes aprobadas y su vigencia de uso antes de programarlas.")
    else:
        source = st.selectbox("Fuente aprobada", list(sources))
        rows = store.working_records(principal, state["id"], account, "subscription")
        prior = next((row for row in rows if row["name"] == source), None)
        monitor = prior["data"].get("monitor") if prior else None
        last_book = st.session_state.get(_key("_ops_last_book"))
        flow = st.session_state.get("_account_flow", {})
        completed = flow.get("completed")
        if last_book and completed and flow.get("context", (None,) * 4)[2:] == (state["id"], account):
            checked = st.checkbox(
                "Confirmé que las cantidades del libro siguen vigentes para vigilar desvíos",
                key=_key("monitor_confirmation"),
            )
            if checked:
                book = last_book["book"]
                assets = completed["settings"].assets
                if {currency for _, currency in book["positions"]} != {"MXN"} or {
                    asset for asset, _ in book["positions"]
                } != set(assets):
                    raise PortfolioError("El seguimiento necesita los mismos instrumentos MXN del análisis.")
                if any(book["pending"].values()):
                    raise PortfolioError(
                        "Revisa la liquidación pendiente antes de fijar cantidades de seguimiento."
                    )
                reference_name = completed["settings"].tracking_reference
                reference = next(
                    item for item in completed["result"]["alternatives"] if item.name == reference_name
                )
                monitor = {
                    "quantities": {asset: str(book["positions"][(asset, "MXN")]) for asset in assets},
                    "weights": dict(zip(assets, reference.metrics.weights.tolist(), strict=True)),
                    "currency": "MXN",
                    "as_of": last_book["cutoff"],
                    "tolerance": completed["settings"].drift_tolerance,
                }
                st.caption(
                    "El seguimiento compara pesos invertidos sin efectivo. "
                    "Actualiza las cantidades confirmadas después de operar."
                )
        enabled = st.checkbox(
            "Revisar esta fuente periódicamente", value=bool(prior and prior["data"].get("enabled"))
        )
        age = st.number_input(
            "Antigüedad máxima de datos · días",
            0,
            366,
            int(prior["data"].get("max_age_days", 7)) if prior else 7,
        )
        interval = st.number_input("Intervalo de revisión · minutos", 15, 10080, 60)
        notify = st.checkbox("Avisar también cuando cambie el contenido aprobado")
        if st.button("Guardar programación", disabled=principal.role not in {"ADMIN", "ANALYST"}):
            store.save_working(
                principal,
                state["id"],
                account,
                "subscription",
                source,
                {
                    "enabled": enabled,
                    "source_id": source,
                    "interval_minutes": interval,
                    "max_age_days": age,
                    "notify_updates": notify,
                    "monitor": monitor,
                },
                expected_version=prior["version"] if prior else 0,
            )
            st.rerun()
        if prior and st.button("Revisar ahora", disabled=principal.role not in {"ADMIN", "ANALYST"}):
            refresh_subscription(store, principal, state["id"], account, prior, sources, force=True)
            st.rerun()
        if config.get("enabled") is not True:
            st.caption("El servicio periódico está desactivado. La revisión manual sigue disponible.")
    caches = store.working_records(principal, state["id"], account, "feed")
    if caches:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Fuente": row["name"],
                        **{
                            key: row["data"].get(key, "Pendiente")
                            for key in ("status", "age_days", "stale", "last_attempt")
                        },
                    }
                    for row in caches
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        chosen = st.selectbox("Datos conservados para revisar", [row["name"] for row in caches])
        row = next(item for item in caches if item["name"] == chosen)
        if row["data"].get("bytes"):
            st.download_button(
                "Descargar última fuente válida",
                base64.b64decode(row["data"]["bytes"]),
                "fuente_para_revision.csv",
                "text/csv",
                on_click="ignore",
            )
    for row in store.working_records(principal, state["id"], account, "alert"):
        st.info(f"{row['updated'][:19]} UTC · {row['data']['source_id']} · {row['data']['message']}")


def _wealth(context):
    st.header("Patrimonio entre cuentas MXN y USD")
    cutoff = st.date_input("Corte común del patrimonio", date.today(), max_value=date.today())
    base = st.selectbox("Moneda base del patrimonio", ["MXN", "USD"])
    _template(
        "Plantilla de patrimonio",
        ["Fecha", "Cuenta", "Instrumento", "Moneda", "Valor", "EmisorID"],
        "wealth_template",
    )
    _, _, state, _ = context
    if state:
        st.caption("Usa los identificadores de las cuentas de este expediente en la columna Cuenta.")
        st.dataframe(pd.DataFrame(state["accounts"])[["id", "portfolio", "currency"]], hide_index=True)
    source = st.file_uploader(
        "Posiciones, efectivo y pendientes de todas las cuentas", ["csv"], key=_key("ops_wealth")
    )
    fx_file = st.file_uploader("Tipos de cambio documentados del corte", ["csv"], key=_key("ops_wealth_fx"))
    if source:
        result = consolidate_wealth(
            _csv(source),
            _csv(fx_file) if fx_file else pd.DataFrame(),
            cutoff=cutoff,
            base=base,
            allowed_accounts={a["id"] for a in state["accounts"]} if state else None,
        )
        st.metric(f"Patrimonio neto · {base}", f"{result['nav']:,.2f}")
        st.dataframe(result["detail"], hide_index=True, width="stretch")
        st.caption(f"Cobertura por identidad de emisor: {result['identity_coverage']:.1%}.")
        st.bar_chart(result["accounts"], color="#1d5fbf")
        _save_evidence(
            context,
            "Conservar patrimonio y tipos de cambio",
            {
                "cutoff": cutoff.isoformat(),
                "base": base,
                "nav": result["nav"],
                "positions": base64.b64encode(source.getvalue()).decode(),
                "fx": base64.b64encode(fx_file.getvalue()).decode() if fx_file else None,
            },
        )
    legs_file = st.file_uploader(
        "Pares de transferencias: Fecha,Cuenta,Tipo,Moneda,Importe,Referencia",
        ["csv"],
        key=_key("ops_transfers"),
    )
    if legs_file:
        legs = _csv(legs_file)
        if state and (
            "Cuenta" not in legs or not set(legs["Cuenta"]).issubset({a["id"] for a in state["accounts"]})
        ):
            raise PortfolioError("Las transferencias deben pertenecer a cuentas de este expediente.")
        st.dataframe(match_internal_flows(legs), hide_index=True, width="stretch")
        st.caption(
            "Sólo los pares verificados se excluyen de flujos externos. "
            "El patrimonio no se reduce por transferir."
        )
    with st.expander("Rendimiento histórico del patrimonio"):
        navs = st.file_uploader(
            "Cierres por cuenta: Fecha,Cuenta,Moneda,NAV", ["csv"], key=_key("ops_multi_nav")
        )
        rates = st.file_uploader(
            "FX de cada cierre: Fecha,Moneda,Base,Tasa,Fuente", ["csv"], key=_key("ops_multi_fx")
        )
        movements = st.file_uploader(
            "Flujos: Fecha,Cuenta,Tipo,Moneda,Importe,Referencia,MomentoFlujo,FXBase,FuenteFX",
            ["csv"],
            key=_key("ops_multi_flows"),
        )
        confirmed = st.checkbox(
            "Concilié los cierres y todos los flujos del patrimonio, con FX al momento de cada flujo",
            key=_key("multi_confirmation"),
        )
        if navs and movements and confirmed:
            result = consolidated_performance(
                _csv(navs),
                _csv(rates) if rates else pd.DataFrame(),
                _csv(movements),
                base=base,
                allowed_accounts={a["id"] for a in state["accounts"]} if state else None,
            )
            historical = result["performance"]
            st.write(f"Ganancia separada de flujos: **{historical['gain']:,.2f} {base}**")
            st.write("TWR: " + (f"{historical['twr']:.2%}" if historical["twr"] is not None else "Pendiente"))
            st.write(
                "XIRR anualizada: "
                + (f"{historical['xirr']:.2%}" if historical["xirr"] is not None else "Pendiente")
            )
            st.line_chart(result["valuations"], color="#1d5fbf")
            st.caption(
                "Se exige el mismo calendario de cierres para todas las cuentas. "
                "Las transferencias sin pareja verificada bloquean el cálculo."
            )
            _save_evidence(
                context,
                "Conservar rendimiento del patrimonio",
                {
                    "result": historical,
                    "base": base,
                    "valuations": base64.b64encode(navs.getvalue()).decode(),
                    "flows": base64.b64encode(movements.getvalue()).decode(),
                    "fx": base64.b64encode(rates.getvalue()).decode() if rates else None,
                },
            )


def _documents(context):
    st.header("Revisión de originales GBM")
    files = st.file_uploader(
        "Estados PDF y comprobantes CFDI XML",
        ["pdf", "xml"],
        accept_multiple_files=True,
        key=_key("ops_docs"),
    )
    if not files:
        st.info(
            "Cada documento conserva huella y procedencia. "
            "Los comprobantes no generan cargos automáticamente."
        )
    for file in files:
        with st.expander(file.name):
            raw = file.getvalue()
            if file.name.lower().endswith(".pdf"):
                draft = session_compute(
                    st.session_state,
                    "gbm_pdf",
                    analysis_key(raw, code_fingerprint()),
                    lambda raw=raw: read_statement(raw),
                )
                status = st.session_state.get(_key("_ops_status"))
                if status is not None:
                    status.documents.append(
                        {
                            "name": file.name,
                            "sha256": draft["sha256"],
                            "differences": [
                                row
                                for row in draft["cash_review"][1:]
                                if row["ControlAritmetico"] != "EXACTO"
                            ],
                            "notice": "Confirma cuenta, moneda, periodo y clasificación contra el original. "
                            "Las filas exactas también conservan revisión humana pendiente.",
                        }
                    )
                st.caption(
                    f"Corte {draft['end']} · {len(draft['positions'])} posiciones · "
                    f"huella {draft['sha256'][:12]}"
                )
                st.dataframe(pd.DataFrame(draft["positions"]), hide_index=True, width="stretch")
                review = pd.DataFrame(draft["cash_review"])
                st.write("**Conciliación del efectivo por fila**")
                controls = review["ControlAritmetico"].value_counts()
                st.caption(
                    f"{controls.get('EXACTO', 0)} transiciones exactas · "
                    f"{controls.get('DIFERENCIA_CENTAVO', 0)} con diferencia de un centavo · "
                    f"{controls.get('DIFERENCIA_MAYOR', 0)} con diferencia mayor. "
                    f"Saldo inicial cotejado con la portada: {float(review.iloc[0]['SaldoImpreso']):,.2f}."
                )
                money = ("NetoImpreso", "SaldoAnteriorImpreso", "SaldoEsperado", "SaldoImpreso", "Diferencia")
                display = review.iloc[1:][
                    ["Pagina", "Fila", "Sentido", *money, "ControlAritmetico", "EstadoRevision"]
                ].copy()
                for column in money:
                    display[column] = pd.to_numeric(display[column])
                display["ControlAritmetico"] = display["ControlAritmetico"].replace(
                    {
                        "EXACTO": "Cuadra",
                        "DIFERENCIA_CENTAVO": "Difiere un centavo",
                        "DIFERENCIA_MAYOR": "Diferencia mayor",
                    }
                )
                display["EstadoRevision"] = "Pendiente"
                display["Sentido"] = display["Sentido"].str.capitalize()
                st.dataframe(
                    display.style.format({column: "{:,.2f}" for column in money}, na_rep="—"),
                    column_config={
                        "Pagina": "Página",
                        "Sentido": "Movimiento",
                        "NetoImpreso": "Neto · MXN",
                        "SaldoAnteriorImpreso": "Anterior · MXN",
                        "SaldoEsperado": "Esperado · MXN",
                        "SaldoImpreso": "Impreso · MXN",
                        "Diferencia": "Diferencia · MXN",
                        "ControlAritmetico": "Comprobación",
                        "EstadoRevision": "Revisión",
                    },
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Diferencia = saldo anterior + abono o − cargo − saldo impreso. "
                    "Moneda MXN por confirmar. Cada fila conserva su revisión pendiente."
                )
                with st.expander("Texto original de los movimientos"):
                    st.dataframe(pd.DataFrame(draft["movement_candidates"]), hide_index=True, width="stretch")
                for warning in draft["warnings"]:
                    st.warning(warning)
                st.caption(
                    "Las filas de movimientos siguen pendientes de clasificación, fechas y conciliación."
                )
            else:
                evidence = read_cfdi_evidence(raw)
                status = st.session_state.get(_key("_ops_status"))
                if status is not None:
                    status.documents.append(
                        {"name": file.name, "sha256": evidence["sha256"], "notice": evidence["notice"]}
                    )
                st.write(evidence["notice"])
                st.dataframe(pd.DataFrame([evidence["checks"]]), hide_index=True)
            st.download_button(
                "Descargar evidencia de revisión",
                json.dumps(
                    draft if file.name.lower().endswith(".pdf") else evidence, ensure_ascii=False
                ).encode(),
                "revision_documento.json",
                "application/json",
                key=_key("doc_" + sha256(raw).hexdigest()),
                on_click="ignore",
            )


def _reset_demo():
    files, settings = demo_operations()
    st.session_state["_ops_review_" + DEMO_CONTEXT] = {
        "token": uuid4().hex,
        "files": files,
        "settings": settings,
        "code_changed": False,
    }
    for name in ("_ops_last_book", "_ops_book_signature", "_ops_status", "_ops_focus_step"):
        st.session_state.pop(name + "_" + DEMO_CONTEXT, None)
    st.session_state["operations_tabs"] = "Movimientos"


def _demo_guide():
    st.caption("Datos de práctica en esta pestaña. Tu revisión sigue abierta en la pestaña de origen.")
    with st.expander("Guía de práctica"):
        st.write(
            "El libro parte de 100 MXN y registra una aportación de 50 MXN al final del 5 de enero. "
            "Revisa el control de cierre sin modificar importes para cuadrarlo."
        )
        st.write(
            "Consulta el calendario: el CSV inicial omite un cierre. Descarga el archivo completo "
            "y cárgalo en Valuaciones históricas verificadas, dentro de Movimientos."
        )
        st.download_button(
            "Descargar valuaciones completas del demo",
            DEMO_NAV_COMPLETE,
            "valuaciones_demo_completas.csv",
            "text/csv",
            key="demo_nav_complete",
            on_click="ignore",
        )
        st.write(
            "Después revisa y confirma los flujos del periodo. Descarga el TXT en Archivos y resumen "
            "descargable. El control con diferencia conserva su revisión pendiente."
        )
        with st.expander("Practicar un archivo rechazado"):
            st.write(
                "Este ejemplo contiene una fecha inválida. Puedes cargarlo y después reemplazarlo "
                "por las valuaciones completas para comprobar la recuperación."
            )
            st.download_button(
                "Descargar ejemplo con fecha inválida",
                DEMO_NAV_INVALID,
                "valuaciones_demo_invalidas.csv",
                "text/csv",
                key="demo_nav_invalid",
                on_click="ignore",
            )
        st.button("Reiniciar datos de práctica", key="demo_reset", on_click=_reset_demo)
        st.caption(
            "El demo no guarda en expedientes ni exporta paquetes ZIP. "
            "Para volver a tu revisión, cierra esta pestaña."
        )


def render_account_operations(*, demo=False):
    if demo:
        st.title("Demo de revisión")
        st.caption("Practica el cierre, completa una valuación y guarda el resumen con datos ficticios.")
    else:
        title, action = st.columns([3, 2], vertical_alignment="center")
        with title:
            st.title("Operación por cuenta")
        with action:
            st.link_button(
                "Probar con datos ficticios",
                demo_url(st.context.url),
                help="Abre una pestaña de práctica; tu revisión permanece en esta pestaña.",
            )
        st.caption(
            "Revisa movimientos y fuentes, prepara cambios y reúne el patrimonio con sus datos de origen."
        )
    started = monotonic()
    try:
        context = (None, None, None, None) if demo else _context()
        st.session_state["_ops_context_key"] = (
            DEMO_CONTEXT
            if demo
            else sha256(
                str(
                    (
                        context[1].actor if context[1] else None,
                        context[2]["id"] if context[2] else None,
                        context[3],
                    )
                ).encode()
            ).hexdigest()[:16]
        )
        if demo:
            if "_ops_review_" + DEMO_CONTEXT not in st.session_state:
                _reset_demo()
            _demo_guide()
        st.session_state.pop(_key("_ops_status"), None)
        overview = st.container()
        areas = (
            ("ledger", "Movimientos", _ledger),
            ("implementation", "Implementación", _implementation),
            ("feeds", "Fuentes y alertas", _feeds),
            ("wealth", "Patrimonio", _wealth),
            ("documents", "Originales GBM", _documents),
        )
        tabs = st.tabs([label for _, label, _ in areas], key="operations_tabs", on_change="rerun")
        review_available = False
        for tab, (area, label, render) in zip(tabs, areas, strict=True):
            with tab:
                if demo and area != "ledger":
                    st.info(
                        "Esta práctica se realiza en Movimientos. "
                        "Tu revisión continúa en la pestaña de origen."
                    )
                else:
                    renderer = (lambda ctx: _ledger(ctx, demo=True)) if demo else render
                    available = _render_operation_area(context, area, label, renderer)
                    if area == "ledger":
                        review_available = available is True
        with overview:
            _status_panel(context, demo=demo, review_available=review_available)
        st.caption(
            f"Preparación de la vista: {monotonic() - started:.2f} s. "
            "Los cálculos se ejecutan al solicitarlos."
        )
    except WorkspaceError:
        _forget_book_reference()
        st.session_state.pop(_key("_ops_status"), None)
        st.error(
            "No se pudo abrir o guardar en el expediente. "
            "Actualiza el estado de la cuenta y revisa tu acceso."
        )
    except Exception as error:
        _forget_book_reference()
        st.session_state.pop(_key("_ops_status"), None)
        _show_operation_error("workspace", "Operación", error, public_validation=False)
