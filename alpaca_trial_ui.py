"""Trial budgets, prospective exit plans and in-app alerts using the established SIG screen."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from alpaca_alerts import active_alerts, observation, observation_key
from alpaca_paper import AlpacaPaperError
from alpaca_risk import plan_payload, settings_payload
from alpaca_trial_store import exit_plans, latest, stable_key, trial_store_for
from technical_analysis import STRATEGY_VERSION, UNAVAILABLE, MarketHistory, analyze_history


def render_trial_controls(
    watchlist,
    issuer,
    subject,
    snapshot,
    *,
    client_loader,
    expected_signature,
    symbols=(),
    history_loader=None,
):
    st.subheader("Control de la prueba")
    st.caption("Cuenta Paper · USD · límites guardados por usuario y cuenta")
    store = trial_store_for(watchlist)
    try:
        events = store.load(issuer, subject, snapshot.account.id)
    except AlpacaPaperError as exc:
        st.error(str(exc))
        return

    def current_client():
        current = client_loader()
        if current.configuration_signature != expected_signature:
            raise AlpacaPaperError("La conexión cambió; vuelve a consultar la cuenta.")
        return current

    notice = st.session_state.pop("_technical_alpaca_trial_notice", None)
    if notice:
        st.success(notice)
    settings = latest(events, "settings")
    cfg = settings.payload if settings else {}
    if settings is None:
        st.info(
            "Define los límites y un plan de salida antes de preparar otra compra. "
            "Las ventas para reducir posiciones conservan su confirmación manual."
        )
    with st.expander("Capital, pérdida prevista y costos", expanded=settings is None):
        with st.form("technical_alpaca_order_budget_form"):
            capital = st.number_input(
                "Capital asignado · USD",
                min_value=0.0,
                value=float(cfg.get("capital", 0)),
                key="technical_alpaca_order_budget_capital",
            )
            loss = st.number_input(
                "Presupuesto de pérdida prevista · USD",
                min_value=0.0,
                value=float(cfg.get("max_loss", 0)),
                key="technical_alpaca_order_budget_loss",
            )
            position = st.number_input(
                "Límite por acción · USD",
                min_value=0.0,
                value=float(cfg.get("max_position", 0)),
                key="technical_alpaca_order_budget_position",
            )
            order_loss = st.number_input(
                "Pérdida prevista máxima por nueva orden · USD",
                min_value=0.0,
                value=float(cfg.get("max_order_loss", 0)),
                key="technical_alpaca_order_budget_order_loss",
            )
            costs = st.number_input(
                "Fricción supuesta por lado (%)",
                min_value=0.0,
                max_value=10.0,
                value=100 * float(cfg.get("cost_rate", "0.0035")),
                step=0.05,
                key="technical_alpaca_order_budget_cost",
            )
            st.caption(
                "Supuesto inicial 0.35 %: costo 0.25 % + escenario adicional de deslizamiento 0.10 %. "
                "El neto estimado aplica este supuesto a los precios ejecutados; no representa cargos "
                "confirmados del broker. El presupuesto usa la pérdida prevista al stop y los cierres "
                "netos desde el inicio de la prueba. Un salto de precio puede superar esa previsión."
            )
            if st.form_submit_button("Guardar límites de la prueba"):
                try:
                    current_client()
                    payload = settings_payload(
                        capital,
                        loss,
                        position,
                        order_loss,
                        str(costs / 100),
                        started_at=cfg.get("started_at"),
                    )
                    store.append(issuer, subject, snapshot.account.id, "settings", payload)
                    st.session_state["_technical_alpaca_trial_notice"] = (
                        "Límites guardados con nueva revisión."
                    )
                    st.rerun()
                except AlpacaPaperError as exc:
                    st.error(str(exc))
    plans = exit_plans(events)
    with st.expander("Plan de salida por posición", expanded=bool(snapshot.positions) and not plans):
        st.caption(
            "Cada revisión se guarda con la fecha actual. El plan se evalúa independientemente de "
            "la señal y fija referencias; las órdenes stop/objetivo se gestionan en el panel del broker."
        )
        choices = list(dict.fromkeys([p.symbol for p in snapshot.positions] + list(symbols) + list(plans)))
        symbol = st.selectbox(
            "Acción para el plan", choices or ["Otro símbolo"], key="technical_alpaca_order_plan_symbol"
        )
        if symbol == "Otro símbolo":
            symbol = st.text_input("Símbolo del plan", key="technical_alpaca_order_plan_custom")
        previous = plans.get(symbol)
        payload = previous.payload if previous else {}
        position = next((p for p in snapshot.positions if p.symbol == symbol), None)
        reference = float(
            payload.get(
                "reference", position.current_price if position and position.current_price is not None else 0
            )
        )
        if position and position.current_price is not None:
            st.caption(f"Precio consultado de {symbol}: {position.current_price:,.2f} USD · "
                       f"{snapshot.fetched_at:%Y-%m-%d %H:%M} UTC.")
        with st.form("technical_alpaca_order_plan_form"):
            price = st.number_input(
                "Precio de referencia del plan · USD",
                min_value=0.0,
                value=reference,
                key=f"technical_alpaca_order_plan_reference_{symbol}",
            )
            stop = st.number_input(
                "Stop de referencia · USD",
                min_value=0.0,
                value=float(payload.get("stop", 0)),
                key=f"technical_alpaca_order_plan_stop_{symbol}",
            )
            target = st.number_input(
                "Objetivo de referencia · USD",
                min_value=0.0,
                value=float(payload.get("target", 0)),
                key=f"technical_alpaca_order_plan_target_{symbol}",
            )
            today = datetime.now(ZoneInfo("America/New_York")).date()
            review = st.date_input(
                "Fecha de revisión obligatoria",
                value=max(today, date.fromisoformat(payload["review_on"]))
                if previous else today + timedelta(days=20),
                min_value=today,
                key=f"technical_alpaca_order_plan_review_{symbol}",
            )
            reason = st.text_area(
                "Motivo y criterio de salida",
                value=payload.get("reason", ""),
                key=f"technical_alpaca_order_plan_reason_{symbol}",
            )
            if st.form_submit_button("Guardar plan de salida"):
                try:
                    current_client()
                    store.append(
                        issuer,
                        subject,
                        snapshot.account.id,
                        "plan",
                        plan_payload(symbol, price, stop, target, review, reason),
                    )
                    st.session_state["_technical_alpaca_trial_notice"] = (
                        "Plan de salida guardado con su fecha."
                    )
                    st.rerun()
                except AlpacaPaperError as exc:
                    st.error(str(exc))
        if plans:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Acción": p.payload["symbol"],
                            "Stop · USD": float(p.payload["stop"]),
                            "Objetivo · USD": float(p.payload["target"]),
                            "Revisar antes de": p.payload["review_on"],
                            "Registrado UTC": p.recorded_at,
                            "Protección": "Referencia guardada",
                        }
                        for p in plans.values()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    _render_alerts(store, issuer, subject, snapshot, current_client, symbols, history_loader)


def _render_alerts(store, issuer, subject, snapshot, current_client, symbols, history_loader):
    st.subheader("Alertas de la prueba")
    auto = st.toggle(
        "Consultar precios cada 60 segundos con la app abierta",
        value=False,
        key="technical_alpaca_order_alert_auto",
    )

    @st.fragment(run_every=60 if auto else None)
    def panel():
        try:
            client = current_client()
        except AlpacaPaperError:
            st.rerun(scope="app")
        current = st.session_state.get("_technical_alpaca_snapshot", snapshot)
        if auto:
            try:
                current = client.fetch_snapshot()
                if current.account.id != snapshot.account.id:
                    st.rerun(scope="app")
                st.session_state["_technical_alpaca_snapshot"] = current
            except AlpacaPaperError as exc:
                st.warning(str(exc))
        try:
            events = store.load(issuer, subject, current.account.id)
            if st.button(
                "Actualizar señales y alertas",
                disabled=history_loader is None,
                key="technical_alpaca_order_alert_refresh",
            ):
                st.session_state["_technical_alpaca_history_refresh"] = uuid4().hex
                current = client.fetch_snapshot()
                if current.account.id != snapshot.account.id:
                    raise AlpacaPaperError("La cuenta cambió; vuelve a conectar.")
                st.session_state["_technical_alpaca_snapshot"] = current
                with st.spinner("Evaluando sesiones terminadas y guardando observaciones…"):
                    for symbol in symbols:
                        try:
                            history = history_loader(symbol)
                            if not isinstance(history, MarketHistory):
                                raise AlpacaPaperError("El proveedor no confirmó precios y metadatos.")
                            row = observation(history, analyze_history(history, datetime.now(UTC)))
                        except Exception:
                            row = {
                                "symbol": symbol,
                                "session": "",
                                "signal": UNAVAILABLE,
                                "reason": "No se pudo actualizar esta acción; revisa su fuente.",
                                "fetched_at": datetime.now(UTC).isoformat(),
                                "strategy_version": STRATEGY_VERSION,
                                "currency": "",
                            }
                        store.append(
                            issuer, subject, current.account.id, "observation", row, key=observation_key(row)
                        )
                events = store.load(issuer, subject, current.account.id)
            observations = {}
            for event in events:
                if event.kind == "observation":
                    observations[event.payload["symbol"]] = event.payload
            alerts = active_alerts(current, events, list(observations.values()))
            existing = {e.key for e in events if e.kind == "alert"}
            for alert in alerts:
                if alert["key"] not in existing:
                    store.append(issuer, subject, current.account.id, "alert", alert, key=alert["key"])
            events = store.load(issuer, subject, current.account.id)
            acknowledgements = {e.payload["alert_key"] for e in events if e.kind == "ack"}
            unread = [a for a in alerts if a["key"] not in acknowledgements]
            st.caption(
                f"{len(unread)} {'alerta vigente' if len(unread) == 1 else 'alertas vigentes'} "
                "sin revisar · precios consultados "
                f"{current.fetched_at:%Y-%m-%d %H:%M:%S} UTC. "
                "Las señales se recalculan con el botón; los avisos permanecen dentro de la app."
            )
            if unread:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Acción": a["symbol"], "Prioridad": a["severity"], "Aviso": a["message"]}
                            for a in unread
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                selection = st.selectbox(
                    "Alerta revisada",
                    [a["key"] for a in unread],
                    format_func=lambda key: next(
                        a["symbol"] + " · " + a["message"][:90] for a in unread if a["key"] == key
                    ),
                    key="technical_alpaca_order_alert_selected",
                )
                st.write(next(a["message"] for a in unread if a["key"] == selection))
                if st.button("Marcar revisada", key="technical_alpaca_order_alert_ack"):
                    current_client()
                    store.append(
                        issuer,
                        subject,
                        current.account.id,
                        "ack",
                        {"alert_key": selection},
                        key=stable_key("ack", selection),
                    )
                    st.rerun(scope="app")
            else:
                st.info("No hay alertas vigentes pendientes de revisión con los datos consultados.")
            history = [e for e in events if e.kind == "alert"]
            if history:
                with st.expander("Historial de alertas"):
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Fecha UTC": e.recorded_at,
                                    "Acción": e.payload["symbol"],
                                    "Aviso": e.payload["message"],
                                    "Revisada": e.key in acknowledgements,
                                }
                                for e in reversed(history)
                            ]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
        except AlpacaPaperError as exc:
            st.error(str(exc))

    panel()
