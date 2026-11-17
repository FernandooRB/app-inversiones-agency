"""Native review controls. Historical cut files never restore session confirmations."""

import csv
from decimal import Decimal
from io import StringIO

import pandas as pd
import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_cuts import build_cut, compare_cuts, read_cut
from portfolio_core import PortfolioError

LABELS = {
    "wealth_change": "Cambio de patrimonio",
    "contributions": "Aportaciones entre cortes",
    "withdrawals": "Retiros entre cortes",
    "gain": "Ganancia monetaria entre cortes",
    "price": "Variación por precios",
    "income": "Ingresos documentados",
    "fees": "Comisiones y cargos",
    "tax": "Impuestos registrados",
    "fx": "Efecto de divisas",
    "repo": "Variación de valuación de reportos",
    "unexplained": "Variación no desglosada",
}


def comparison_lines(result):
    return [
        [label, "Pendiente" if result.get(key) is None else f"{Decimal(result[key]):,.2f} {result['base']}"]
        for key, label in LABELS.items()
    ]


def comparison_csv(result):
    stream = StringIO(newline="")
    writer = csv.writer(stream)

    def row(*values):
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )

    def number(value):
        return "Pendiente" if value is None else Decimal(value)

    row("Comparación de cortes", result["start"], result["end"], result["base"], result["mode"])
    row("Corte inicial SHA-256", result["cut_ids"][0])
    row("Corte final SHA-256", result["cut_ids"][1])
    row("Concepto", "Importe", "Moneda")
    for key, label in LABELS.items():
        row(label, number(result.get(key)), result["base"])
    for name, value in result.get("known_components", {}).items():
        if not result.get("coverage", {}).get(name, True):
            row("Subtotal documentado · " + LABELS[name], number(value), result["base"])
    row("Saldos", "Instrumento", "Moneda", "Anterior", "Actual", "Cambio", "Peso anterior", "Peso actual")
    for item in result["balances"]:
        row(
            item["section"],
            item["instrument"],
            item["currency"],
            *(number(item[n]) for n in ("before", "after", "change", "weight_before", "weight_after")),
        )
    row("Precios", "Instrumento", "Moneda", "Variación nativa", "Variación base")
    for item in result["by_instrument"]:
        row(
            "Precio",
            item["instrument"],
            item["currency"],
            number(item["price_native"]),
            number(item["price_base"]),
        )
    row("Ingresos y cargos", "Instrumento", "Moneda", "Ingreso", "Comisión", "Impuesto", "Neto", "IDs")
    for item in result["documented"]:
        row(
            "Documentado",
            item["instrument"],
            item["currency"],
            *(number(item[n]) for n in ("income", "fees", "tax", "net")),
            " | ".join(item["event_ids"]),
        )
    for i, historical in enumerate(result["historical_results"]):
        if historical:
            row(
                "Resultado histórico propio",
                "Inicial" if i == 0 else "Final",
                historical["start"],
                historical["end"],
                *(number(historical[n]) for n in ("gain", "twr", "xirr")),
            )
    for period, issues in (("Inicial", result["issues_before"]), ("Final", result["issues_after"])):
        for issue in issues:
            row("Incidencia " + period, issue["id"], issue["title"], issue["state"], issue["reason"])
    for pending in result["pending"]:
        row("Pendiente de comparación", pending)
    for source in result["source_changes"]:
        row("Fuente distinta", source)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def render_cut_comparison(context, status, snapshot, *, key):
    """Build/download lazily; cache is per review, account and all current inputs."""
    with st.expander("Comparar y guardar cortes", key=key("cuts_panel"), on_change="rerun"):
        if not st.session_state.get(key("cuts_panel"), False):
            st.session_state.pop(key("cut_comparison_result"), None)
            return None
        st.write("Guarda el estado de hoy y compáralo con otro corte de la misma cuenta y moneda.")
        st.caption(
            "El corte JSON conserva saldos, fuentes y resultados históricos. El ZIP sigue siendo el archivo "
            "para continuar la revisión. Son archivos privados sin cifrar; no incluyen originales PDF/XML."
        )
        st.caption("Mantén este panel abierto para incluir la comparación vigente en el TXT y el PDF.")
        signature = analysis_key(snapshot)
        _store, _principal, state, account = context
        try:
            raw = session_compute(
                st.session_state,
                key("cut_build"),
                signature,
                lambda: build_cut(
                    status.ledger_events,
                    cutoff=status.cutoff,
                    base=status.base,
                    case_id=state["id"] if state and account else None,
                    account_id=account,
                    valuation=status.valuation,
                    summary=status.performance_summary,
                    sources={k: v["sha256"] for k, v in status.inputs.items()},
                    issues=snapshot["issues"],
                ),
                max_entries=1,
            )
            st.download_button(
                "Descargar corte actual JSON",
                raw,
                f"corte_{status.cutoff}.json",
                "application/json",
                key=key("cut_download"),
                on_click="ignore",
            )
            previous = st.file_uploader(
                "Corte anterior JSON", type=["json"], max_upload_size=2, key=key("cut_previous")
            )
            if previous is None:
                st.session_state.pop(key("cut_comparison_result"), None)
                return None
            historical = read_cut(previous.getvalue())
            st.text(f"Corte aportado: {historical['payload']['cutoff']} · {historical['payload']['base']}")
            consent_signature = analysis_key(raw, previous.getvalue())
            if st.session_state.get(key("cuts_consent_signature")) != consent_signature:
                st.session_state[key("cuts_confirmed")] = False
                st.session_state[key("cuts_consent_signature")] = consent_signature
            confirmed = st.checkbox(
                "Cotejé ambos cortes, su cuenta y sus fuentes para esta comparación",
                key=key("cuts_confirmed"),
            )
            result = session_compute(
                st.session_state,
                key("cut_compare"),
                analysis_key(consent_signature, confirmed),
                lambda: compare_cuts(previous.getvalue(), raw, confirmed=confirmed),
                max_entries=1,
            )
        except PortfolioError as exc:
            st.session_state.pop(key("cut_comparison_result"), None)
            st.error(str(exc))
            return None
        st.session_state[key("cut_comparison_result")] = {"signature": signature, "result": result}
        st.caption(f"{result['start']} → {result['end']} · {result['base']}")
        table_key = "cuts_totals_" + analysis_key(key("totals"))[:16]
        with st.container(key=table_key):
            st.html(f"""<style>
              .st-key-{table_key} td:last-child, .st-key-{table_key} th:last-child {{
                text-align:right!important;font-variant-numeric:tabular-nums;
              }}
            </style>""")
            st.table(pd.DataFrame(comparison_lines(result), columns=["Concepto", "Importe"]))
            partial = [
                [LABELS[name], f"{Decimal(value):,.2f} {result['base']}"]
                for name, value in result.get("known_components", {}).items()
                if not result.get("coverage", {}).get(name, True)
            ]
            if partial:
                st.caption(
                    "Subtotales documentados de componentes incompletos; "
                    "ya se excluyen de la variación sin desglose."
                )
                st.table(pd.DataFrame(partial, columns=["Componente pendiente", "Subtotal documentado"]))
        st.caption(
            "El cambio de patrimonio incluye aportaciones y retiros. La ganancia entre cortes usa el libro "
            "con sus liquidaciones pendientes; no es un TWR. Ningún pendiente se convierte en cero."
        )
        for pending in result["pending"][:10]:
            st.text(pending)
        with st.expander("Títulos, saldos, pesos y evidencia entre cortes"):
            displayed_balances = pd.DataFrame(result["balances"][:100])
            for name in ("weight_before", "weight_after"):
                if name in displayed_balances:
                    displayed_balances[name] = displayed_balances[name].map(
                        lambda v: "Pendiente" if v is None else f"{Decimal(v):.2%}"
                    )
            st.dataframe(
                displayed_balances.rename(
                    columns={
                        "section": "Saldo",
                        "instrument": "Instrumento",
                        "currency": "Moneda",
                        "before": "Anterior",
                        "after": "Actual",
                        "change": "Cambio",
                        "weight_before": "Peso anterior",
                        "weight_after": "Peso actual",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Pesos sobre patrimonio neto de cada corte; efectivo y pendientes se conservan por separado."
            )
            if result["by_instrument"]:
                st.dataframe(
                    pd.DataFrame(result["by_instrument"][:100]).rename(
                        columns={
                            "instrument": "Instrumento",
                            "currency": "Moneda",
                            "price_native": "Precio · moneda origen",
                            "price_base": "Precio · moneda base",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
            if result["documented"]:
                st.caption("Ingresos y cargos por instrumento · moneda de origen")
                st.dataframe(
                    pd.DataFrame(result["documented"][:100]).rename(
                        columns={
                            "instrument": "Instrumento",
                            "currency": "Moneda",
                            "income": "Ingreso",
                            "fees": "Cargos",
                            "tax": "Impuestos",
                            "net": "Neto",
                            "event_ids": "Movimientos",
                            "converted": "Coincide con moneda base",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
            for label, issues in (("Inicial", result["issues_before"]), ("Actual", result["issues_after"])):
                st.text(f"{label}: {len(issues)} incidencias conservadas.")
            st.text("Fuentes cambiadas: " + (", ".join(result["source_changes"]) or "ninguna"))
            st.caption("El CSV conserva todas las filas; aquí se muestran hasta 100 por tabla.")
        with st.expander("Rendimientos históricos y método de atribución"):
            for label, historic in zip(("Inicial", "Actual"), result["historical_results"], strict=True):
                twr = historic["twr"] if historic and historic["twr"] is not None else "Pendiente"
                xirr = historic["xirr"] if historic and historic["xirr"] is not None else "Pendiente"
                st.text(
                    f"{label}: "
                    + (
                        f"{historic['start']} a {historic['end']} · TWR {twr} · XIRR {xirr} (fracciones)"
                        if historic
                        else "sin resultado guardado"
                    )
                )
            st.caption(
                "No se restan TWR ni XIRR de periodos distintos. Precio = valor final − inicial − compras "
                "+ ventas − entradas en especie + salidas en especie. Ingresos y cargos se separan por fecha "
                "de operación. En tenencias sin movimientos: precio a FX final y FX sobre valor inicial. "
                "Con movimientos en divisa se requiere FX de cada operación; "
                "lo no cubierto queda sin desglose. "
                "Las huellas comprueban integridad, no autoría ni exactitud de las fuentes."
            )
        st.download_button(
            "Descargar comparación de cortes CSV",
            comparison_csv(result),
            f"comparacion_{result['start']}_{result['end']}.csv",
            "text/csv",
            key=key("cut_csv"),
            on_click="ignore",
        )
        return result
