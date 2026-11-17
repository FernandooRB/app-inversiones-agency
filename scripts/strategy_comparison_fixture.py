"""Create fictional portable inputs for browser checks; no provider or real documents."""
# ruff: noqa: E402

import base64
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from account_demo import demo_account
from account_workflow import AccountSettings, make_run_bundle, run_account_analysis
from executable_allocation import executable_plan
from implementation_costs import ImplementationCostAssumptions
from operations_proposal import portable_proposal
from operations_proposal_bridge import proposal_inputs
from operations_review import build_operations_review


def create_fixture(out):
    # Fixed past date: browser checks must not change when runners cross midnight.
    with patch("account_demo.date") as clock:
        clock.today.return_value = date(2026, 11, 13)
        files, metadata, defaults = demo_account()
    settings = AccountSettings(**defaults)
    result = run_account_analysis(files, settings, metadata)
    frame = pd.DataFrame(
        {"Instrumento": settings.assets, "Cantidad": 0, "Precio": 10, "Lote": 1, "PesoObjetivo": 0.1}
    )
    costs = ImplementationCostAssumptions(10)
    day = settings.as_of
    ledger = (
        "ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
        "Referencia,MomentoFlujo,Interes\n"
        f"opening,{day},{day},OPEN_CASH,,MXN,0,0,1000,0,0,,UNKNOWN,0\n"
    ).encode()
    ready = proposal_inputs(
        ledger,
        cutoff=date.fromisoformat(day),
        currency="MXN",
        confirmed=True,
        market_rows=[
            {
                "Instrumento": a,
                "Fecha": day,
                "Precio": "10",
                "Lote": "1",
                "PesoObjetivo": "0.1",
                "Fuente": "Precios y lotes ficticios",
            }
            for a in settings.assets
        ],
    )
    frame = ready["positions"]
    proposal = {
        "inputs": {
            "currency": "MXN",
            "date": settings.as_of,
            "quote_source": "Precios ficticios sin ajuste",
            "tariff_source": "Tarifa ficticia",
            "tariff": asdict(costs),
            "cash": 1000.0,
            "cash_floor": 0.0,
            "max_turnover": 2.0,
            "max_weight": 1.0,
            "minimum_trade": 0.0,
            "origin": "Libro de movimientos",
            "optimize": False,
            "book_origin": {k: v for k, v in ready.items() if k != "positions"},
            "target": [0.1] * 3,
            "csv": base64.b64encode(frame.to_csv(index=False).encode()).decode(),
        },
        "result": executable_plan(frame, 1000, [0.1] * 3, costs, quotes_confirmed=True),
    }
    _, package = build_operations_review(
        {"ledger": ledger}, cutoff=settings.as_of, base="MXN", proposal=portable_proposal(proposal)
    )
    out.mkdir(parents=True, exist_ok=True)
    _, analysis = make_run_bundle(files, settings, metadata, result, run_id="b" * 32)
    (out / "strategy_account_analysis.zip").write_bytes(analysis)
    (out / "strategy_fixture_v3.zip").write_bytes(package)
    weights = next(a.metrics.weights.tolist() for a in result["alternatives"] if a.name == "Máximo Sharpe")
    (out / "strategy_expected.json").write_text(
        json.dumps({"fictional_only": True, "date": settings.as_of, "weights": weights}), encoding="utf-8"
    )


if __name__ == "__main__":
    create_fixture(Path(sys.argv[1]))
