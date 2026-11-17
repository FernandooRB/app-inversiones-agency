"""Two fictitious accounts; never read original statements or secrets."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations_consolidation_bundle import build_bundle
from operations_cuts import build_cut
from transaction_ledger import Event, book_at, value_book

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
day = date(2026, 1, 10)
entries = []
for alias, amount, currency in (("Cuenta1", "100.01", "MXN"), ("Cuenta2", "10", "USD")):
    events = [Event(alias + "-opening", day, day, "OPEN_CASH", currency=currency, amount=Decimal(amount))]
    valuation = value_book(book_at(events, day), {}, {}, base=currency, raw_prices_confirmed=True)
    raw = build_cut(events, cutoff=day.isoformat(), base=currency, valuation=valuation)
    entries.append({"alias": alias, "source": "Cuenta propia ficticia " + alias, "cut": raw})
    (folder / (alias + ".cut.json")).write_bytes(raw)
fx = b"Fecha,Moneda,Base,Tasa,Fuente\n2026-01-10,USD,MXN,20.01,Cierre ficticio\n"
(folder / "group_fx.csv").write_bytes(fx)
(folder / "group_fixture.zip").write_bytes(build_bundle(entries, fx=fx))
(folder / "group_invalid.zip").write_bytes(b"Not a real archive; fictional rejection fixture")
