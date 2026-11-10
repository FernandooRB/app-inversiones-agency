"""Account operations: reviewed evidence, ledger, implementation, feeds and wealth."""

import base64
import json
import logging
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
from implementation_costs import ImplementationCostAssumptions
from ledger_reconciliation import COLUMNS as CONTROL_COLUMNS
from ledger_reconciliation import read_closing_controls, reconcile_book
from multi_currency_wealth import consolidate_wealth, consolidated_performance, match_internal_flows
from operations_jobs import refresh_subscription
from operations_review_ui import (
    download_review,
    open_review,
    reset_confirmation,
    review_defaults,
    review_key,
    review_upload,
)
from portfolio_core import PortfolioError
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


def _forget_book_reference():
    st.session_state.pop(_key("_ops_last_book"), None)
    st.session_state.pop(_key("_ops_book_signature"), None)


def _remember_book(book, cutoff, source):
    signature = analysis_key({
        "ledger": sha256(source).hexdigest(), "cutoff": cutoff.isoformat(),
        "review": review_key("book_source"),
    })
    if st.session_state.get(_key("_ops_book_signature")) != signature:
        # The monitor checkbox is rendered later, in Fuentes y alertas.
        st.session_state[_key("monitor_confirmation")] = False
    st.session_state[_key("_ops_book_signature")] = signature
    st.session_state[_key("_ops_last_book")] = {"book": book, "cutoff": cutoff.isoformat()}


def _show_operation_error(area, label, error, *, public_validation=True):
    stage = error.stage if isinstance(error, _OperationInputError) else label
    original = error.error if isinstance(error, _OperationInputError) else error
    if public_validation and isinstance(original, PortfolioError):
        st.error(f"Revisa {stage}.")
        # Plain text prevents uploaded identifiers being interpreted as Markdown.
        st.text(str(original))
    else:
        reference = uuid4().hex[:12]
        LOGGER.error(
            "Unexpected operation error area=%s type=%s reference=%s",
            area, type(original).__name__, reference,
        )
        st.error(f"No se pudo completar {stage}.")
        st.caption(f"Vuelve a intentarlo. Si persiste, conserva esta referencia: {reference}.")


def _render_operation_area(context, area, label, render):
    try:
        render(context)
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
    with st.expander("Conciliar contra el estado de cuenta"):
        st.caption(
            "Compara CASH (efectivo liquidado), PENDING (efectivo pendiente), POSITION (títulos) "
            "y REPO (capital por referencia). Usa saldos y fuentes del mismo cierre y cuenta."
        )
        _template("Plantilla de controles de cierre", CONTROL_COLUMNS, "closing_controls_template")
        source = review_upload("Controles de cierre", "controls", key="ops_closing_controls")
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
        view["Tipo"] = view["Tipo"].replace({
            "CASH": "Efectivo liquidado", "PENDING": "Efectivo pendiente",
            "POSITION": "Títulos", "REPO": "Capital de reporto",
        })
        view["Estado"] = view["Estado"].replace({
            "COINCIDE": "Coincide", "SIN_CONTROL": "Sin control", "DIFERENCIA": "Diferencia",
        })
        st.dataframe(
            view.style.format(
                {"Libro": "{:,.12g}", "Control": "{:,.12g}",
                 "Diferencia": lambda value: f"{value:+,.12g}" if value else "0"}, na_rep="—",
            ).set_properties(subset=["Libro", "Control", "Diferencia"], **{"text-align": "right"}),
            hide_index=True, width="stretch",
        )
        st.caption(
            "Cada saldo conserva su unidad y moneda. Un control ausente sigue pendiente; "
            "la coincidencia aritmética no acredita integridad del estado ni aprobación de la cuenta."
        )
        payload = {
            **result, "ledger_sha256": sha256(ledger_bytes).hexdigest(),
            "controls_sha256": sha256(source.getvalue()).hexdigest(),
            "code_sha256": {
                name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in ("transaction_ledger.py", "ledger_reconciliation.py")
            },
        }
        st.download_button(
            "Descargar conciliación de cierre",
            json.dumps(payload, ensure_ascii=False, default=str).encode(),
            f"conciliacion_cierre_{cutoff}.json", "application/json",
            key=_key("closing_reconciliation_download"), on_click="ignore",
        )
        _save_evidence(context, "Conservar conciliación de cierre", payload)
        return payload


