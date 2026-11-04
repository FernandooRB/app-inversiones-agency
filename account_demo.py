"""Fictional local-market inputs for the account workflow; no real ticker quotes."""

from datetime import date

import numpy as np
import pandas as pd

from data_rights import RIGHTS_COLUMNS
from portfolio_exposure import COMPONENT_COLUMNS


def demo_account():
    dates = pd.bdate_range(end=date.today(), periods=260)
    assets = ("SIM-A", "SIM-B", "SIM-F")
    rng = np.random.default_rng(138)
    prices = pd.DataFrame(
        100
        * np.exp(
            np.cumsum(rng.normal([0.0003, 0.0002, 0.00025], [0.01, 0.008, 0.009], (len(dates), 3)), axis=0)
        ),
        index=dates,
        columns=assets,
    )
    prices.index.name = "Fecha"
    as_of = dates[-1].date().isoformat()
    rights = (
        ",".join(RIGHTS_COLUMNS)
        + "\n"
        + (
            f"Series ficticias SIG,Demostración propia,Simulado,{date.today()},,CONFIRMADO,"
            "INVESTIGACION_INTERNA,AJUSTADO,Cierre ficticio,Generación sintética propia\n"
        )
    )
    components = pd.DataFrame(
        [
            [
                "SIM-F",
                "SIM-A",
                0.6,
                "Emisor ficticio A",
                "Tecnología ficticia",
                "México",
                "MXN",
                as_of,
                "Ejemplo ficticio",
            ],
            [
                "SIM-F",
                "SIM-B",
                0.3,
                "Emisor ficticio B",
                "Consumo ficticio",
                "México",
                "MXN",
                as_of,
                "Ejemplo ficticio",
            ],
        ],
        columns=COMPONENT_COLUMNS,
    )
    metadata = {
        "SIM-A": {
            "Tipo": "Acción",
            "Emisor": "Emisor ficticio A",
            "Sector": "Tecnología ficticia",
            "Pais": "México",
            "Moneda": "MXN",
            "Fuente": "Ejemplo ficticio",
        },
        "SIM-B": {
            "Tipo": "Acción",
            "Emisor": "Emisor ficticio B",
            "Sector": "Consumo ficticio",
            "Pais": "México",
            "Moneda": "MXN",
            "Fuente": "Ejemplo ficticio",
        },
        "SIM-F": {"Tipo": "ETF/Fondo"},
    }
    files = {
        "holdings": (
            f"FechaCorte,Instrumento,ValorMXN\n{as_of},SIM-A,40000\n"
            f"{as_of},SIM-B,30000\n{as_of},SIM-F,30000\n"
        ).encode(),
        "prices": prices.to_csv(date_format="%Y-%m-%d").encode(),
        "rights": rights.encode(),
        "components": components.to_csv(index=False).encode(),
    }
    return (
        files,
        metadata,
        {
            "as_of": as_of,
            "history_start": dates[0].date().isoformat(),
            "assets": assets,
            "outside_cash": 5000.0,
            "objective": "Demostración ficticia",
        },
    )
