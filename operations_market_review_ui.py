"""Session-only comparison panel in Fuentes y alertas."""

import json
from urllib.parse import urlsplit
from uuid import uuid4

import pandas as pd
import streamlit as st

from analysis_session import analysis_key
from operations_market_review import STATES, TYPES, compare_observations, fingerprint
from operations_review_ui import _context_key, review_key
from portfolio_core import PortfolioError
from scripts.market_review_fixture import fictional_observations, observations_csv

PENDING = {"DIFERENCIA", "NO_COMPARABLE", "FALTA_PRINCIPAL", "FALTA_REFERENCIA"}
REASONS = {
    "Mercado": "mercado",
    "Moneda": "moneda",
    "Unidad": "unidad o dirección",
    "Metodo": "metodología",
    "PlazoDias": "plazo",
    "BaseDias": "base de días",
    "Corte": "hora de corte",
    "Proveedor": "proveedor compartido",
    "Origen": "origen compartido",
    "Evidencia": "evidencia compartida",
}


def _reset(result_key, generation_key):
    st.session_state.pop(result_key, None)
    st.session_state[generation_key] = uuid4().hex


def _local_uploads(url):
    """Expose file uploads in the local app. Hosted checks use the built-in fixtures."""
    try:
        address = urlsplit(url or "")
        return address.scheme in {"http", "https"} and address.hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def _detail(row):
    st.text(f"{row['series']} · {row['date']} · {STATES[row['state']]}")
    if row["reasons"]:
        st.text("Revisa: " + ", ".join(REASONS[field] for field in row["reasons"]))
    if row["delta"] is not None:
        st.text(f"Principal − referencia: {row['delta']} · Diferencia: {row['bps']} pb")
    labels = {
        "Valor": "Valor original",
        "Moneda": "Moneda",
        "Unidad": "Unidad",
        "Mercado": "Mercado",
        "Metodo": "Método",
        "Corte": "Hora y zona",
        "PlazoDias": "Plazo en días",
        "BaseDias": "Base de días",
        "Proveedor": "Proveedor",
        "Origen": "Origen del dato",
        "Evidencia": "Evidencia",
    }
    for name, label in (("primary", "Principal"), ("reference", "Referencia")):
        item = row[name]
        if item is None:
            st.text(f"{label}: sin dato")
            continue
        st.write(f"**{label} · fila {row[name + '_line']}**")
        st.text("\n".join(f"{title}: {item[field]}" for field, title in labels.items() if item[field]))


def _result(report, key):
    rows = report["rows"]
    flagged = sum(report["counts"].get(state, 0) for state in PENDING)
    comparable = sum(group["comparable"] for group in report["coverage"].values())
    st.write(f"**{len(rows):,} observaciones · {comparable:,} comparables · {flagged:,} por revisar**")
    st.caption("Compara principal menos referencia. Las diferencias requieren cotejo humano.")
    with st.expander("Cobertura, huellas y cálculo"):
        st.table(
            [
                {
                    "Tipo": TYPES[kind],
                    "Observaciones": group["union"],
                    "En ambos CSV": group["paired"],
                    "Comparables": group["comparable"],
                }
                for kind, group in report["coverage"].items()
            ]
        )
        for side, label in (("primary", "Principal"), ("reference", "Referencia")):
            st.text(f"{label} · SHA-256 {report['inputs'][side + '_sha256']}")
        st.caption(
            "Precios y FX: diferencia relativa a la referencia × 10,000. "
            "Tasas: diferencia en puntos porcentuales × 100. El límite se aplica al valor sin redondear."
        )
        st.text(
            "Umbrales en pb: " + " · ".join(f"{TYPES[k]} {v}" for k, v in report["tolerances_bps"].items())
        )
    only_pending = st.checkbox(
        "Mostrar sólo observaciones por revisar", value=bool(flagged), key=key("pending")
    )
    shown = [row for row in rows if not only_pending or row["state"] in PENDING]
    if shown:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Fecha": row["date"],
                        "Serie": row["series"],
                        "Tipo": TYPES[row["type"]],
                        "Principal": row["primary"]["Valor"] if row["primary"] else "—",
                        "Referencia": row["reference"]["Valor"] if row["reference"] else "—",
                        "Diferencia · pb": row["bps"] if row["bps"] is not None else "—",
                        "Revisión": STATES[row["state"]],
                    }
                    for row in shown[:200]
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("La tabla muestra hasta 200 filas. La ficha y el JSON permiten revisar el resto.")
        limit_key = key("row_" + str(len(shown)))
        index = (
            int(
                st.number_input(
                    "Número de observación para cotejar",
                    min_value=1,
                    max_value=len(shown),
                    step=1,
                    key=limit_key,
                )
            )
            - 1
        )
        _detail(shown[index])
    else:
        st.info("Las observaciones del cotejo están dentro del umbral declarado.")
    download_panel = key("download_panel")
    with st.expander("Descargar evidencia del cotejo", key=download_panel, on_change="rerun"):
        if st.session_state.get(download_panel, False):
            st.download_button(
                "Descargar cotejo JSON",
                json.dumps(report, ensure_ascii=False, indent=2).encode(),
                "cotejo_fuentes.json",
                "application/json",
                on_click="ignore",
                key=key("download"),
            )