def _native_flow_amount(event):
    value = event.quantity * event.price if event.kind.startswith("ASSET_") else event.amount
    return float(value) * (-1 if event.kind in {"WITHDRAWAL", "TRANSFER_OUT", "ASSET_OUT"} else 1)


def _valuation_calendar(start, end, flows, available_dates=()):
    with st.expander("Valuaciones necesarias para TWR"):
        if start >= end:
            st.info("Selecciona un cierre posterior a la apertura del libro para planear el periodo.")
            return None
        result = valuation_requirements(start, end, flows, available_dates=available_dates)
        st.caption(f"Periodo del plan: {start.isoformat()} a {end.isoformat()}.")
        if result["twr_coverage_ready"]:
            st.success("Las fechas y los momentos declarados cubren el calendario de TWR.")
        else:
            st.warning(
                "Calendario pendiente · Cierres obligatorios faltantes: "
                f"{len(result['missing_required_dates'])} "
                f"· Flujos sin momento: {result['unknown_flow_count']}."
            )
        view = pd.DataFrame([
            {
                "Fecha": row["date"],
                "Requisito": "Obligatorio" if row["required"] else "Si el flujo se confirma BOD",
                "Fecha en CSV": "Aportada" if row["available"] else "Falta",
                "Motivo": "; ".join(row["reasons"]),
            }
            for row in result["rows"]
        ])
        st.dataframe(view, hide_index=True, width="stretch")
        st.caption(
            "BOD requiere el cierre del día calendario anterior; EOD usa el cierre de la fecha del flujo. "
            "UNKNOWN conserva ambos escenarios pendientes. El plan sólo revisa fechas: no aprueba "
            "saldos, clasificación de flujos, FX ni eventos corporativos."
        )
        st.download_button(
            "Descargar plan de valuaciones", view.to_csv(index=False).encode("utf-8-sig"),
            f"plan_valuaciones_{start}_{end}.csv", "text/csv",
            key=_key("valuation_calendar_download"), on_click="ignore",
        )
        return result


