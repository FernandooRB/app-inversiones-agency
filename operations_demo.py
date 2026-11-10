"""Deterministic fictional review inputs. No market data, accounts, or external services."""

from urllib.parse import urlsplit, urlunsplit

DEMO_CONTEXT = "operations-demo"
DEMO_CUTOFF = "2026-01-10"
DEMO_NAV_COMPLETE = b"Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,150\n"
DEMO_NAV_INVALID = b"Fecha,NAV\nNaT,100\n2026-01-10,150\n"


def demo_url(current_url):
    base = urlsplit(current_url or "")
    return urlunsplit((base.scheme, base.netloc, base.path, "demo_operacion=1", ""))


def demo_operations():
    """Fresh dictionaries; source bytes stay reproducible across sessions and resets."""
    files = {
        "ledger": (
            b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
            b"Referencia,MomentoFlujo,Interes\n"
            b"demo-opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
            b"demo-deposit,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n"
        ),
        "controls": (
            b"Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente\n"
            b"2026-01-10,CASH,,MXN,150.01,Control ficticio SIG para practica\n"
        ),
        "nav": b"Fecha,NAV\n2026-01-01,100\n2026-01-10,150\n",
    }
    return files, {"cutoff": DEMO_CUTOFF, "base": "MXN"}
