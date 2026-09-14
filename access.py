"""Fail-closed OIDC authorization; identity is issuer + subject, never email alone."""

import json
import math
import time

import streamlit as st


def session_valid(claims, now=None):
    now = time.time() if now is None else now
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= now:
        return False
    return True


def authorized(claims, policy, now=None):
    if not session_valid(claims, now):
        return False
    return any(
        entry.get("issuer") == claims.get("iss")
        and entry.get("subject") == claims.get("sub")
        and bool(entry.get("issuer"))
        and bool(entry.get("subject"))
        for entry in policy.get("identities", [])
    )


def require_access():
    try:
        policy = st.secrets.get("access", {})
        configured = bool(st.secrets.get("auth", {}))
    except FileNotFoundError:
        policy, configured = {}, False
    if not configured:
        st.error("Acceso pendiente de configuración por el administrador.")
        st.stop()
    if not st.user.is_logged_in:
        if st.button("Iniciar sesión"):
            st.login()
        st.stop()
    claims = st.user.to_dict()
    if not authorized(claims, policy):
        if not session_valid(claims):
            st.error("La sesión expiró o no contiene una expiración válida. Cierra sesión e inicia de nuevo.")
        else:
            st.error("Tu cuenta inició sesión, pero todavía no está autorizada para usar esta aplicación.")
            issuer, subject = claims.get("iss"), claims.get("sub")
            if isinstance(issuer, str) and isinstance(subject, str) and issuer and subject:
                identity = (
                    "[[access.identities]]\n"
                    f"issuer = {json.dumps(issuer)}\n"
                    f"subject = {json.dumps(subject)}"
                )
                st.error(
                    "Si administras esta aplicación, añade este bloque al final de Settings > Secrets "
                    "en Streamlit, conservando la configuración existente. "
                    "Este bloque identifica únicamente tu cuenta; no concede acceso automáticamente.\n\n"
                    f"```toml\n{identity}\n```"
                )
            else:
                st.error("El proveedor no entregó un identificador de cuenta válido.")

        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.logout()
        st.stop()
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.clear()
        st.logout()
        st.stop()
