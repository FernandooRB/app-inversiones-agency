"""Synthetic mappings with independently expected book/cash results and preserved source."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

try:
    import csv_mapping as mapper
except ModuleNotFoundError:
    mapper = None

from portfolio_core import PortfolioError
from transaction_ledger import COLUMNS, book_at, read_ledger

HEADERS = [
    "ticket",
    "operacion",
    "liquidacion",
    "clase",
    "activo",
    "divisa",
    "titulos",
    "precio",
    "bruto",
    "cargo",
    "impuesto",
    "ref",
    "momento",
    "interes",
]
RAW = (
    ",".join(HEADERS) + "\n"
    "a,2026-01-01,2026-01-01,Apertura,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    "b,2026-01-05,2026-01-05,Abono,,MXN,0,0,50,0,0,,EOD,0\n"
    "c,2026-01-06,2026-01-06,Retiro,,MXN,0,0,10,0,0,,EOD,0\n"
    "d,2026-01-07,2026-01-07,Dividendo,A,MXN,0,0,5,0,0,,UNKNOWN,0\n"
    "e,2026-01-07,2026-01-07,Cargo,,MXN,0,0,1,0,0,,UNKNOWN,0\n"
    "f,2026-01-07,2026-01-07,Impuesto,,MXN,0,0,0.5,0,0,,UNKNOWN,0\n"
    "g,2026-01-08,2026-01-12,Compra,A,MXN,2,10,20,0.2,0,,UNKNOWN,0\n"
).encode()


def mapping(raw=RAW, **overrides):
    assert mapper is not None, "CSV mapping engine is not implemented"
    config = mapper.blank_mapping(HEADERS)
    config["fields"] = {
        dest: {"mode": "column", "value": src, "transform": "identity"}
        for dest, src in zip(COLUMNS, HEADERS, strict=True)
    }
    config["values"]["Tipo"] = dict(
        zip(
            ["Apertura", "Abono", "Retiro", "Dividendo", "Cargo", "Impuesto", "Compra"],
            ["OPEN_CASH", "DEPOSIT", "WITHDRAWAL", "DIVIDEND", "FEE", "TAX", "BUY"],
            strict=True,
        )
    )
    config["basis"] = "Columnas cotejadas con exportacion ficticia"
    config.update(overrides)
    return config


def test_complete_mapping_preserves_source_and_independently_expected_money_and_settlement():
    config = mapping()
    result = mapper.preview(RAW, config, {})
    assert result["ready"] and not result["issues"]
    book = book_at(read_ledger(result["ledger"]), date(2026, 1, 10))
    assert book["cash"]["MXN"] == Decimal("143.5")
    assert book["pending"]["MXN"] == Decimal("-20.2")
    assert book["positions"][("A", "MXN")] == 2
    assert result["source"]["sha256"] == __import__("hashlib").sha256(RAW).hexdigest()
    assert result["rows"][1]["line_start"] == result["rows"][1]["line_end"] == 3


@pytest.mark.parametrize(("kind", "net"), [(b"BUY", b"20.01"), (b"SELL", b"19.99")])
def test_mapped_net_cannot_be_used_as_gross_when_charges_explain_difference(kind, net):
    raw = RAW.replace(b"Compra,A,MXN,2,10,20,0.2", kind + b",A,MXN,2,10,20,0.01")
    if kind == b"SELL":
        raw += b"h,2026-01-01,2026-01-01,OPEN_POSITION,A,MXN,2,0,0,0,0,,UNKNOWN,0\n"
    correct = mapper.preview(raw, mapping(), {})
    assert correct["ready"]
    raw = raw.replace(b",2,10,20,0.01", b",2,10," + net + b",0.01")
    result = mapper.preview(raw, mapping(), {})
    assert result["ledger"] is None and not result["ready"]
    assert any(i["row"] == 7 and i["code"] == "NET_AS_GROSS" for i in result["issues"])
    assert result["rows"][6]["original"]["bruto"] == net.decode()


def test_template_with_invalid_unicode_is_rejected_before_preview():
    template = json.loads(mapper.write_template(mapping(), mapper.read_source(RAW)))
    template["mapping"]["fields"]["Referencia"] = {
        "mode": "constant",
        "value": "\ud800",
        "transform": "identity",
    }
    with pytest.raises(PortfolioError):
        mapper.read_template(json.dumps(template).encode(), RAW)


def test_unknown_description_and_blank_amount_never_become_classification_or_zero():
    config = mapping()
    config["values"]["Tipo"].pop("Abono")
    result = mapper.preview(RAW, config, {})
    assert not result["ready"] and result["ledger"] is None
    assert any(i["row"] == 2 and i["field"] == "Tipo" for i in result["issues"])
    result = mapper.preview(RAW.replace(b",50,0,0", b",,0,0"), mapping(), {})
    assert not result["ready"] and any(i["field"] == "Importe" for i in result["issues"])


def test_negative_cash_requires_explicit_magnitude_and_does_not_mutate_original():
    raw = RAW.replace(b",10,0,0,,EOD", b",-10,0,0,,EOD")
    config = mapping()
    assert not mapper.preview(raw, config, {})["ready"]
    config["fields"]["Importe"]["transform"] = "magnitude"
    result = mapper.preview(raw, config, {})
    assert result["ready"]
    assert book_at(read_ledger(result["ledger"]), date(2026, 1, 10))["cash"]["MXN"] == Decimal("143.5")
    assert b",-10,0,0" in raw


@pytest.mark.parametrize("date_format,expected", [("DMY", date(2026, 3, 2)), ("MDY", date(2026, 2, 3))])
def test_ambiguous_dates_use_only_declared_format(date_format, expected):
    raw = (
        ",".join(HEADERS) + "\n" + "a,02/03/2026,02/03/2026,Apertura,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    ).encode()
    result = mapper.preview(raw, mapping(date_format=date_format), {})
    assert result["ready"] and read_ledger(result["ledger"])[0].day == expected
    assert not mapper.preview(raw, mapping(), {})["ready"]


def test_decimal_comma_grouping_is_explicit_and_cent_precision_is_not_rounded():
    raw = (
        ";".join(HEADERS) + "\n" + "a;2026-01-01;2026-01-01;Apertura;;MXN;0;0;1.234,0050;0;0;;UNKNOWN;0\n"
    ).encode()
    result = mapper.preview(raw, mapping(delimiter=";", decimal=",", thousands="."), {})
    assert result["ready"]
    assert read_ledger(result["ledger"])[0].amount == Decimal("1234.0050")
    assert b"1234.0050" in result["ledger"]
    assert not mapper.preview(
        raw.replace(b"1.234,0050", b"12.34,0050"), mapping(delimiter=";", decimal=",", thousands="."), {}
    )["ready"]


def test_economic_duplicates_require_explicit_documented_decisions_and_ids_stay_unique():
    first = RAW.splitlines()[1]
    raw = RAW + b"z" + first[1:] + b"\n"
    config = mapping()
    result = mapper.preview(raw, config, {})
    assert not result["ready"] and any(i["code"] == "DUPLICATE" for i in result["issues"])
    decisions = {
        str(n): {
            "action": "include",
            "reason": "Son movimientos diferentes documentados",
            "source": "Dos comprobantes ficticios",
        }
        for n in (1, 8)
    }
    assert mapper.preview(raw, config, decisions)["ready"]
    assert not mapper.preview(RAW + first + b"\n", config, decisions)["ready"]
    decisions["8"] = {"action": "exclude", "reason": "Duplicado cotejado", "source": "Exportacion ficticia"}
    result = mapper.preview(raw, config, decisions)
    assert result["ready"] and result["excluded"] == 1 and len(read_ledger(result["ledger"])) == 7


@pytest.mark.parametrize("replacement", [b'=HYPERLINK("url")', b"@cmd", b"-cmd|bad"])
def test_formula_like_reference_is_pending_and_never_escaped_into_a_different_reference(replacement):
    raw = RAW.replace(b",,EOD", b"," + replacement + b",EOD", 1)
    assert not mapper.preview(raw, mapping(), {})["ready"]


@pytest.mark.parametrize(
    "raw",
    [
        b"a,a\n1,2\n",
        b"a,\n1,2\n",
        b"a,b\n1\n",
        b'a,b\n"unfinished\n',
        b"\x00,a\n1,2\n",
    ],
)
def test_structural_rejection_is_controlled(raw):
    mapping()
    with pytest.raises(PortfolioError):
        mapper.read_source(raw)


def test_template_is_data_only_and_does_not_reuse_row_decisions_or_source_approval():
    config = mapping()
    blob = mapper.write_template(config, mapper.read_source(RAW))
    loaded = mapper.read_template(blob, RAW)
    assert loaded == config
    obj = json.loads(blob)
    assert obj["review_state"] == "PENDING_REVIEW" and "decisions" not in obj and "confirmed" not in obj
    obj["execute"] = "os.remove"
    with pytest.raises(PortfolioError):
        mapper.read_template(json.dumps(obj).encode(), RAW)
    with pytest.raises(PortfolioError):
        mapper.read_template(blob, RAW.replace(b"ticket,", b"otro,"))


def test_import_provenance_roundtrip_scope_and_source_hash_are_strict():
    config = mapping()
    result = mapper.preview(RAW, config, {})
    proposal = {
        "source": RAW,
        "mapping": config,
        "decisions": {},
        "scope": {"case_id": "case-a", "account_id": "account-a"},
        "applied_ledger_sha256": __import__("hashlib").sha256(result["ledger"]).hexdigest(),
    }
    meta, source = mapper.pack_import(proposal)
    assert source == RAW
    assert mapper.unpack_import(meta, source, case_id="case-a", account_id="account-a") == proposal
    with pytest.raises(PortfolioError):
        mapper.unpack_import(meta, source, case_id="case-a", account_id="other")
    with pytest.raises(PortfolioError):
        mapper.unpack_import(meta, source.replace(b",50,", b",51,"), case_id="case-a", account_id="account-a")


def test_zero_is_only_from_column_or_explicit_declaration_and_future_trade_stays_pending():
    config = mapping()
    config["fields"]["Comision"] = {"mode": "missing", "value": "", "transform": "identity"}
    assert not mapper.preview(RAW, config, {})["ready"]
    config["fields"]["Comision"] = {"mode": "constant", "value": "0", "transform": "identity"}
    assert mapper.preview(RAW, config, {})["ready"]
    assert not mapper.preview(RAW.replace(b"2026-01-01", b"2099-01-01"), config, {})["ready"]


def test_partial_import_is_portable_but_never_an_approved_book():
    config = mapping()
    config["values"]["Tipo"].pop("Abono")
    proposal = {
        "source": RAW,
        "mapping": config,
        "decisions": {},
        "scope": {"case_id": None, "account_id": None},
        "applied_ledger_sha256": None,
    }
    meta, source = mapper.pack_import(proposal)
    restored = mapper.unpack_import(meta, source)
    assert not mapper.preview(source, restored["mapping"], restored["decisions"])["ready"]
    assert json.loads(meta)["review_state"] == "PENDING_REVIEW"


def test_limits_and_invalid_rule_shapes_are_rejected():
    config = mapping()
    with pytest.raises(PortfolioError):
        mapper.read_source(b"x" * 2_000_001)
    bad = deepcopy(config)
    bad["fields"]["Importe"]["transform"] = "eval"
    with pytest.raises(PortfolioError):
        mapper.preview(RAW, bad, {})


def test_equivalent_decimal_duplicates_and_unrounded_magnitude():
    first = RAW.splitlines()[1]
    repeated = b"z" + first[1:].replace(b",100,", b",100.00,")
    assert not mapper.preview(RAW + repeated + b"\n", mapping(), {})["ready"]
    precise = b"-0.1234567890123456789012345678901234567890"
    raw = (
        b",".join(h.encode() for h in HEADERS)
        + b"\n"
        + b"a,2026-01-01,2026-01-01,Apertura,,MXN,0,0,"
        + precise
        + b",0,0,,UNKNOWN,0\n"
    )
    config = mapping()
    config["fields"]["Importe"]["transform"] = "magnitude"
    result = mapper.preview(raw, config, {})
    assert result["ready"] and precise[1:] in result["ledger"]


def test_fx_and_repo_are_validated_as_complete_sequences_not_independent_rows():
    raw = (
        ",".join(HEADERS) + "\n"
        "a,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
        "b,2026-01-02,2026-01-02,FX_OUT,,MXN,0,0,20,0,0,fx-one,UNKNOWN,0\n"
        "c,2026-01-02,2026-01-02,FX_IN,,USD,0,0,1,0,0,fx-one,UNKNOWN,0\n"
        "d,2026-01-03,2026-01-03,REPO_START,,MXN,0,0,50,0,0,repo-one,UNKNOWN,0\n"
        "e,2026-01-04,2026-01-04,REPO_MATURITY,,MXN,0,0,51,0,0,repo-one,UNKNOWN,1\n"
    ).encode()
    result = mapper.preview(raw, mapping(), {})
    assert result["ready"]
    book = book_at(read_ledger(result["ledger"]), date(2026, 1, 10))
    assert book["cash"]["MXN"] == Decimal("81") and book["cash"]["USD"] == Decimal("1")
    assert not mapper.preview(raw.replace(b",51,0,0,repo-one", b",52,0,0,repo-one"), mapping(), {})["ready"]
    assert not mapper.preview(raw.replace(b",FX_IN,", b",DEPOSIT,"), mapping(), {})["ready"]
