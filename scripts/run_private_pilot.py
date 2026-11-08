"""Reproducible two-cut pilot. Originals remain untouched; output omits private values."""

import argparse
import json
from collections import Counter
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from gbm_documents import read_cfdi_evidence, read_statement


def write_review_packets(paths: list[Path], destination: Path) -> dict:
    """Write private, row-level evidence; never convert it into approved ledger events."""
    private_root = Path(__file__).resolve().parents[1] / "data" / "private"
    if not destination.resolve().is_relative_to(private_root.resolve()):
        raise ValueError("La revisión con importes debe guardarse dentro de data/private/.")
    destination.mkdir(parents=True, exist_ok=True)
    packets = []
    for path in paths:
        draft = read_statement(path.read_bytes())
        stem = f"revision_{draft['end']}_{draft['sha256'][:12]}"
        json_path = destination / f"{stem}.json"
        json_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = [
            f"# Revisión privada GBM · corte {draft['end']}",
            "",
            f"Documento SHA-256: `{draft['sha256']}`.",
            "",
            "**Pendiente de revisión humana.** Los valores impresos se conservan sin ajustes.",
            "Los dos días impresos no se convierten en fechas de operación o liquidación confirmadas.",
            "Este archivo no es un paquete de análisis ni un libro de movimientos aprobado.",
            "",
            "## Efectivo",
            "",
            "Diferencia = saldo anterior + abono o − cargo − saldo impreso. Importes en MXN por confirmar.",
            "El saldo inicial ya se cotejó con la portada; no se cuenta como transición.",
            "",
            "| ID | Página/fila | Días | Sentido | Neto | Saldo anterior | "
            "Esperado | Impreso | Diferencia | Control |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in draft["cash_review"]:
            values = [
                row["ID"][:12], f"{row['Pagina']}/{row['Fila']}", row["DiasImpresos"], row["Sentido"],
                row["NetoImpreso"], row["SaldoAnteriorImpreso"] or "—", row["SaldoEsperado"],
                row["SaldoImpreso"], row["Diferencia"], row["ControlAritmetico"],
            ]
            lines.append("| " + " | ".join(values) + " |")
        lines += ["", "## Texto original y procedencia", ""]
        for row in draft["cash_review"]:
            lines.append(
                f"- `{row['ID'][:12]}` · página {row['Pagina']}, fila {row['Fila']}: "
                + row["TextoOriginal"].replace("\n", " ")
            )
        lines += [
            "", "## Pendientes", "",
            "- Revisar los originales y aceptar o resolver cada diferencia con evidencia.",
            "- Confirmar cuenta, moneda, identidad/mercado, clasificación y fechas de las filas.",
            "- Vincular el CFDI con cargos existentes; no duplicarlo como otro cargo.",
            "- Aportar precios históricos y procedencia antes del análisis de cartera.",
            "- El cotejo aritmético no acredita completitud ni autoriza calcular rendimiento.", "",
        ]
        (destination / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
        controls = Counter(row["ControlAritmetico"] for row in draft["cash_review"])
        packets.append(
            {"cutoff": draft["end"], "sha256": draft["sha256"], "json": json_path.name,
             "markdown": f"{stem}.md", "rows": len(draft["cash_review"]), "controls": dict(controls)}
        )
    result = {"schema": 1, "status": "REQUIERE_REVISION_HUMANA", "packets": packets}
    (destination / "index.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


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
    parser.add_argument("--review-dir", type=Path, help="Detalle privado por fila dentro de data/private/.")
    args = parser.parse_args()
    if args.review_dir:
        write_review_packets([args.previous, args.current], args.review_dir)
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
