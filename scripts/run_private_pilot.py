"""Reproducible two-cut pilot. Originals remain untouched; output omits private values."""

import argparse
import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from gbm_documents import read_cfdi_evidence, read_statement


def run_pilot(previous: Path, current: Path, cfdi: list[Path] | None = None) -> dict:
    raw = [path.read_bytes() for path in (previous, current)]
    before, after = [read_statement(value) for value in raw]
    same = before["contract"] == after["contract"]
    contiguous = before["end"] == after["start"]
    continuity = before["closing_total"] == after["opening_total"]
    prior_quantities = {row["Instrumento"]: Decimal(row["Cantidad"]) for row in before["positions"]}
    next_quantities = {row["Instrumento"]: Decimal(row["CantidadAnterior"]) for row in after["positions"]}
    quantity_continuity = all(
        prior_quantities.get(key, Decimal(0)) == next_quantities.get(key, Decimal(0))
        for key in set(prior_quantities) | set(next_quantities)
    )
    documents = []
    for path in cfdi or []:
        evidence = read_cfdi_evidence(path.read_bytes())
        documents.append({key: evidence[key] for key in ("sha256", "checks", "status")})
    return {
        "alias": "Piloto propio GBM BMV",
        "schema": 1,
        "periods": [[item["start"], item["end"]] for item in (before, after)],
        "same_contract": same,
        "contiguous_cuts": contiguous,
        "total_continuity_exact": continuity,
        "quantity_continuity_exact": quantity_continuity,
        "statements": [
            {
                "sha256": item["sha256"],
                "positions": len(item["positions"]),
                "movement_candidates": len(item["movement_candidates"]),
                "checks": item["checks"],
                "warnings": item["warnings"],
            }
            for item in (before, after)
        ],
        "cfdi": documents,
        "code_sha256": sha256(Path("gbm_documents.py").read_bytes()).hexdigest(),
        "code_hashes": {
            name: sha256(Path(name).read_bytes()).hexdigest()
            for name in ("gbm_documents.py", "scripts/inspect_gbm_intake.py", "scripts/run_private_pilot.py")
        },
        "status": "REQUIERE_REVISION_HUMANA"
        if same and contiguous and continuity and quantity_continuity
        else "BLOQUEADO",
        "limits": "No confirma ISIN, mercado, fechas de liquidación, CFDI contra cargos ni rendimiento.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--cfdi", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_pilot(args.previous, args.current, args.cfdi)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "alias",
                    "periods",
                    "same_contract",
                    "contiguous_cuts",
                    "total_continuity_exact",
                    "status",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
