"""Private Streamlit connection view for one owner's Alpaca paper account."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pandas as pd
import streamlit as st

from access import authorized
from alpaca_paper import ORDER_LIMIT, AlpacaPaperClient, AlpacaPaperError
from watchlist_store import identity_key


def configured_alpaca_paper(issuer: str, subject: str) -> AlpacaPaperClient:
    try:
        claims = st.user.to_dict()
        policy = st.secrets.get("access", {})
        config = st.secrets.get("alpaca_paper", {})
    except (FileNotFoundError, AttributeError):
        raise AlpacaPaperError("Inicia una sesión autorizada para consultar Alpaca Paper.") from None
    if (not authorized(claims, policy) or claims.get("iss") != issuer
            or claims.get("sub") != subject):
        raise AlpacaPaperError("La sesión no está autorizada o ha expirado.")
    if not isinstance(config, Mapping) or config.get("enabled") is not True:
        raise AlpacaPaperError(
            "Conexión pendiente: añade el bloque [alpaca_paper] en Settings → Secrets de Streamlit."
        )
    if (config.get("owner_issuer") != issuer or config.get("owner_subject") != subject):
        raise AlpacaPaperError("La conexión Alpaca Paper está reservada a su usuario propietario.")
    return AlpacaPaperClient(config.get("api_key", ""), config.get("secret_key", ""),
                             expected_account_id=config.get("expected_account_id", ""))


def _clear_snapshot():
    for key in ("_technical_alpaca_snapshot", "_technical_alpaca_signature"):
        st.session_state.pop(key, None)


def render_alpaca_paper(
    issuer: str, subject: str, *, client_factory: Callable | None = None,
):
    st.subheader("Alpaca Paper")
    st.caption("Cuenta de simulación · mercado estadounidense · USD · consulta manual")
    try:
        client = (client_factory or configured_alpaca_paper)(issuer, subject)
    except AlpacaPaperError as exc:
        _clear_snapshot()
        st.info(str(exc))
        st.caption("Usa las API Keys de Paper Trading. Sigue la guía para configurar la conexión.")
        st.link_button("Abrir guía de conexión", "https://github.com/FernandooRB/"
                       "app-inversiones-agency/blob/main/docs/alpaca_paper_connection.md")
        return
    signature = (identity_key(issuer, subject), client.configuration_signature)
    if st.session_state.get("_technical_alpaca_signature") != signature:
        _clear_snapshot()
        st.session_state["_technical_alpaca_signature"] = signature
    snapshot = st.session_state.get("_technical_alpaca_snapshot")
    if st.button("Actualizar cuenta" if snapshot else "Conectar y consultar", type="primary",
                 key="technical_alpaca_refresh"):
        try:
            with st.spinner("Consultando cuenta, posiciones y órdenes de simulación…"):
                snapshot = client.fetch_snapshot()
            st.session_state["_technical_alpaca_snapshot"] = snapshot
        except AlpacaPaperError as exc:
            st.error(str(exc))
            if snapshot:
                st.caption("Se conserva la última consulta correcta; estos datos no se actualizaron.")
    if snapshot is None:
        st.info("Pulsa Conectar y consultar para verificar tus credenciales Paper y recuperar la cuenta.")
        return
    account = snapshot.account
    st.write(f"**Cuenta …{account.number[-4:]} · estado {account.status}**")
    st.caption(f"Última consulta correcta: {snapshot.fetched_at:%Y-%m-%d %H:%M:%S} UTC.")
    if account.account_blocked or account.trading_blocked:
        st.warning("Alpaca informa restricciones en esta cuenta o en su negociación.")
    st.metric("Valor de la cuenta simulada · USD", f"{account.equity:,.2f}")
    cash, buying_power = st.columns(2)
    cash.metric("Efectivo simulado · USD", f"{account.cash:,.2f}")
    buying_power.metric("Poder de compra simulado · USD", f"{account.buying_power:,.2f}")
    st.caption("El poder de compra puede incluir margen y no equivale a efectivo disponible.")
    positions_tab, orders_tab = st.tabs(["Posiciones", "Órdenes recientes"])
    with positions_tab:
        count = len(snapshot.positions)
        st.write("**1 posición abierta**" if count == 1 else f"**{count} posiciones abiertas**")
        if not snapshot.positions:
            st.info("La cuenta Paper no tiene posiciones abiertas.")
        else:
            rows = pd.DataFrame([{
                "Símbolo": p.symbol, "Clase": p.asset_class, "Lado": p.side,
                "Cantidad": float(p.quantity), "Entrada media · USD": float(p.entry_price),
                "Último precio · USD": float(p.current_price) if p.current_price is not None else None,
                "Valor · USD": float(p.market_value) if p.market_value is not None else None,
                "Ganancia no realizada · USD": float(p.unrealized_pl)
                if p.unrealized_pl is not None else None,
            } for p in snapshot.positions])
            st.dataframe(rows, hide_index=True, width="stretch", height=min(260, 38 + 35 * len(rows)),
                         column_config={"Símbolo": st.column_config.TextColumn(pinned=True),
                                        **{name: st.column_config.NumberColumn(format="%.2f")
                                           for name in rows.columns if "USD" in name}})
    with orders_tab:
        st.caption(f"Hasta {ORDER_LIMIT} órdenes recientes de todos los estados; historial limitado.")
        if not snapshot.orders:
            st.info("La cuenta Paper no tiene órdenes en esta consulta.")
        else:
            rows = pd.DataFrame([{
                "Símbolo": o.symbol, "Lado": o.side, "Tipo": o.type, "Estado": o.status,
                "Cantidad": float(o.quantity) if o.quantity is not None else None,
                "Importe solicitado · USD": float(o.notional) if o.notional is not None else None,
                "Cantidad ejecutada": float(o.filled_quantity),
                "Precio ejecutado · USD": float(o.filled_price) if o.filled_price is not None else None,
                "Precio límite · USD": float(o.limit_price) if o.limit_price is not None else None,
                "Creada UTC": o.created_at, "ID": o.id,
            } for o in snapshot.orders])
            st.dataframe(rows, hide_index=True, width="stretch", height=min(260, 38 + 35 * len(rows)),
                         column_config={"Símbolo": st.column_config.TextColumn(pinned=True),
                                        **{name: st.column_config.NumberColumn(format="%.2f")
                                           for name in rows.columns if "USD" in name}})
    with st.expander("Identificación y alcance de esta conexión"):
        st.text(f"Identificador de cuenta Paper: {account.id}")
        st.caption(
            "Esta entrega consulta cuenta, posiciones y órdenes. El envío y cancelación de órdenes "
            "se habilitarán en una fase posterior. Los datos de esta cuenta no forman parte de la "
            "bitácora manual SIC/GBM ni sustituyen su precio, moneda o volumen."
        )
        st.caption(
            "La cuenta Paper y sus ejecuciones son simuladas. La conexión no cambia la fuente "
            "de los indicadores; el volumen IEX gratuito no representa todo el mercado de EE. UU."
        )
