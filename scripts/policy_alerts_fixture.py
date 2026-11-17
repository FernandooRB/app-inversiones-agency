"""Fictional policy/holdings for native browser verification only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations_review import build_operations_review

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
ledger = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,Referencia,MomentoFlujo,Interes\n"
    b"cash,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,40,0,0,,UNKNOWN,0\n"
    b"pos,2026-01-01,2026-01-01,OPEN_POSITION,AAA,MXN,6,0,0,0,0,,UNKNOWN,0\n"
)
quotes = b"Fecha,Instrumento,Moneda,Precio\n2026-01-10,AAA,MXN,10\n"
_, raw = build_operations_review({"ledger": ledger, "quotes": quotes}, cutoff="2026-01-10", base="MXN")
(out / "policy_fixture_v1.zip").write_bytes(raw)