def render_market_review():
    panel = review_key("market_panel")
    with st.expander("Cotejar precios, tipos de cambio y tasas", key=panel, on_change="rerun"):
        if not st.session_state.get(panel, False):
            return
        result_key, generation_key = _context_key("_market_result"), _context_key("_market_generation")
        generation = st.session_state.get(generation_key, "initial")

        def key(name):
            return review_key(f"market_{name}_{generation}")

        st.caption("Usa datos ficticios en la web. Coteja archivos reales autorizados en la app local.")
        mode = "Práctica ficticia"
        if _local_uploads(st.context.url):
            mode = st.radio("Origen de los archivos", [mode, "Cargar dos CSV"], key=key("mode"))
        fixture_primary, fixture_reference = fictional_observations()
        if mode == "Práctica ficticia":
            primary, reference = fixture_primary, fixture_reference
            st.caption(
                "El caso de práctica incluye una diferencia de FX, un precio ajustado y un plazo distinto."
            )
            columns = st.columns(2)
            for col, raw, label, name in zip(
                columns,
                (primary, reference),
                ("principal", "referencia"),
                ("principal_ficticio.csv", "referencia_ficticia.csv"),
                strict=True,
            ):
                col.download_button(
                    f"Descargar CSV {label} ficticio"
                    if label == "principal"
                    else "Descargar CSV de referencia ficticio",
                    raw,
                    name,
                    "text/csv",
                    key=key("sample_" + label),
                    on_click="ignore",
                )
        else:
            st.download_button(
                "Descargar plantilla de cotejo",
                observations_csv(()),
                "plantilla_cotejo.csv",
                "text/csv",
                key=key("template"),
                on_click="ignore",
            )
            left = st.file_uploader(
                "Observaciones de la fuente principal", ["csv"], max_upload_size=2, key=key("primary")
            )
            right = st.file_uploader(
                "Observaciones de la fuente de referencia", ["csv"], max_upload_size=2, key=key("reference")
            )
            primary, reference = (left.getvalue() if left else None), (right.getvalue() if right else None)
        st.write("**Umbrales en puntos base**")
        options = st.columns(3)
        tolerances = {
            kind: str(
                col.number_input(
                    TYPES[kind] + " · pb",
                    0.0,
                    10000.0,
                    default,
                    0.1,
                    key=key("tolerance_" + kind),
                    format="%.2f",
                )
            )
            for col, (kind, default) in zip(options, zip(TYPES, (1.0, 10.0, 5.0), strict=True), strict=True)
        }
        signature = analysis_key(primary, reference, mode, tolerances, fingerprint())
        permitted = mode == "Práctica ficticia"
        if not permitted and primary and reference:
            permitted = st.checkbox(
                "Confirmo que puedo cotejar ambos archivos y documenté su origen",
                key=key("rights_" + analysis_key(primary, reference)[:16]),
            )
        stored = st.session_state.get(result_key)
        if stored and (stored["signature"] != signature or not permitted):
            st.session_state.pop(result_key)
            stored = None
        col, clear = st.columns(2)
        if col.button(
            "Cotejar observaciones", key=key("compare"), disabled=not (primary and reference and permitted)
        ):
            if stored is None:
                try:
                    report = compare_observations(primary, reference, tolerances)
                except PortfolioError as error:
                    st.text(str(error))
                else:
                    report.update(engine_sha256=fingerprint(), practice=mode == "Práctica ficticia")
                    stored = {"signature": signature, "report": report}
                    st.session_state[result_key] = stored
        clear.button("Vaciar cotejo", key=key("clear"), on_click=_reset, args=(result_key, generation_key))
        if stored:
            _result(stored["report"], key)
        else:
            st.caption(
                "El cotejo se prepara al pulsar Cotejar observaciones. Conserva ambos CSV para retomarlo."
            )
