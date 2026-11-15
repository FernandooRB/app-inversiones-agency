"""Prepare an unapproved portfolio proposal from the current account's ledger."""

from datetime import date
from hashlib import sha256

import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_proposal_bridge import proposal_book, proposal_code_fingerprints, proposal_inputs
from operations_review import review_code_fingerprints
from operations_review_ui import current_review_files, review_key
from portfolio_core import PortfolioError


def _key(name):
    return name + "_" + st.session_state.get("_ops_context_key", "temporary")


def prepare_book_proposal():
    raw = current_review_files().get("ledger")
    reference = st.session_state.get(_key("_ops_last_book"))
    valid = raw is not None and reference and reference.get("ledger_sha256") == sha256(raw).hexdigest()
    base_signature = (
        analysis_key(
            review_key("proposal"),
            raw,
            reference["cutoff"],
            review_code_fingerprints(),
            proposal_code_fingerprints(),
        )
        if valid
        else None
    )
    saved = st.session_state.get(_key("_ops_proposal_bridge"))
    if saved and saved["signature"] != base_signature:
        st.session_state.pop(_key("_ops_proposal_bridge"), None)
        saved = None
    with st.expander("Preparar desde el libro de movimientos"):
        if not valid:
            st.info(
                "Abre Movimientos y revisa un libro válido de esta cuenta "
                "antes de conectarlo con la propuesta."
            )
            return None
        cutoff = date.fromisoformat(reference["cutoff"])
        currency = st.selectbox(
            "Moneda del libro para la propuesta", ["MXN", "USD"], key=review_key("bridge_currency")
        )
        try:
            book = session_compute(
                st.session_state,
                _key("bridge_book"),
                analysis_key(base_signature, currency),
                lambda: proposal_book(raw, cutoff, currency),
                max_entries=1,
            )
        except PortfolioError as error:
            st.text(str(error))
            return None
        additional = st.text_input(
            "Instrumentos adicionales, separados por coma", key=review_key("bridge_additional")
        )
        assets = [asset for asset, _ in book["positions"]]
        assets.extend(asset.strip() for asset in additional.split(",") if asset.strip())
        if len(assets) != len(set(assets)) or len(assets) > 25:
            st.text("Revisa los instrumentos: deben ser únicos y no superar 25.")
            return None
        signature = analysis_key(base_signature, currency, assets)
        if saved and saved.get("input_signature") != signature:
            saved = None
            st.session_state.pop(_key("_ops_proposal_bridge"), None)
        st.write(f"Cierre: {cutoff} · Efectivo liquidado: {book['cash'].get(currency, 0)} {currency}")
        st.caption(
            "Los títulos y el efectivo proceden del libro. "
            "Completa precios sin ajuste, lotes y pesos objetivo "
            "con fecha y fuente. Puedes agregar instrumentos nuevos; su cantidad inicial será cero."
        )
        if not assets:
            st.info("Este libro sólo tiene efectivo. Añade arriba los instrumentos que quieras evaluar.")
            return None
        with st.form(review_key("bridge_form") + signature[:12]):
            rows = []
            for asset in assets:
                st.text(f"{asset} · Títulos del libro: {book['positions'].get((asset, currency), 0)}")
                left, right = st.columns(2)
                rows.append(
                    {
                        "Instrumento": asset,
                        "Fecha": str(cutoff),
                        "Precio": left.text_input("Precio sin ajuste · " + asset),
                        "Lote": right.text_input("Lote · " + asset),
                        "PesoObjetivo": left.text_input("Peso objetivo entre 0 y 1 · " + asset),
                        "Fuente": right.text_input("Fuente de precio y lote · " + asset),
                    }
                )
            checked = st.checkbox(
                "Cotejé títulos, efectivo liquidado, precios, lotes y pesos con sus fuentes"
            )
            if st.form_submit_button("Usar libro para preparar propuesta"):
                saved = None
                st.session_state.pop(_key("_ops_proposal_bridge"), None)
                try:
                    prepared = proposal_inputs(
                        raw, cutoff=cutoff, currency=currency, market_rows=rows, confirmed=checked
                    )
                    saved = {"signature": base_signature, "input_signature": signature, "data": prepared}
                    st.session_state[_key("_ops_proposal_bridge")] = saved
                    st.session_state[_key("proposal_origin")] = "Libro de movimientos"
                except PortfolioError as error:
                    st.text(str(error))
        if saved:
            st.success("Posiciones y efectivo preparados. Revisa los costos y límites antes de calcular.")
            st.caption("Libro de origen · SHA-256 " + saved["data"]["ledger_sha256"])
    return saved["data"] if saved else None
