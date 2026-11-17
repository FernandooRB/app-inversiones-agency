"""Policy proposals and read-only checks in the current review/session."""

import csv
import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pandas as pd
import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_comparison import strategy_from_analysis
from operations_cuts import build_cut
from operations_policy import evaluate_policy, targets_from_csv, validate_policy
from operations_review_ui import _context_key, _recovery, reset_confirmation, review_key
from portfolio_core import PortfolioError

HEADER = "Instrumento,Moneda,PesoObjetivo\n"
LABELS = {"drift": "Desvío de pesos", "max_weight": "Concentración individual", "cash": "Efectivo disponible"}


def targets_csv(targets):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Instrumento", "Moneda", "PesoObjetivo"])
    for row in targets:
        name = row["instrument"]
        writer.writerow(
            [
                name,
                row["currency"],
                Decimal(row["weight"]) * 100,
            ]
        )
    return stream.getvalue()


def policy_csv(report):
    stream = StringIO(newline="")
    writer = csv.writer(stream)

    def row(values):
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )

    row(["Corte", report["cutoff"], "Moneda", report["base"], "Base de pesos", report["basis"]])
    row(
        [
            "Fuente",
            report["source"],
            "Vigente desde",
            report["valid_from"],
            "Política SHA-256",
            report["policy_sha256"],
        ]
    )
    row(
        [
            "Criterio",
            "Instrumento",
            "Moneda",
            "Estado",
            "Observado %",
            "Objetivo %",
            "Límite pp/%",
            "Diferencia pp",
            "Motivo",
            "Acción",
        ]
    )
    for item in report["rows"]:
        values = [LABELS[item["kind"]], item["instrument"], item["currency"], item["state"]]
        values.extend(
            Decimal(item[k]) * 100 if item[k] is not None else "Pendiente"
            for k in ("observed", "target", "limit", "difference")
        )
        row(values + [item["reason"], item["action"]])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def render_policy(context, status):
    with st.expander("Política y avisos de cartera", key=review_key("policy_panel"), on_change="rerun"):
        if not st.session_state.get(review_key("policy_panel"), False):
            return
        st.write("Compara este corte con los criterios que declares y confirmes.")
        st.caption(
            "Los criterios vacíos permanecen pendientes. "
            "Mantén este panel abierto para incluir los avisos en el informe."
        )
        saved = _recovery().get("policy") or {}
        scope = {"case_id": context[2]["id"] if context[2] and context[3] else None, "account_id": context[3]}
        flow = st.session_state.get("_account_flow", {})
        completed = flow.get("completed")
        if completed:
            with st.expander("Proponer pesos desde el análisis de cuenta"):
                names = [a.name for a in completed["result"]["alternatives"]]
                chosen = st.selectbox("Referencia para la política", names, key=review_key("policy_strategy"))
                if st.button("Copiar pesos como propuesta de política", key=review_key("policy_copy")):
                    binding = (
                        str(context[0].path) if context[0] else None,
                        context[1].actor if context[1] else None,
                        scope["case_id"],
                        context[3],
                    )
                    try:
                        assets = completed["settings"].assets
                        if set(status.book["positions"]) != {(a, status.base) for a in assets}:
                            raise PortfolioError(
                                "Revisa el universo del libro frente al análisis de esta cuenta."
                            )
                        reference = strategy_from_analysis(
                            flow, binding, assets, status.cutoff, status.base, chosen
                        )
                    except PortfolioError as exc:
                        st.text(str(exc))
                    else:
                        targets = [
                            {"instrument": a, "currency": status.base, "weight": str(w)}
                            for a, w in zip(assets, reference["weights"], strict=True)
                        ]
                        raw = targets_csv(targets)
                        st.session_state[review_key("policy_targets")] = raw
                        st.session_state[review_key("policy_basis")] = "Sólo instrumentos cotizados"
                        st.session_state[review_key("policy_source")] = (
                            f"Análisis {chosen} · ejecución {reference['run_id']}"
                        )
                        st.session_state[review_key("policy_reference")] = (raw, reference)
        source = st.text_input(
            "Fuente de la política",
            value=saved.get("source", ""),
            max_chars=500,
            key=review_key("policy_source"),
        )
        valid = st.date_input(
            "Política vigente desde",
            value=date.fromisoformat(saved.get("valid_from", status.cutoff)),
            max_value=date.today(),
            key=review_key("policy_date"),
        )
        bases = ["Patrimonio neto", "Sólo instrumentos cotizados"]
        basis = st.radio(
            "Base de los pesos de política",
            bases,
            index=1 if saved.get("basis") == "invested" else 0,
            key=review_key("policy_basis"),
        )
        raw_targets = st.text_area(
            "Pesos objetivo CSV · PesoObjetivo en %",
            value=targets_csv(saved.get("targets", [])),
            key=review_key("policy_targets"),
            height=120,
        )
        criteria = {}
        for name, label in (
            ("tolerance", "Tolerancia de desvío · puntos porcentuales"),
            ("max_weight", "Máximo individual · % de la base elegida"),
            ("min_cash", "Mínimo de efectivo disponible · % del patrimonio neto"),
        ):
            value = saved.get(name)
            percent = st.number_input(
                label,
                min_value=0.0,
                max_value=100.0,
                value=float(Decimal(value) * 100) if value is not None else None,
                placeholder="Sin definir",
                key=review_key("policy_" + name),
            )
            criteria[name] = str(Decimal(str(percent)) / 100) if percent is not None else None
        st.caption(
            "Efectivo disponible: liquidado menos pagos pendientes; "
            "los cobros pendientes no financian el mínimo. "
            "Concentración por instrumento, sin inferir emisores."
        )
        reset_confirmation(
            "policy_confirmed", [status.snapshot("Política"), source, valid, basis, raw_targets, criteria]
        )
        current = dict(_recovery())
        current.pop("policy", None)
        st.session_state[_context_key("_ops_review")] = current
        try:
            imported = st.session_state.get(review_key("policy_reference"))
            reference = (
                imported[1]
                if imported and imported[0] == raw_targets and basis == bases[1]
                else saved.get("reference")
            )
            targets = targets_from_csv(raw_targets)
            candidate = {
                "schema": 1,
                "scope": scope,
                "base": status.base,
                "valid_from": valid.isoformat(),
                "source": source,
                "basis": "invested" if basis == bases[1] else "net",
                "targets": targets,
                **criteria,
                "reference": reference,
            }
            # An edited target is a new declaration, not the original strategy's exact provenance.
            if reference and (
                basis != bases[1]
                or [float(t["weight"]) for t in targets] != reference["weights"]
                or [t["instrument"] for t in targets] != reference["assets"]
                or status.base != reference["currency"]
                or any(t["currency"] != reference["currency"] for t in targets)
            ):
                candidate["reference"] = None
            candidate = validate_policy(candidate)
            current["policy"] = candidate
            st.session_state[_context_key("_ops_review")] = current
        except PortfolioError as exc:
            st.info("Completa la fuente y los criterios que quieras revisar.")
            st.text(str(exc))
            return
        confirmed = st.checkbox(
            "Confirmé la política, la cuenta y las fuentes de este corte", key=review_key("policy_confirmed")
        )
        try:
            cut = build_cut(
                status.ledger_events,
                cutoff=status.cutoff,
                base=status.base,
                **scope,
                valuation=status.valuation,
                sources={k: v["sha256"] for k, v in status.inputs.items()},
            )
            report = session_compute(
                st.session_state,
                review_key("policy_evaluation"),
                analysis_key(candidate, cut, confirmed),
                lambda: evaluate_policy(candidate, cut, confirmed=confirmed),
                max_entries=1,
            )
        except PortfolioError as exc:
            st.info("La evaluación de política queda pendiente; el libro conserva sus datos.")
            st.text(str(exc))
            return
        status.policy_report = report
        st.text(
            f"Política: {report['counts']['deviations']} desvíos · "
            f"{report['counts']['pending']} pendientes · {status.cutoff}"
        )
        rows = []
        for item in report["rows"][:100]:
            rows.append(
                {
                    "Criterio": LABELS[item["kind"]],
                    "Instrumento": item["instrument"],
                    "Estado": item["state"],
                    "Observado": "Pendiente"
                    if item["observed"] is None
                    else f"{Decimal(item['observed']):.2%}",
                    "Objetivo": "Pendiente" if item["target"] is None else f"{Decimal(item['target']):.2%}",
                    "Límite": "Pendiente"
                    if item["limit"] is None
                    else f"{Decimal(item['limit']) * 100:.2f}" + (" pp" if item["kind"] == "drift" else "%"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for item in [r for r in report["rows"] if r["state"] != "Dentro de límites"][:5]:
            st.text(
                f"{LABELS[item['kind']]} · {item['instrument']} · {item['state']}: "
                f"{item['reason']} {item['action']}"
            )
        st.caption(
            report["notice"]
            + " El CSV conserva todas las filas. Fuente y criterios guardados como propuesta en el ZIP v5."
        )
        with st.expander("Método y evidencia de política"):
            st.text(
                f"Fuente: {report['source']} · Vigente desde {report['valid_from']} · Moneda {report['base']}"
            )
            st.text(f"Política SHA-256 {report['policy_sha256']} · Corte SHA-256 {report['cut_sha256']}")
            st.caption(
                "La tolerancia de desvío usa puntos porcentuales. "
                "El mínimo de efectivo siempre usa patrimonio neto. "
                "Se conserva la precisión declarada y se comparan los límites sin margen añadido. "
                "Las huellas verifican integridad, no autoría."
            )
        st.download_button(
            "Descargar avisos de política CSV",
            policy_csv(report),
            f"avisos_politica_{status.cutoff}.csv",
            "text/csv",
            key=review_key("policy_csv"),
            on_click="ignore",
        )
        st.download_button(
            "Descargar política propuesta JSON",
            json.dumps(candidate, ensure_ascii=False, allow_nan=False).encode(),
            f"politica_{status.cutoff}.json",
            "application/json",
            key=review_key("policy_json"),
            on_click="ignore",
        )
