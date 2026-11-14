"""Source-backed CSV completion; form edits use the same readers as uploaded inputs."""

import csv
from datetime import date
from io import StringIO

import streamlit as st

from operations_review_ui import review_key, save_review_input
from portfolio_core import PortfolioError
from transaction_ledger import decimal

FORMATS = {
    "nav": ("Valuación histórica", ("Fecha", "NAV", "Fuente"), ("Fecha",)),
    "quotes": (
        "Cotización de cierre",
        ("Fecha", "Instrumento", "Moneda", "Precio", "Fuente"),
        ("Fecha", "Instrumento", "Moneda"),
    ),
    "fx": ("FX del cierre", ("Fecha", "Moneda", "Base", "Tasa", "Fuente"), ("Fecha", "Moneda", "Base")),
    "flow_fx": ("FX de un flujo", ("Fecha", "Moneda", "Base", "Tasa", "Fuente"), ("Fecha", "Moneda", "Base")),
    "repo_values": (
        "Valor total de reporto",
        ("Fecha", "Referencia", "Moneda", "Valor", "Fuente"),
        ("Fecha", "Referencia", "Moneda"),
    ),
    "controls": (
        "Control del cierre",
        ("Fecha", "Tipo", "InstrumentoReferencia", "Moneda", "Saldo", "Fuente"),
        ("Fecha", "Tipo", "InstrumentoReferencia", "Moneda"),
    ),
}


def upsert_input(role, raw, entry):
    _, fields, identity = FORMATS[role]
    if set(entry) != set(fields) or any(
        not isinstance(v, str) or len(v) > 500 or any(ord(c) < 32 for c in v) for v in entry.values()
    ):
        raise PortfolioError("Completa los campos sin caracteres de control.")
    if any(not entry[k].strip() for k in fields if k != "InstrumentoReferencia"):
        raise PortfolioError("Cada dato requiere sus campos completos y una fuente.")
    if any(
        entry[key].lstrip().startswith(("=", "+", "-", "@"))
        for key in ("Instrumento", "Referencia", "InstrumentoReferencia", "Fuente")
        if key in entry
    ):
        raise PortfolioError("Las referencias y fuentes no admiten prefijos de fórmula de hoja de cálculo.")
    try:
        if date.fromisoformat(entry["Fecha"]) > date.today():
            raise ValueError
    except ValueError:
        raise PortfolioError("Declara una fecha válida, sin fechas futuras.") from None
    if any(entry[k] not in {"MXN", "USD"} for k in ("Moneda", "Base") if k in entry):
        raise PortfolioError("La moneda debe ser MXN o USD.")
    for key in ("NAV", "Precio", "Tasa", "Valor", "Saldo"):
        if key in entry and decimal(entry[key]) <= 0 and key != "Saldo":
            raise PortfolioError("La valuación o tasa debe ser positiva.")
    if "Saldo" in entry:
        decimal(entry["Saldo"])
        if entry["Tipo"] not in {"CASH", "PENDING", "POSITION", "REPO"}:
            raise PortfolioError("El tipo de control no es válido.")
    rows = []
    if raw:
        if len(raw) > 2_000_000:
            raise PortfolioError("El CSV supera 2 MB.")
        try:
            reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
            previous = tuple(reader.fieldnames or ())
            if not set(previous).issubset(fields) or set(fields) - set(previous) - {"Fuente"}:
                raise ValueError
            for row in reader:
                if None in row or any(v is None for v in row.values()) or len(rows) >= 20000:
                    raise ValueError
                rows.append({key: row.get(key, "") for key in fields})
        except (UnicodeError, ValueError, csv.Error):
            raise PortfolioError("Revisa el CSV existente antes de completarlo con el formulario.") from None
    matches = [i for i, row in enumerate(rows) if all(row[k] == entry[k] for k in identity)]
    if len(matches) > 1:
        raise PortfolioError("El CSV tiene claves duplicadas; resuélvelas antes de editar.")
    if matches:
        rows[matches[0]] = dict(entry)
    else:
        rows.append(dict(entry))
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    result = output.getvalue().encode()
    if len(result) > 2_000_000:
        raise PortfolioError("El CSV resultante supera 2 MB.")
    return result


def complete_input(role, upload, *, day):
    label, fields, _ = FORMATS[role]
    with st.expander("Completar en la app · " + label):
        st.caption(
            "Guardar agrega o reemplaza el dato de la misma fecha y referencia; conserva las demás filas. "
            "Se renovarán las confirmaciones. Descarga un ZIP para conservar la versión anterior."
        )
        with st.form(review_key("form_" + role)):
            entry = {}
            columns = st.columns(2)
            for index, key in enumerate(fields):
                default = day.isoformat() if key == "Fecha" else "MXN" if key in {"Moneda", "Base"} else ""
                entry[key] = columns[index % 2].text_input(key, default)
            if st.form_submit_button("Guardar dato · " + label):
                try:
                    raw = upsert_input(role, upload.getvalue() if upload else None, entry)
                    save_review_input(role, raw)
                    st.rerun()
                except PortfolioError as error:
                    st.text(str(error))
