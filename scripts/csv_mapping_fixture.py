"""Public, invented CSV and its explicit practice-only correspondence."""

from csv_mapping import blank_mapping, read_source, write_template
from transaction_ledger import COLUMNS


def fictional_csv():
    headers = [
        "folio",
        "operacion",
        "liquidacion",
        "clase",
        "activo",
        "divisa",
        "titulos",
        "precio",
        "bruto",
        "comision",
        "impuesto",
        "referencia",
        "momento",
        "interes",
    ]
    raw = (
        ",".join(headers) + "\n"
        "sim-a,2026-01-01,2026-01-01,Apertura,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
        "sim-b,2026-01-05,2026-01-05,Aportacion,,MXN,0,0,50,0,0,,EOD,0\n"
        "sim-c,2026-01-06,2026-01-06,Comision,,MXN,0,0,1,0,0,,UNKNOWN,0\n"
    ).encode()
    config = blank_mapping(headers)
    config["fields"] = {
        f: {"mode": "column", "value": h, "transform": "identity"}
        for f, h in zip(COLUMNS, headers, strict=True)
    }
    config["values"]["Tipo"] = {"Apertura": "OPEN_CASH", "Aportacion": "DEPOSIT", "Comision": "FEE"}
    config["basis"] = "Fuente: datos inventados SIM-CSV; correspondencia exclusiva de esta práctica."
    return raw, write_template(config, read_source(raw))
