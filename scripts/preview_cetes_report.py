"""Create a fictional mixed-asset report for PDF visual review."""

from datetime import date
from pathlib import Path

import numpy as np

from portfolio_core import PortfolioMetrics, RiskMetrics
from reporting import create_pdf_report


def main() -> None:
    output = Path("output/pdf/reporte_metodologico_cetes_ficticio.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(create_pdf_report(
        ("SPY", "AMXB.MX", "CETES28"),
        date(2022, 1, 3),
        date(2025, 12, 31),
        PortfolioMetrics(np.array([0.40, 0.25, 0.35]), 0.092, 0.108, 0.296),
        RiskMetrics(0.95, 5, 0.031, 0.037, 0.049),
        1_000_000,
        base_currency="MXN",
        risk_free_rate=0.06,
        max_weight=0.60,
        observations=980,
        quotes={"SPY": "USD", "AMXB.MX": "MXN", "CETES28": "MXN"},
        data_source=(
            "datos ficticios para revisión visual; CETES28: CSV aportado por el usuario y "
            "preparado desde precio/plazo, SHA-256 abc123def456"
        ),
    ))
    print(output.resolve())


if __name__ == "__main__":
    main()
