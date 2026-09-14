"""Compare explicitly supplied USD/MXN references on identical observation dates."""

import io

import numpy as np
import pandas as pd
import streamlit as st

from portfolio_core import (
    PortfolioError,
    annualized_moments,
    calculate_returns,
    calculate_risk_metrics,
    optimize_portfolio,
    portfolio_statistics,
)


def read_reference(data):
    if len(data) > 1_000_000:
        raise PortfolioError("El CSV de referencia debe ocupar menos de 1 MB.")
    try:
        frame = pd.read_csv(io.BytesIO(data), dtype=str)
        if list(frame.columns) != ["Date", "USDMXN"]:
            raise ValueError("columns")
        if not frame["Date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            raise ValueError("dates")
        index = pd.to_datetime(frame["Date"], format="%Y-%m-%d", errors="raise")
        values = pd.to_numeric(frame["USDMXN"], errors="raise").to_numpy()
        if index.duplicated().any() or not len(values) or not np.isfinite(values).all():
            raise ValueError("values")
        if (values <= 0).any():
            raise ValueError("positive")
        return pd.Series(values, index=pd.DatetimeIndex(index), name="Referencia").sort_index()
    except (ValueError, KeyError, UnicodeError, pd.errors.ParserError) as exc:
        raise PortfolioError(
            "CSV inválido: columnas Date,USDMXN; fechas YYYY-MM-DD únicas y tasas positivas."
        ) from exc


def compare_series(prices, yahoo, reference):
    dates = prices.index.intersection(yahoo.dropna().index).intersection(reference.index).sort_values()
    if not len(dates):
        raise PortfolioError("La referencia no tiene fechas comunes con el análisis.")
    table = pd.DataFrame({"Yahoo": yahoo.reindex(dates), "Referencia": reference.reindex(dates)})
    if not np.isfinite(table.to_numpy()).all() or (table <= 0).any().any():
        raise PortfolioError("Las tasas deben ser positivas y finitas.")
    table["Diferencia relativa"] = table["Yahoo"] / table["Referencia"] - 1
    original = prices.reindex(dates)
    return table, original.mul(table["Yahoo"], axis=0), original.mul(table["Referencia"], axis=0)


def fixed_metrics(prices, weights, rate, confidence, horizon):
    returns = calculate_returns(prices)
    mean, covariance = annualized_moments(returns)
    ret, vol, sharpe = portfolio_statistics(weights, mean, covariance, rate)
    risk = calculate_risk_metrics(returns, weights, confidence, horizon)
    return {
        "Media anualizada": ret,
        "Volatilidad anualizada": vol,
        "Sharpe": sharpe,
        "VaR histórico": risk.historical_var,
        "CVaR histórico": risk.historical_cvar,
    }


def render_comparison(prices, quotes, base, fx, weights, rate, cap, confidence, horizon):
    with st.expander("Contraste cambiario independiente: USD/MXN"):
        st.caption(
            "Compara referencias con horarios y metodologías identificados. "
            "Una diferencia no demuestra por sí sola un error. El PDF principal conserva Yahoo."
        )
        if base != "MXN" or set(quotes.values()) != {"USD"}:
            st.info("Esta comparación admite por ahora activos cotizados en USD con moneda base MXN.")
            return
        source = st.text_input("Fuente de referencia y enlace", max_chars=500)
        method = st.text_input(
            "Método, hora de observación y zona horaria de la referencia", max_chars=500
        )
        st.caption(
            "CSV con columnas Date,USDMXN; fechas YYYY-MM-DD y pesos por dólar. "
            "Utiliza la fecha de observación, no la de publicación. No se rellenan huecos."
        )
        upload = st.file_uploader("Serie de referencia CSV", type=["csv"])
        if upload is None:
            return
        if not source.strip() or not method.strip():
            st.info("Identifica la fuente y su convención temporal para comparar.")
            return
        try:
            reference = read_reference(upload.getvalue())
            table, baseline, alternative = compare_series(prices, fx["USDMXN=X"], reference)
            st.write(
                f"Fechas comunes: {len(table)}; de {table.index.min().date()} "
                f"a {table.index.max().date()}. Precios originales excluidos: {len(prices) - len(table)}."
            )
            st.dataframe(table.style.format({
                "Yahoo": "{:.6f}", "Referencia": "{:.6f}", "Diferencia relativa": "{:.2%}",
            }))
            st.download_button(
                "Descargar diferencias CSV", table.to_csv().encode("utf-8"),
                "contraste_fx.csv", "text/csv",
            )
            if len(table) < 60:
                st.info("Contraste puntual disponible. El riesgo requiere 60 fechas comunes.")
                return
            st.caption(
                "Sensibilidad con los mismos pesos y fechas en ambas fuentes. "
                "Los retornos entre fechas comunes pueden abarcar varias sesiones si hay huecos."
            )
            metrics = pd.DataFrame({
                "Yahoo (muestra común)": fixed_metrics(baseline, weights, rate, confidence, horizon),
                "Referencia (muestra común)": fixed_metrics(alternative, weights, rate, confidence, horizon),
            })
            st.dataframe(metrics)
            allocations = {}
            for label, series in [("Yahoo", baseline), ("Referencia", alternative)]:
                mean, covariance = annualized_moments(calculate_returns(series))
                allocations[label] = optimize_portfolio(mean, covariance, rate, max_weight=cap).weights
            st.write("Pesos de máximo Sharpe reoptimizados por fuente sobre las mismas fechas:")
            st.dataframe(pd.DataFrame(allocations, index=prices.columns).style.format("{:.2%}"))
            st.caption(
                "Métricas porcentuales expresadas como fracción (0.10 = 10%); Sharpe es adimensional. "
                "Referencia del usuario; autenticidad y sincronización sin verificación automática."
            )
        except PortfolioError as exc:
            st.error(str(exc))
