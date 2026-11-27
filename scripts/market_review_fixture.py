"""Invented prices, exchange rates and rates for the public comparison practice."""

import csv
from io import StringIO

from operations_market_review import MARKET_COLUMNS


def observations_csv(rows):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(MARKET_COLUMNS)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def fictional_observations():
    price = (
        "PRECIO",
        "2026-01-08",
        "SIM-A",
        "SIM-X",
        "MXN",
        "POR_TITULO",
        "Cierre sin ajuste",
        "2026-01-08T15:00:00-06:00",
        "",
        "",
    )
    fx = (
        "FX",
        "2026-01-08",
        "USD/MXN",
        "SIM-X",
        "MXN",
        "MXN_POR_USD",
        "Cierre spot ficticio",
        "2026-01-08T15:00:00-06:00",
        "",
        "",
    )
    rate = (
        "TASA",
        "2026-01-08",
        "CETE-SIM-28",
        "SIM-X",
        "MXN",
        "PORCENTAJE_ANUAL",
        "Rendimiento subasta",
        "2026-01-08T10:00:00-06:00",
        "28",
        "360",
    )
    primary_tag = ("Proveedor de práctica A", "Origen de práctica A", "Ejemplo inventado A")
    reference_tag = ("Proveedor de práctica B", "Origen de práctica B", "Ejemplo inventado B")
    price_only = (*price[:2], "SIM-B", *price[3:])
    price_other_method = (*price[:2], "SIM-C", *price[3:])
    rate_other_term = (*rate[:2], "CETE-SIM-91", *rate[3:8], "91", "360")
    primary = (
        (price, "100.01"),
        (fx, "20.04"),
        (rate, "7.05"),
        (price_only, "50.02"),
        (price_other_method, "95.01"),
        (rate_other_term, "7.1"),
    )
    reference = (
        (price, "100"),
        (fx, "20"),
        (rate, "7.00"),
        ((*price_other_method[:6], "Cierre ajustado", *price_other_method[7:]), "95.01"),
        ((*rate_other_term[:8], "90", "360"), "7.1"),
    )
    return (
        observations_csv((*fields, value, *primary_tag) for fields, value in primary),
        observations_csv((*fields, value, *reference_tag) for fields, value in reference),
    )
