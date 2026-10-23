"""Local snapshot pilot. Console output is restricted to statuses and counts."""

import argparse
import json
import sys
from dataclasses import fields
from datetime import date
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_tariffs import read_broker_tariff_csv  # noqa: E402
from pilot_validation import evaluate_snapshot_model, review_cost_profile  # noqa: E402
from portfolio_core import PortfolioError  # noqa: E402
from snapshot_pilot import INPUT_ROLES, SnapshotSettings, prepare_snapshot, run_snapshot  # noqa: E402


def read_configuration(path: Path) -> tuple[dict[str, bytes], SnapshotSettings | None, dict]:
    raw = path.read_bytes()
    if len(raw) > 100_000:
        raise ValueError("La configuración excede el tamaño permitido.")
    configuration = json.loads(raw)
    if (not isinstance(configuration, dict) or set(configuration) != {"version", "files", "settings"}
            or type(configuration["version"]) is not int or configuration["version"] != 1
            or not isinstance(configuration["files"], dict)
            or set(configuration["files"]) != set(INPUT_ROLES)):
        raise ValueError("La configuración no coincide con el esquema del piloto.")
    inputs = {}
    missing = []
    root = path.resolve().parent
    for role, name in configuration["files"].items():
        if name is None:
            missing.append(role)
            continue
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError("Las rutas de entrada deben ser relativas a la carpeta del caso.")
        candidate = root / name
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or candidate.is_symlink():
            raise ValueError("Una entrada sale de la carpeta del caso o es un enlace simbólico.")
        if not resolved.is_file():
            missing.append(role)
            continue
        # All existing importers apply tighter limits to their individual data type.
        if resolved.stat().st_size > 5_000_000:
            raise ValueError("Una entrada excede el tamaño permitido.")
        inputs[role] = resolved.read_bytes()
    settings_data = configuration["settings"]
    settings = None
    if settings_data is not None:
        if (not isinstance(settings_data, dict)
                or set(settings_data) - {field.name for field in fields(SnapshotSettings)}):
            raise ValueError("Los supuestos incluyen campos desconocidos.")
        settings_data = dict(settings_data)
        for key in ("history_start", "as_of"):
            settings_data[key] = date.fromisoformat(settings_data[key])
        settings_data["assets"] = tuple(settings_data["assets"])
        settings = SnapshotSettings(**settings_data)
        settings.validate()
    status = {
        "configuration_sha256": sha256(raw).hexdigest(),
        "inputs_loaded": len(inputs), "missing_inputs": missing,
        "settings_pending": settings is None,
        "client_delivery_allowed": False,
    }
    return inputs, settings, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--extended-validation", action="store_true",
                        help="Añadir sensibilidad, estrés y pruebas temporales; conserva faltantes.")
    parser.add_argument("--tariff-profile", type=Path,
                        help="CSV de costos fechado, relativo a la carpeta de configuración.")
    parser.add_argument(
        "--pdf", action="store_true", help="Añadir el comparativo interno cuando el modelo se ejecute.",
    )
    args = parser.parse_args(argv)
    # Never overwrite a prior execution, even if its input configuration was changed.
    if args.output_dir.exists():
        print(json.dumps({"status": "OUTPUT_ALREADY_EXISTS"}))
        return 2
    model_executed = False
    try:
        inputs, settings, readiness = read_configuration(args.config)
        ready = not readiness["missing_inputs"] and not readiness["settings_pending"]
        prepared = prepare_snapshot(inputs, settings) if ready else None
        tariff_contents = None
        if args.tariff_profile is not None:
            candidate = args.config.resolve().parent / args.tariff_profile
            if (args.tariff_profile.is_absolute() or not candidate.resolve().is_relative_to(
                    args.config.resolve().parent) or candidate.is_symlink()
                    or candidate.stat().st_size > 100_000):
                raise ValueError("El perfil de costos debe ser local y de hasta 100 KB.")
            tariff_contents = candidate.read_bytes()
            if settings is not None:
                profile = read_broker_tariff_csv(tariff_contents, as_of=settings.as_of)
                if profile.valid_from is None:
                    raise ValueError("El perfil necesita vigencia explícita.")
        readiness["cost_profile_validated"] = tariff_contents is not None and settings is not None
        readiness.update({"status": "VALIDATED_INPUTS" if ready else "INPUTS_PENDING",
                          "model_executed": False, "human_review_pending": True})
        run = run_snapshot(prepared) if prepared is not None and not args.check_only else None
        model_executed = run is not None
        if run is not None:
            analysis = run.summary()
            analysis["configuration_sha256"] = readiness["configuration_sha256"]
            costs = None
            if tariff_contents is not None:
                costs = review_cost_profile(run, tariff_contents)
            analysis["implementation"] = costs.summary(prepared.holdings.total_value) if costs else {
                "status": "PENDING_ACCOUNT_TARIFF", "costs_are_zero": False,
            }
            if args.extended_validation:
                analysis["validation"] = evaluate_snapshot_model(run)
            pdf = run.pdf(costs=costs) if args.pdf else None
        else:
            analysis, pdf = None, None
        args.output_dir.mkdir(parents=True, exist_ok=False)
        if run is not None:
            readiness.update({"status": "INTERNAL_RESEARCH_COMPLETED", "model_executed": True})
            (args.output_dir / "analysis.json").write_text(
                json.dumps(analysis, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
            )
            if pdf is not None:
                (args.output_dir / "comparison_internal.pdf").write_bytes(pdf)
        (args.output_dir / "readiness.json").write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, KeyError, PortfolioError):
        # Do not print validator messages: they can include holdings amounts or ticker names.
        print(json.dumps({"status": "INVALID_INPUT_OR_OUTPUT", "model_executed": model_executed}))
        return 2
    print(json.dumps({"status": readiness["status"], "inputs_loaded": readiness["inputs_loaded"],
                      "missing_count": len(readiness["missing_inputs"]),
                      "model_executed": readiness["model_executed"], "client_delivery_allowed": False}))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
