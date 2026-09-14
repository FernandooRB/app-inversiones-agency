"""Fail-closed OIDC authorization; identity is issuer + subject, never email alone."""

import math
import time

import streamlit as st


def authorized(claims, policy, now=None):
    now = time.time() if now is None else now
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= now:
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
    if not authorized(st.user.to_dict(), policy):
        st.error("Esta identidad no tiene acceso o su sesión expiró.")
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.logout()
        st.stop()
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.clear()
        st.logout()
        st.stop()