def _ledger(context):
    # Rebuild the reference from current inputs before another tab may use it.
    st.session_state.pop(_key("_ops_last_book"), None)
    st.subheader("Movimientos y rendimiento histórico")
    st.caption("Títulos a fecha de operación, efectivo a liquidación y pendientes separados. MXN y USD.")
    open_review(context)
    _template("Plantilla de libro normalizado", COLUMNS, "ledger_template")
    with st.expander("Cómo registrar reportos"):
        st.write(
            "OPEN_REPO registra el capital inicial sin mover efectivo; REPO_START invierte capital; "
            "REPO_MATURITY cobra el bruto, con Interes ya incluido. Usa una referencia única por reporto."
        )
    source = review_upload("Libro normalizado de movimientos", "ledger", key="ops_ledger")
    if not source:
        _forget_book_reference()
        st.info(
            "Importa el libro para revisar saldos y flujos. "
            "Las compras, ventas y dividendos son movimientos internos."
        )
        return
    events = _checked_input("Libro de movimientos", read_ledger, source.getvalue())
    defaults = review_defaults()
    cutoff = st.date_input(
        "Cierre del libro", value=date.fromisoformat(defaults["cutoff"]) if defaults else date.today(),
        max_value=date.today(), key=review_key("ops_cutoff"),
    )
    files = {"ledger": source}
    book = _checked_input("Cierre del libro", book_at, events, cutoff)
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
            ).style.format({"Capital": "{:,.2f}"}).set_properties(
                subset=["Capital"], **{"text-align": "right"}
            ),
            hide_index=True,
            width="stretch",
        )
        _template("Plantilla de valuación de reportos", REPO_VALUE_COLUMNS, "repo_values_template")
        repo_file = review_upload(
            "Valuación de reportos al cierre: Fecha,Referencia,Moneda,Valor,Fuente",
            "repo_values", key="ops_repo_values",
        )
        if not repo_file:
            st.info(
                "Valuación pendiente: carga el valor total documentado de cada reporto al cierre, "
                "incluidos los intereses devengados que correspondan. El capital no sustituye esa valuación."
            )
    repo_values = _checked_input(
        "Valuación de reportos", read_repo_values, repo_file.getvalue(), cutoff
    ) if repo_file else None
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
    quotes_file = review_upload(
        "Cotizaciones de cierre: Fecha,Instrumento,Moneda,Precio", "quotes", key="ops_raw"
    )
    fx_file = review_upload(
        "FX del cierre: Fecha,Moneda,Base,Tasa,Fuente", "fx", key="ops_book_fx"
    )
    base = st.selectbox(
        "Moneda del rendimiento y valuación", ["MXN", "USD"],
        index=1 if defaults.get("base") == "USD" else 0, key=review_key("ops_base"),
    )
    files.update(quotes=quotes_file, fx=fx_file)
    reset_confirmation("raw_confirmation", [
        source.getvalue(), cutoff, base,
        *(file.getvalue() if file else b"" for file in (repo_file, quotes_file, fx_file)),
    ])
    raw_confirmed = st.checkbox(
        "Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre",
        key=review_key("raw_confirmation"),
    )
    if (quotes_file or not book["positions"]) and raw_confirmed and (not book["repos"] or repo_file):
        quotes = _checked_input("Cotizaciones de cierre", _csv, quotes_file) if quotes_file else pd.DataFrame(
            columns=["Fecha", "Instrumento", "Moneda", "Precio"]
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
                set(book["cash"]) | {c for _, c in book["positions"]}
                | set(book["pending"]) | {c for _, c in book["repos"]}
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
            "Valuación al cierre", value_book, book, quote_map, rates,
            base=base, raw_prices_confirmed=True, repo_values=repo_values,
        )
        st.metric(f"Patrimonio neto al cierre · {base}", f"{valued['nav']:,.2f}")
        st.dataframe(
            pd.DataFrame(valued["detail"]).style.format(
                {"ValorOrigen": "{:,.2f}", "FX": "{:,.6g}", "ValorBase": "{:,.2f}"}
            ),
            hide_index=True, width="stretch",
        )
    nav_file = review_upload("Valuaciones históricas verificadas: Fecha,NAV", "nav", key="ops_nav")
    nav = None
    if nav_file:
        nav = _checked_input("Valuaciones históricas", _read_nav, nav_file)
        start, end = nav.index[0].date(), nav.index[-1].date()
    else:
        start = min((event.day for event in events if event.day <= cutoff), default=cutoff)
        end = cutoff
    period_events = [
        event for event in events
        if event.kind in EXTERNAL_EVENT_KINDS and start < event.settled <= end
    ]
    _valuation_calendar(
        start, end,
        [Flow(event.settled, _native_flow_amount(event), event.timing) for event in period_events],
        available_dates=nav.index if nav is not None else (),
    )
    flow_fx_file = review_upload(
        "FX por fecha de cada flujo: Fecha,Moneda,Base,Tasa,Fuente", "flow_fx", key="ops_flow_fx"
    )
    files.update(nav=nav_file, flow_fx=flow_fx_file)
    reset_confirmation("flows_confirmation", [
        cutoff, base, *(file.getvalue() if file else b"" for file in files.values()),
    ])
    verified = st.checkbox(
        "Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida",
        key=review_key("flows_confirmation"),
    )
    if nav_file and verified:
        fx_frame = _checked_input("FX de los flujos", _csv, flow_fx_file) if flow_fx_file else pd.DataFrame()
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
        result = _checked_input("Rendimiento histórico", performance, nav, flows)
        a, b, c = st.columns(3)
        a.metric("Ganancia separada de flujos", f"{result['gain']:,.2f} {base}")
        b.metric("TWR del periodo", f"{result['twr']:.2%}" if result["twr"] is not None else "Pendiente")
        c.metric("XIRR anualizada", f"{result['xirr']:.2%}" if result["xirr"] is not None else "Pendiente")
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
    download_review(context, files, cutoff=cutoff, base=base)


