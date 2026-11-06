"""Reproducible account research: reviewed inputs, alternatives, goals and portable runs."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import numpy as np
import pandas as pd

from allocation_analysis import calculate_allocation
from analysis_session import analysis_key, session_compute
from data_rights import read_data_rights_csv
from holdings import read_current_holdings_csv
from implementation_costs import ImplementationCostAssumptions, estimate_implementation_cost
from instrument_identity import read_instrument_identity_csv
from model_estimation import DEFAULT_METHOD, METHOD_LABELS
from portfolio_core import (
    PortfolioError,
    PortfolioMetrics,
    calculate_risk_metrics,
    normalize_tickers,
    portfolio_statistics,
    validate_weights,
)
from portfolio_exposure import analyze_exposure, read_components, validate_metadata
from price_quality import assess_price_quality
from price_upload import read_adjusted_price_csv
from reporting import (
    HoldingsAuditReport,
    PortfolioAlternative,
    SimulationReport,
    create_comparison_pdf_report,
)
from simulation import simulate_portfolio_paths

RUN_VERSION = 1
MAX_BUNDLE_BYTES = 9_000_000
INPUT_NAMES = {
    "holdings",
    "prices",
    "rights",
    "identity",
    "components",
    "source_xlsx",
    "source_pdf",
    "catalogue",
}
CODE_FILES = (
    "account_workflow.py",
    "account_import.py",
    "gbm_documents.py",
    "scripts/inspect_gbm_intake.py",
    "instrument_catalogue.py",
    "allocation_analysis.py",
    "model_estimation.py",
    "portfolio_core.py",
    "covariance_calibration.py",
    "implementation_costs.py",
    "simulation.py",
    "portfolio_exposure.py",
    "holdings.py",
    "price_upload.py",
    "reporting.py",
)


def code_fingerprint():
    root = Path(__file__).resolve().parent
    return analysis_key({name: sha256((root / name).read_bytes()).hexdigest() for name in CODE_FILES})


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    ).encode()


@dataclass(frozen=True)
class AccountSettings:
    as_of: str
    history_start: str
    assets: tuple[str, ...]
    risk_free_rate: float = 0.05
    max_weight: float = 0.6
    covariance_method: str = DEFAULT_METHOD
    partial_fraction: float = 0.25
    outside_cash: float = 0.0
    costs_confirmed: bool = False
    commission_bps: float = 0.0
    market_cost_bps: float = 0.0
    vat_rate: float = 0.0
    minimum_commission: float = 0.0
    annual_fixed_cost: float = 0.0
    annual_management_rate: float = 0.0
    cost_source: str = ""
    cost_date: str = ""
    goal_amount: float = 0.0
    goal_months: int = 12
    goal_real: bool = True
    monthly_contribution: float = 0.0
    monthly_withdrawal: float = 0.0
    inflation_rate: float = 0.04
    simulation_method: str = "bootstrap_blocks"
    paths: int = 500
    seed: int = 42
    objective: str = ""
    tracking_reference: str = "Conservar"
    drift_tolerance: float = 0.05

    def validate(self):
        if self.tracking_reference not in {
            "Conservar",
            "Cambio parcial",
            "Mínima volatilidad",
            "Máximo Sharpe",
            "Pesos iguales",
        }:
            raise PortfolioError("La referencia de seguimiento no corresponde a una alternativa.")
        if (
            type(self.drift_tolerance) not in (int, float)
            or not np.isfinite(self.drift_tolerance)
            or not 0 <= self.drift_tolerance <= 1
        ):
            raise PortfolioError("La tolerancia de desvío debe estar entre 0 y 100%.")
        try:
            start, end = date.fromisoformat(self.history_start), date.fromisoformat(self.as_of)
        except (ValueError, TypeError):
            raise PortfolioError("Las fechas del análisis deben usar YYYY-MM-DD.") from None
        if start >= end or end > date.today():
            raise PortfolioError("Define fechas válidas hasta el corte de la cuenta.")
        if not self.assets or len(self.assets) > 25 or len(set(self.assets)) != len(self.assets):
            raise PortfolioError("Define un universo único de hasta 25 instrumentos.")
        if (
            any(not isinstance(asset, str) for asset in self.assets)
            or tuple(normalize_tickers(self.assets)) != self.assets
        ):
            raise PortfolioError("Los instrumentos deben estar normalizados y ser únicos.")
        if self.covariance_method not in METHOD_LABELS:
            raise PortfolioError("Estimador de covarianza no reconocido.")
        numeric = [
            getattr(self, name)
            for name in (
                "risk_free_rate",
                "max_weight",
                "partial_fraction",
                "outside_cash",
                "commission_bps",
                "market_cost_bps",
                "vat_rate",
                "minimum_commission",
                "annual_fixed_cost",
                "annual_management_rate",
                "goal_amount",
                "monthly_contribution",
                "monthly_withdrawal",
                "inflation_rate",
            )
        ]
        if not all(type(value) in (int, float) and np.isfinite(value) for value in numeric):
            raise PortfolioError("Los supuestos deben ser números finitos.")
        if not -1 < self.risk_free_rate < 1 or not 0 < self.partial_fraction < 1:
            raise PortfolioError("Revisa la tasa libre de riesgo y la fracción del cambio parcial.")
        if not 0 < self.max_weight <= 1 or len(self.assets) * self.max_weight < 1 - 1e-10:
            raise PortfolioError("El tope por activo impide invertir el capital completo.")
        if self.outside_cash < 0 or self.goal_amount < 0:
            raise PortfolioError("Efectivo y monto de la meta no pueden ser negativos.")
        if type(self.costs_confirmed) is not bool or type(self.goal_real) is not bool:
            raise PortfolioError("Las confirmaciones del análisis son inválidas.")
        if (
            not isinstance(self.objective, str)
            or len(self.objective) > 500
            or any(ord(c) < 32 for c in self.objective)
        ):
            raise PortfolioError("El objetivo debe ser texto de hasta 500 caracteres.")
        if self.costs_confirmed:
            if (
                not isinstance(self.cost_source, str)
                or not self.cost_source.strip()
                or len(self.cost_source) > 300
                or any(ord(c) < 32 for c in self.cost_source)
            ):
                raise PortfolioError("Declara la fuente del tarifario confirmado.")
            try:
                if date.fromisoformat(self.cost_date) > date.today():
                    raise ValueError
            except (ValueError, TypeError):
                raise PortfolioError("La fecha de revisión del tarifario no es válida.") from None
        if (
            self.monthly_contribution < 0
            or self.monthly_withdrawal < 0
            or (self.monthly_contribution and self.monthly_withdrawal)
        ):
            raise PortfolioError("Elige aportaciones o retiros, con importes no negativos.")
        if not -0.5 < self.inflation_rate <= 1 or self.simulation_method not in {
            "bootstrap_blocks",
            "lognormal",
        }:
            raise PortfolioError("Método de simulación o inflación no válidos.")
        for value, low, high in (
            (self.goal_months, 1, 120),
            (self.paths, 100, 2000),
            (self.seed, 0, 2**32 - 1),
        ):
            if type(value) is not int or not low <= value <= high:
                raise PortfolioError(
                    "La simulación admite 1–120 meses, 100–2,000 trayectorias y semilla válida."
                )
        self.costs().annual_recurring_cost(1)

    def costs(self):
        return ImplementationCostAssumptions(
            self.commission_bps,
            self.market_cost_bps,
            self.vat_rate,
            self.minimum_commission,
            self.annual_fixed_cost,
            self.annual_management_rate,
        )


def settings_from_dict(value):
    if not isinstance(value, dict) or set(value) != set(AccountSettings.__dataclass_fields__):
        raise PortfolioError("La configuración guardada no coincide con esta versión del análisis.")
    result = AccountSettings(**{**value, "assets": tuple(value["assets"])})
    result.validate()
    return result


def prepare_account_inputs(files, settings):
    settings.validate()
    if not set(files).issubset(INPUT_NAMES) or not {"holdings", "prices", "rights"}.issubset(files):
        raise PortfolioError("El análisis necesita cartera, precios ajustados MXN y manifiesto de derechos.")
    holdings = read_current_holdings_csv(files["holdings"], settings.assets)
    if holdings.as_of.date().isoformat() != settings.as_of:
        raise PortfolioError("El corte de las posiciones no coincide con el análisis.")
    prices = read_adjusted_price_csv(
        files["prices"],
        settings.assets,
        date.fromisoformat(settings.history_start),
        date.fromisoformat(settings.as_of),
    ).prices
    rights = read_data_rights_csv(files["rights"])
    identity = (
        read_instrument_identity_csv(
            files["identity"], settings.assets, dict.fromkeys(settings.assets, "MXN")
        )
        if files.get("identity")
        else None
    )
    if identity and identity.proxy_assets:
        raise PortfolioError(
            "Este recorrido usa cierres locales en MXN; los proxies se investigan en Análisis avanzado."
        )
    components = (
        read_components(files["components"], settings.assets, as_of=date.fromisoformat(settings.as_of))
        if files.get("components")
        else None
    )
    return holdings, prices, rights, identity, components


def run_account_analysis(files, settings, metadata, *, session=None):
    holdings, prices, rights, identity, components = prepare_account_inputs(files, settings)
    validate_metadata(metadata, settings.assets, date.fromisoformat(settings.as_of))
    session = session if session is not None else {}
    version = code_fingerprint()
    key = analysis_key(files, asdict(settings), metadata, version)

    def compute():
        model = calculate_allocation(
            prices,
            settings.risk_free_rate,
            settings.max_weight,
            method=settings.covariance_method,
            chart_data=False,
        )
        current = holdings.weights.to_numpy()
        partial = current + settings.partial_fraction * (model.min_volatility.weights - current)
        equal = np.repeat(1 / len(settings.assets), len(settings.assets))
        alternatives = []
        costs, table, goals = [], [], []
        simulations = {}
        for name, weights in (
            ("Conservar", current),
            ("Cambio parcial", partial),
            ("Mínima volatilidad", model.min_volatility.weights),
            ("Máximo Sharpe", model.max_sharpe.weights),
            ("Pesos iguales", equal),
        ):
            metrics = PortfolioMetrics(
                weights,
                *portfolio_statistics(
                    weights, model.moments.mean, model.moments.covariance, settings.risk_free_rate
                ),
            )
            risk = calculate_risk_metrics(model.returns, weights)
            alternatives.append(PortfolioAlternative(name, metrics, risk))
            cost = (
                estimate_implementation_cost(
                    settings.assets,
                    weights,
                    holdings.total_value,
                    settings.costs(),
                    alternative_name=name,
                    current_weights=current,
                )
                if settings.costs_confirmed
                else None
            )
            if cost:
                costs.append(cost)
            turnover = float(np.abs(weights - current).sum() / 2)
            cash_after = settings.outside_cash - cost.total_cost if cost else None
            table.append(
                {
                    "Alternativa": name,
                    "Media histórica anualizada": metrics.annual_return,
                    "Volatilidad anualizada": metrics.annual_volatility,
                    "CVaR diario MXN": risk.historical_cvar * holdings.total_value,
                    "Rotación": turnover,
                    "Costo del cambio MXN": cost.total_cost
                    if cost
                    else (0.0 if name == "Conservar" else None),
                    "Costo recurrente anual MXN": settings.costs().annual_recurring_cost(holdings.total_value)
                    if cost
                    else None,
                    "Efectivo tras costos MXN": cash_after,
                    "Financiable con efectivo externo": cash_after >= -1e-8
                    if cash_after is not None
                    else None,
                    "Cumple tope por activo": bool(weights.max() <= settings.max_weight + 1e-7),
                }
            )
            if settings.goal_amount > 0:
                if cash_after is not None and cash_after < -1e-8:
                    goals.append(
                        {
                            "Alternativa": name,
                            "Probabilidad simulada de alcanzar meta": None,
                            "Capital final mediano MXN": None,
                            "Déficit mediano MXN": None,
                            "Probabilidad de retiro no cubierto": None,
                        }
                    )
                    continue
                reserve = max(0.0, cash_after) if cash_after is not None else settings.outside_cash
                initial = holdings.total_value + reserve
                goal_returns = model.returns.copy()
                cash_label = "__RESERVA_EFECTIVO_MXN__"
                goal_returns[cash_label] = 0.0
                goal_weights = np.r_[weights * holdings.total_value / initial, reserve / initial]
                simulation = simulate_portfolio_paths(
                    goal_returns,
                    goal_weights,
                    initial_value=initial,
                    months=settings.goal_months,
                    paths=settings.paths,
                    seed=settings.seed,
                    monthly_contribution=settings.monthly_contribution,
                    monthly_withdrawal=settings.monthly_withdrawal,
                    inflation_rate=settings.inflation_rate,
                    method=settings.simulation_method,
                    annual_fee=settings.annual_management_rate if settings.costs_confirmed else 0.0,
                    monthly_fixed_fee=settings.annual_fixed_cost / 12 if settings.costs_confirmed else 0.0,
                    transaction_cost_bps=0.0,
                    rebalance_months=None,
                    fee_exempt_assets=(len(settings.assets),),
                )
                simulations[name] = simulation
                terminal = (
                    simulation.real_terminal_values if settings.goal_real else simulation.monthly_values[-1]
                )
                goals.append(
                    {
                        "Alternativa": name,
                        "Probabilidad simulada de alcanzar meta": float(
                            np.mean(terminal >= settings.goal_amount)
                        ),
                        "Capital final mediano MXN": float(np.median(terminal)),
                        "Déficit mediano MXN": float(
                            np.median(np.maximum(0, settings.goal_amount - terminal))
                        ),
                        "Probabilidad de retiro no cubierto": simulation.probability_of_shortfall,
                        "Probabilidad de cargo fijo no cubierto": float(np.mean(simulation.unpaid_fees > 0)),
                    }
                )
        issues = assess_price_quality(prices)
        exposure = analyze_exposure(
            settings.assets, current, metadata, components, as_of=date.fromisoformat(settings.as_of)
        )
        pending = [
            "Revisión humana del expediente y de los documentos originales",
            "Contraste independiente de precios no aportado en este recorrido",
        ]
        if identity is None:
            pending.append("Identidad local/ISIN no aportada")
        if not settings.costs_confirmed:
            pending.append("Tarifario sin confirmar; los costos faltantes no se suponen cero")
        if exposure["coverage"] < 1 - 1e-8:
            pending.append(f"Exposición sin cobertura: {1 - exposure['coverage']:.1%}")
        if (date.fromisoformat(settings.as_of) - prices.index[-1].date()).days > 7:
            pending.append("Último precio con más de 7 días respecto al corte")
        if issues:
            pending.append(f"{len(issues)} alerta(s) heurística(s) de precios")
        if not settings.costs_confirmed and settings.goal_amount:
            pending.append("Meta simulada antes de costos por falta de tarifario")
        return {
            "code_sha256": version,
            "calculated_at": datetime.now(UTC).isoformat(),
            "model": model,
            "holdings": holdings,
            "prices": prices,
            "rights": rights,
            "identity": identity,
            "components": components,
            "alternatives": tuple(alternatives),
            "costs": tuple(costs),
            "comparison": pd.DataFrame(table),
            "goals": pd.DataFrame(goals),
            "simulations": simulations,
            "exposure": exposure,
            "pending": pending,
            "quality_issues": issues,
            "key": key,
            "input_files": dict(files),
        }

    return session_compute(session, "account_run", key, compute, max_entries=2)


def account_pdf(result, settings, *, run_id, selected="Mínima volatilidad"):
    simulation = result["simulations"].get(selected)
    report = (
        SimulationReport(
            selected,
            simulation,
            settings.monthly_contribution,
            settings.monthly_withdrawal,
            settings.annual_management_rate if settings.costs_confirmed else 0.0,
            0,
            settings.inflation_rate,
            None,
            21,
        )
        if simulation
        else None
    )
    return create_comparison_pdf_report(
        settings.assets,
        result["prices"].index.min().date(),
        result["prices"].index.max().date(),
        result["alternatives"],
        result["holdings"].total_value,
        base_currency="MXN",
        risk_free_rate=settings.risk_free_rate,
        observations=len(result["model"].returns),
        quotes=dict.fromkeys(settings.assets, "MXN"),
        data_source=f"Ejecución {run_id}. {result['rights'].source}. {result['model'].moments.description}. "
        "Cartera al corte, no rendimiento realizado. La meta incluye efectivo externo sin rendimiento; "
        "el efectivo está exento de cargo proporcional. "
        f"Meta {settings.goal_amount:,.2f} MXN {'de hoy' if settings.goal_real else 'nominales'}, "
        f"{settings.goal_months} meses, método {settings.simulation_method}, semilla {settings.seed}. "
        + (
            f"Cargo fijo mensual {settings.annual_fixed_cost / 12:.2f} MXN; "
            if settings.costs_confirmed
            else "Costos sin confirmar: meta simulada bruta; "
        )
        + "sin costos de las operaciones futuras ni impuestos. "
        + "; ".join(result["pending"]),
        holdings_audit=HoldingsAuditReport(
            result["holdings"],
            "Cartera revisada del recorrido por cuenta",
            sha256(result["input_files"]["holdings"]).hexdigest(),
        ),
        implementation_costs=result["costs"],
        implementation_cost_assumptions=settings.costs() if settings.costs_confirmed else None,
        implementation_cost_source=settings.cost_source if settings.costs_confirmed else None,
        implementation_cost_source_date=date.fromisoformat(settings.cost_date)
        if settings.costs_confirmed
        else None,
        simulation=report,
        price_quality_issues=result["quality_issues"],
        executive_summary=True,
        objective=settings.objective or None,
    )


def make_run_bundle(
    files,
    settings,
    metadata,
    result,
    *,
    case_id=None,
    account_id=None,
    profile=None,
    run_id=None,
    import_review=None,
    pdf=None,
):
    if (case_id is None) != (account_id is None):
        raise PortfolioError("Vincula expediente y cuenta juntos.")
    if result["key"] != analysis_key(files, asdict(settings), metadata, result["code_sha256"]):
        raise PortfolioError(
            "Los insumos o supuestos cambiaron después del cálculo; ejecuta el análisis otra vez."
        )
    run_id = run_id or uuid4().hex
    manifest = {
        "schema_version": RUN_VERSION,
        "run_id": run_id,
        "created_at": result["calculated_at"],
        "case_id": case_id,
        "account_id": account_id,
        "settings": asdict(settings),
        "metadata": metadata,
        "profile": profile,
        "import_review": import_review,
        "code_sha256": result["code_sha256"],
        "fingerprints": {name: sha256(value).hexdigest() for name, value in files.items()},
        "summary": {
            "as_of": settings.as_of,
            "positions": dict(zip(settings.assets, result["holdings"].values.tolist(), strict=True)),
            "outside_cash": settings.outside_cash,
            "covariance_method": settings.covariance_method,
            "shrinkage": result["model"].moments.shrinkage,
            "weights": {item.name: item.metrics.weights.tolist() for item in result["alternatives"]},
            "reference_name": settings.tracking_reference,
            "reference_weights": dict(
                zip(
                    settings.assets,
                    next(
                        item.metrics.weights.tolist()
                        for item in result["alternatives"]
                        if item.name == settings.tracking_reference
                    ),
                    strict=True,
                )
            ),
            "drift_tolerance": settings.drift_tolerance,
            "pending": result["pending"],
            "exposure_coverage": result["exposure"]["coverage"],
            "comparison": result["comparison"]
            .astype(object)
            .where(pd.notna(result["comparison"]), None)
            .to_dict(orient="records"),
            "goals": result["goals"]
            .astype(object)
            .where(pd.notna(result["goals"]), None)
            .to_dict(orient="records"),
        },
        "client_delivery_allowed": False,
        "report_sha256": sha256(pdf).hexdigest() if pdf is not None else None,
    }
    manifest = json.loads(_json(manifest))
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            ZipInfo("run.json", (1980, 1, 1, 0, 0, 0)), _json(manifest), compress_type=ZIP_DEFLATED
        )
        if pdf is not None:
            if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF"):
                raise PortfolioError("El reporte no tiene formato PDF.")
            archive.writestr(ZipInfo("report.pdf", (1980, 1, 1, 0, 0, 0)), pdf, compress_type=ZIP_DEFLATED)
        for name, value in sorted(files.items()):
            if name not in INPUT_NAMES or not isinstance(value, bytes):
                raise PortfolioError("El paquete contiene un insumo no admitido.")
            archive.writestr(
                ZipInfo(f"inputs/{name}", (1980, 1, 1, 0, 0, 0)), value, compress_type=ZIP_DEFLATED
            )
    if len(stream.getvalue()) > MAX_BUNDLE_BYTES:
        raise PortfolioError("El paquete supera 9 MB; reduce el periodo o tamaño de los archivos.")
    return manifest, stream.getvalue()


def read_run_bundle(contents, *, case_id=None, account_id=None):
    if not contents or len(contents) > MAX_BUNDLE_BYTES:
        raise PortfolioError("El paquete está vacío o supera 9 MB.")
    try:
        with ZipFile(BytesIO(contents)) as archive:
            entries = archive.infolist()
            names = {item.filename for item in entries}
            allowed = {"run.json", "report.pdf"} | {f"inputs/{name}" for name in INPUT_NAMES}
            if (
                len(names) != len(entries)
                or not names.issubset(allowed)
                or "run.json" not in names
                or sum(item.file_size for item in entries) > 30_000_000
            ):
                raise ValueError
            manifest = json.loads(archive.read("run.json"))
            report_sha = manifest.get("report_sha256")
            if ("report.pdf" in names) != (report_sha is not None):
                raise ValueError
            if report_sha is not None and sha256(archive.read("report.pdf")).hexdigest() != report_sha:
                raise ValueError
            if (
                manifest["schema_version"] != RUN_VERSION
                or manifest["client_delivery_allowed"] is not False
                or not isinstance(manifest["fingerprints"], dict)
                or set(manifest["fingerprints"]) != {name[7:] for name in names if name.startswith("inputs/")}
            ):
                raise ValueError
            if (
                not re.fullmatch(r"[0-9a-f]{32}", manifest["run_id"])
                or not re.fullmatch(r"[0-9a-f]{64}", manifest["code_sha256"])
                or (manifest["case_id"] is None) != (manifest["account_id"] is None)
            ):
                raise ValueError
            if case_id is not None and (manifest["case_id"], manifest["account_id"]) != (case_id, account_id):
                raise PortfolioError("La ejecución pertenece a otro expediente o cuenta.")
            files = {name: archive.read(f"inputs/{name}") for name in manifest["fingerprints"]}
            if any(
                sha256(value).hexdigest() != manifest["fingerprints"][name] for name, value in files.items()
            ):
                raise ValueError
            settings = settings_from_dict(manifest["settings"])
            holdings, *_ = prepare_account_inputs(files, settings)
            validate_metadata(manifest["metadata"], settings.assets, date.fromisoformat(settings.as_of))
            summary = manifest["summary"]
            if (
                summary["as_of"] != settings.as_of
                or summary["outside_cash"] != settings.outside_cash
                or summary["positions"] != dict(zip(settings.assets, holdings.values.tolist(), strict=True))
            ):
                raise ValueError
            for weights in summary["weights"].values():
                validate_weights(weights, len(settings.assets))
            expected_reference = dict(
                zip(settings.assets, summary["weights"][settings.tracking_reference], strict=True)
            )
            if (
                summary["reference_weights"] != expected_reference
                or summary["reference_name"] != settings.tracking_reference
                or summary["drift_tolerance"] != settings.drift_tolerance
            ):
                raise ValueError
            return manifest, files, settings
    except PortfolioError:
        raise
    except (BadZipFile, KeyError, ValueError, TypeError, OSError, UnicodeError):
        raise PortfolioError("El paquete no supera la comprobación de formato e integridad.") from None


def compare_account_cuts(previous, current):
    if (previous.get("case_id"), previous.get("account_id")) != (
        current.get("case_id"),
        current.get("account_id"),
    ):
        raise PortfolioError("Compara cortes de la misma cuenta y expediente.")
    before, after = previous["summary"], current["summary"]
    if before["as_of"] >= after["as_of"]:
        raise PortfolioError("El corte anterior debe preceder al actual.")
    total_before, total_after = sum(before["positions"].values()), sum(after["positions"].values())
    rows = []
    for asset in sorted(set(before["positions"]) | set(after["positions"])):
        old, new = before["positions"].get(asset, 0), after["positions"].get(asset, 0)
        reference = before.get("reference_weights", {}).get(asset)
        drift = new / total_after - reference if reference is not None else None
        rows.append(
            {
                "Instrumento": asset,
                "Valor anterior MXN": old,
                "Valor actual MXN": new,
                "Cambio de valuación MXN": new - old,
                "Peso anterior": old / total_before,
                "Peso actual": new / total_after,
                "Desvío de peso": new / total_after - old / total_before,
                "Peso referencia anterior": reference,
                "Desvío vs referencia": drift,
                "Fuera de tolerancia": abs(drift) > before.get("drift_tolerance", 0.05)
                if drift is not None
                else None,
            }
        )
    return pd.DataFrame(rows)
