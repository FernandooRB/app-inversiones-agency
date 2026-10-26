"""Manual, public-source audit; never called by the production Streamlit app.

Usage: python scripts/audit_market_sources.py --symbols AAPL MSFT NVDA KO SPY
The Nasdaq historical endpoint is public but not a contracted production feed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from technical_analysis import MarketHistory  # noqa: E402
from technical_market_data import download_market_history  # noqa: E402
from technical_source_audit import compare_market_histories  # noqa: E402

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "KO", "SPY", "QQQ")
NASDAQ_ENDPOINT = "https://api.nasdaq.com/api/quote/{symbol}/historical"


def parse_nasdaq_rows(symbol: str, records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        values = {}
        for name in ("Open", "High", "Low", "Close", "Volume"):
            raw = record.get(name.lower())
            if not isinstance(raw, str) or raw.upper() == "N/A":
                raise ValueError(f"Nasdaq {symbol}, {record.get('date')}: {name} ausente.")
            values[name] = float(raw.replace("$", "").replace(",", ""))
        rows.append({"Date": pd.to_datetime(record["date"], format="%m/%d/%Y"), **values})
    if not rows:
        raise ValueError("Nasdaq no devolvió sesiones.")
    return pd.DataFrame(rows).set_index("Date").sort_index()


def download_nasdaq_history(symbol: str, *, now: datetime) -> MarketHistory:
    start = (pd.Timestamp(now.date()) - pd.DateOffset(years=5, months=1)).date()
    assetclass = "etf" if symbol in {"SPY", "QQQ", "IWM"} else "stocks"
    query = urlencode({
        "assetclass": assetclass, "fromdate": start.isoformat(),
        "todate": now.date().isoformat(), "limit": 2000,
    })
    url = f"{NASDAQ_ENDPOINT.format(symbol=symbol)}?{query}"
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Origin": "https://www.nasdaq.com",
    })
    with urlopen(request, timeout=35) as response:
        payload = json.load(response)
    if payload.get("status", {}).get("rCode") != 200 or not payload.get("data"):
        raise ValueError("Nasdaq no devolvió historia válida.")
    bars = parse_nasdaq_rows(symbol, payload["data"]["tradesTable"]["rows"])
    return MarketHistory(symbol, bars, "USD", "US consolidated", "America/New_York", now,
                         source="Nasdaq, histórico público")


def audit_symbol(symbol: str, now: datetime) -> dict:
    try:
        yahoo = download_market_history(symbol)
        nasdaq = download_nasdaq_history(symbol, now=now)
        comparison = compare_market_histories(yahoo, nasdaq, now=now)
        events = {}
        for name in ("Dividends", "Stock Splits"):
            if name in yahoo.bars:
                events[name] = int(yahoo.bars[name].fillna(0).ne(0).sum())
        return {"symbol": symbol, "status": "evaluado", "comparison": asdict(comparison),
                "yahoo_events": events}
    except Exception as exc:
        # This audit is independent per ticker, as is the production loader.
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
        "scope": "Contraste público de investigación; no sustituye datos SIC ni licencia de mercado.",
        "symbols": [audit_symbol(symbol, now) for symbol in symbols],
    }
    output = args.output or ROOT / "data" / "private" / "market_source_audit.json"
    output = output.resolve()
    private_root = (ROOT / "data" / "private").resolve()
    if not output.is_relative_to(private_root):
        parser.error("La salida debe estar dentro de data/private.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "evaluated": sum(item["status"] == "evaluado" for item in report["symbols"]),
        "failed": [item["symbol"] for item in report["symbols"] if item["status"] != "evaluado"],
        "needs_review": [item["symbol"] for item in report["symbols"]
                         if item["status"] == "evaluado"
                         and item["comparison"]["reasons_to_review"]],
    }, ensure_ascii=False))
    return 0 if all(item["status"] == "evaluado" for item in report["symbols"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