def _implementation(context):
    st.subheader("Propuesta por títulos y lotes")
    st.caption(
        "Minimiza desvío del objetivo y costos sujetos a efectivo, lotes, concentración y rotación. "
        "Comprueba precios, lotes y tarifas con tu intermediario antes de usar una propuesta."
    )
    _template(
        "Plantilla de posiciones y objetivo",
        ["Instrumento", "Cantidad", "Precio", "Lote", "PesoObjetivo"],
        "execution_template",
    )
    upload = st.file_uploader(
        "Posiciones, cotizaciones sin ajuste y pesos objetivo", ["csv"], key=_key("ops_execution")
    )
    cash = st.number_input("Efectivo disponible para operar", min_value=0.0, value=0.0)
    floor = st.number_input("Efectivo mínimo que deseas conservar", min_value=0.0, value=0.0)
    currency = st.selectbox("Moneda de las órdenes", ["MXN", "USD"])
    quote_day = st.date_input("Fecha de cotización de las órdenes", date.today(), max_value=date.today())
    quote_source = st.text_input("Fuente de cotizaciones y lotes")
    commission = st.number_input("Comisión · puntos base por operación", 0.0, 500.0, 0.0)
    minimum = st.number_input("Comisión mínima por orden", 0.0, 100000.0, 0.0)
    market = st.number_input("Costo de mercado · puntos base", 0.0, 500.0, 0.0)
    vat = st.number_input("IVA sobre comisión · %", 0.0, 100.0, 0.0) / 100
    tariff_source = st.text_input("Fuente y vigencia de las tarifas aplicables")
    turnover = st.slider("Rotación máxima · suma de compras y ventas / patrimonio", 0.0, 2.0, 0.5)
    cap = st.slider("Concentración máxima por activo sobre capital inicial", 0.01, 1.0, 1.0)
    min_trade = st.number_input("Importe mínimo por orden", 0.0, value=0.0)
    confirmed = st.checkbox(
        "Confirmé precios sin ajuste, títulos, lotes, moneda y tarifas de esta cuenta",
        key=_key("orders_confirmation"),
    )
    optimize = st.checkbox("Usar modelo de costos y riesgo del análisis de cuenta abierto en esta sesión")
    if st.button("Calcular propuesta de títulos", disabled=not upload or not confirmed):
        if not quote_source.strip() or not tariff_source.strip():
            raise PortfolioError("Documenta las fuentes de cotizaciones y tarifas.")
        positions = _csv(upload)
        if "PesoObjetivo" not in positions:
            raise PortfolioError("Falta el peso objetivo de cada instrumento.")
        target = pd.to_numeric(positions["PesoObjetivo"], errors="raise").to_numpy()
        if optimize:
            flow = st.session_state.get("_account_flow", {})
            completed = flow.get("completed")
            _, _, state, account = context
            if (
                not completed
                or currency != "MXN"
                or (state and flow.get("context", (None,) * 4)[2:] != (state["id"], account))
            ):
                raise PortfolioError("Abre primero un análisis MXN de esta misma cuenta.")
            assets = tuple(positions["Instrumento"])
            if assets != completed["settings"].assets:
                raise PortfolioError("Los instrumentos y su orden deben coincidir con el análisis de cuenta.")
            moments = completed["result"]["model"].moments
            current = positions["Cantidad"].astype(float) * positions["Precio"].astype(float)
            target = cost_aware_target(
                moments.mean,
                moments.covariance,
                current / current.sum(),
                cost_rate=(commission * (1 + vat) + market) / 10000,
                max_weight=cap,
                max_turnover=turnover,
            )
        assumptions = ImplementationCostAssumptions(commission, market, vat, minimum)
        result = executable_plan(
            positions,
            cash,
            target,
            assumptions,
            cash_floor=floor,
            max_turnover=turnover,
            max_weight=cap,
            minimum_trade=min_trade,
            quotes_confirmed=confirmed,
        )
        st.session_state["_execution_proposal"] = {
            "context": (context[2]["id"] if context[2] else None, context[3]),
            "result": result,
            "inputs": {
                "currency": currency,
                "date": str(quote_day),
                "quote_source": quote_source,
                "tariff_source": tariff_source,
                "tariff": asdict(assumptions),
                "cash": cash,
                "cash_floor": floor,
                "max_turnover": turnover,
                "max_weight": cap,
                "minimum_trade": min_trade,
                "target": target.tolist(),
                "csv": base64.b64encode(upload.getvalue()).decode(),
            },
        }
    proposal = st.session_state.get("_execution_proposal")
    binding = (context[2]["id"] if context[2] else None, context[3])
    if proposal and proposal["context"] == binding:
        result = proposal["result"]
        formats = {column: "{:,.2f}" for column in ("Importe firmado", "Comisión e IVA", "Costo de mercado")}
        formats.update({column: "{:.2%}" for column in ("PesoObjetivo", "Peso final sobre capital inicial")})
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
        _save_evidence(
            context,
            "Conservar propuesta e insumos",
            {
                "inputs": proposal["inputs"],
                "result": {**result, "detail": result["detail"].to_dict("records")},
            },
        )


