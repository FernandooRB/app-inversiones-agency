"""Deterministic public test fixture; no provider, account or real document."""

import sys
from datetime import date
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from operations_cuts import build_cut
from operations_review import build_operations_review
from transaction_ledger import book_at, read_ledger, value_book

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
ledger = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
    b"Referencia,MomentoFlujo,Interes\n"
    b"open,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    b"buy,2026-01-02,2026-01-04,BUY,AAA,MXN,2,10,20,1,0,,UNKNOWN,0\n"
    b"sell,2026-01-05,2026-01-12,SELL,AAA,MXN,2,12,24,0,0,,UNKNOWN,0\n"
    b"div,2026-01-06,2026-01-13,DIVIDEND,AAA,MXN,0,0,3,0,.3,,UNKNOWN,0\n"
)
events = read_ledger(ledger)
valuation = value_book(book_at(events, date(2026, 1, 1)), {}, {}, raw_prices_confirmed=True)
(destination / "cuts_before.json").write_bytes(
    build_cut(
        events,
        cutoff="2026-01-01",
        base="MXN",
        valuation=valuation,
        sources={"ledger": sha256(ledger).hexdigest()},
    )
)
_, package = build_operations_review(
    {"ledger": ledger, "nav": b"Fecha,NAV\n2026-01-01,100\n2026-01-10,105.7\n"},
    cutoff="2026-01-10",
    base="MXN",
)
(destination / "cuts_fixture_v1.zip").write_bytes(package)
(destination / "cuts_altered.json").write_bytes(
    (destination / "cuts_before.json").read_bytes().replace(b'"nav":"100"', b'"nav":"101"')
)
