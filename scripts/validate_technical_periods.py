"""Replay fixed signals in disjoint 252-session periods; no order execution.

Usage: python scripts/validate_technical_periods.py --symbols AAPL MSFT NVDA KO SPY QQQ
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from technical_analysis import completed_bars  # noqa: E402
from technical_market_data import download_market_history  # noqa: E402
from technical_validation import run_chronological_validation  # noqa: E402

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "KO", "SPY", "QQQ")


def validate_symbol(symbol: str, now: datetime) -> dict:
    try:
        history = download_market_history(symbol)
        bars = completed_bars(history, now)
        result = run_chronological_validation(bars)
        windows = result.windows.reset_index()
        windows["Inicio"] = windows["Inicio"].astype(str)
        windows["Fin"] = windows["Fin"].astype(str)
        return {
            "symbol": symbol, "status": "evaluado", "currency": history.currency,
            "exchange": history.exchange, "sessions": len(bars),
            "strategy_version": result.strategy_version,
            "base_cost_rate": result.base_cost_rate,
            "base_slippage_bps": result.base_slippage_bps,
            "stress_cost_rate": result.stress_cost_rate,
            "stress_slippage_bps": result.stress_slippage_bps,
            "windows": windows.astype(object).where(windows.notna(), None).to_dict(orient="records"),
        }
    except Exception as exc:
        return {"symbol": symbol, "status": "no_evaluable", "reason": str(exc)[:180]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    symbols = [symbol.upper() for symbol in args.symbols]
    if len(symbols) > 25 or len(symbols) != len(set(symbols)) or any(
        not symbol.replace(".", "").isalnum() for symbol in symbols
    ):
        parser.error("Indica entre 1 y 25 símbolos únicos con letras, números o punto.")
    now = datetime.now(UTC)
    report = {
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "scope": "Reproducción cronológica retrospectiva; no es prueba prospectiva ni ejecución real.",
        "symbols": [validate_symbol(symbol, now) for symbol in symbols],
    }
    output = (args.output or ROOT / "data" / "private" / "technical_period_validation.json").resolve()
    private_root = (ROOT / "data" / "private").resolve()
    if not output.is_relative_to(private_root):
        parser.error("La salida debe estar dentro de data/private.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "evaluated": sum(item["status"] == "evaluado" for item in report["symbols"]),
        "failed": [item["symbol"] for item in report["symbols"] if item["status"] != "evaluado"],
        "trades_by_symbol": {
            item["symbol"]: sum(window["Operaciones"] for window in item["windows"])
            for item in report["symbols"] if item["status"] == "evaluado"
        },
    }, ensure_ascii=False))
    return 0 if all(item["status"] == "evaluado" for item in report["symbols"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