def _feeds(context):
    st.subheader("Fuentes aprobadas y alertas")
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
    st.subheader("Patrimonio entre cuentas MXN y USD")
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
    st.subheader("Revisión de originales GBM")
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
                    {"EXACTO": "Cuadra", "DIFERENCIA_CENTAVO": "Difiere un centavo",
                     "DIFERENCIA_MAYOR": "Diferencia mayor"}
                )
                display["EstadoRevision"] = "Pendiente"
                display["Sentido"] = display["Sentido"].str.capitalize()
                st.dataframe(
                    display.style.format({column: "{:,.2f}" for column in money}, na_rep="—"),
                    column_config={
                        "Pagina": "Página", "Sentido": "Movimiento", "NetoImpreso": "Neto · MXN",
                        "SaldoAnteriorImpreso": "Anterior · MXN", "SaldoEsperado": "Esperado · MXN",
                        "SaldoImpreso": "Impreso · MXN", "Diferencia": "Diferencia · MXN",
                        "ControlAritmetico": "Comprobación", "EstadoRevision": "Revisión",
                    },
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Diferencia = saldo anterior + abono o − cargo − saldo impreso. "
                    "Moneda MXN por confirmar. Cada fila conserva su revisión pendiente."
                )
                with st.expander("Texto original de los movimientos"):
                    st.dataframe(
                        pd.DataFrame(draft["movement_candidates"]), hide_index=True, width="stretch"
                    )
                for warning in draft["warnings"]:
                    st.warning(warning)
                st.caption(
                    "Las filas de movimientos siguen pendientes de clasificación, fechas y conciliación."
                )
            else:
                evidence = read_cfdi_evidence(raw)
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


def render_account_operations():
    st.title("Operación por cuenta")
    st.caption("Revisa movimientos y fuentes, prepara cambios y reúne el patrimonio con sus datos de origen.")
    started = monotonic()
    try:
        context = _context()
        st.session_state["_ops_context_key"] = sha256(
            str(
                (
                    context[1].actor if context[1] else None,
                    context[2]["id"] if context[2] else None,
                    context[3],
                )
            ).encode()
        ).hexdigest()[:16]
        areas = (
            ("ledger", "Movimientos", _ledger), ("implementation", "Implementación", _implementation),
            ("feeds", "Fuentes y alertas", _feeds), ("wealth", "Patrimonio", _wealth),
            ("documents", "Originales GBM", _documents),
        )
        tabs = st.tabs([label for _, label, _ in areas], key="operations_tabs")
        for tab, (area, label, render) in zip(tabs, areas, strict=True):
            with tab:
                _render_operation_area(context, area, label, render)
        st.caption(
            f"Preparación de la vista: {monotonic() - started:.2f} s. "
            "Los cálculos se ejecutan al solicitarlos."
        )
    except WorkspaceError:
        _forget_book_reference()
        st.error(
            "No se pudo abrir o guardar en el expediente. "
            "Actualiza el estado de la cuenta y revisa tu acceso."
        )
    except Exception as error:
        _forget_book_reference()
        _show_operation_error("workspace", "Operación", error, public_validation=False)
