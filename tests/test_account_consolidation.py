from dataclasses import replace
from datetime import date
from io import BytesIO

import pandas as pd
import pytest
from pypdf import PdfReader

from account_consolidation import consolidate_snapshots, prepare_account_snapshot
from consolidated_reporting import create_consolidation_pdf
from instrument_identity import IDENTITY_COLUMNS, valid_isin
from portfolio_core import PortfolioError


def account(alias, amount, cash=100):
    prefix = "ZZ000000001"
    isin = next(prefix + str(number) for number in range(10) if valid_isin(prefix + str(number)))
    files = {
        "holdings": f"FechaCorte,Instrumento,ValorMXN\n2020-09-08,AAA,{amount}\n".encode(),
        "coverage": (
            "FechaCorte,ValorCarteraAnalizadaMXN,EfectivoFueraAnalisisMXN,"
            "PendienteLiquidacionMXN,OtrosFueraAnalisisMXN,TotalCuentaMXN,Fuente\n"
            f"2020-09-08,{amount},{cash},0,0,{amount + cash},Cobertura sintética\n"
        ).encode(),
        "identity": (
            ",".join(IDENTITY_COLUMNS)
            + "\n"
            + f"AAA,{isin},BMV,AAA,BMV,MXN,CIERRE_LOCAL_AJUSTADO,{date.today()},Sintético\n"
        ).encode(),
    }
    return prepare_account_snapshot(alias, ("AAA",), files)


def test_consolidation_sums_account_parts_exactly_and_keeps_cash_separate():
    result = consolidate_snapshots((account("Cuenta_A", 1000), account("Cuenta_B", 2000)))
    assert result["totals"]["positions"] == "3000.00"
    assert result["totals"]["cash_outside"] == "200.00"
    assert result["totals"]["total"] == "3200.00"
    assert result["positions"][0]["weight_in_analyzed_positions"] == "1"
    assert not result["client_delivery_allowed"]
    pdf = create_consolidation_pdf(result)
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert "3,200.00" in text and "200.00" in text
    assert "No autorizado para entrega" in text


def test_consolidation_rejects_duplicate_positions_or_different_cuts():
    first = account("Cuenta_A", 1000)
    duplicate = replace(first, alias="Cuenta_B")
    with pytest.raises(PortfolioError, match="duplicadas"):
        consolidate_snapshots((first, duplicate))
    second = account("Cuenta_B", 2000)
    different = replace(second, holdings=replace(second.holdings, as_of=pd.Timestamp("2020-08-31")))
    with pytest.raises(PortfolioError, match="corte"):
        consolidate_snapshots((first, different))
