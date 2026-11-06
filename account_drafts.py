"""Bounded JSON drafts; encryption and current-account authorization live in CaseStore."""

import base64
import json

from account_workflow import INPUT_NAMES
from portfolio_core import PortfolioError


def draft_payload(flow):
    return json.loads(
        json.dumps(
            {
                "schema": 1,
                "files": {
                    key: base64.b64encode(value).decode()
                    for key, value in flow["files"].items()
                    if key in INPUT_NAMES
                },
                "metadata": flow["metadata"],
                "defaults": flow["defaults"],
                "demo": flow["demo"],
                "import_review": flow["import_review"],
            },
            default=str,
        )
    )


def restore_draft(payload):
    try:
        if payload["schema"] != 1 or not set(payload["files"]).issubset(INPUT_NAMES):
            raise ValueError
        files = {key: base64.b64decode(value, validate=True) for key, value in payload["files"].items()}
        if sum(map(len, files.values())) > 9_000_000:
            raise ValueError
        return {**payload, "files": files, "completed": None}
    except (KeyError, ValueError, TypeError):
        raise PortfolioError("El borrador no supera la comprobación de formato y tamaño.") from None


def run_name(settings, run_id):
    import re

    label = re.sub(r"[^A-Za-z0-9áéíóúÁÉÍÓÚñÑ_-]+", "-", settings.objective).strip("-")[:35] or "Analisis"
    return f"cartera_run_{settings.as_of}_{label}_{run_id}.zip"


def is_run(name, run_id):
    return name.startswith("cartera_run_") and name.endswith(run_id + ".zip")


def run_options(state, account, *, excluding=None):
    rows = [
        item
        for item in state.get("artifacts", [])
        if item["account_id"] == account
        and item["name"].startswith("cartera_run_")
        and (not excluding or not is_run(item["name"], excluding))
    ]
    rows.sort(key=lambda item: item["added_in_revision"], reverse=True)
    return {item["id"]: item["name"].removeprefix("cartera_run_").removesuffix(".zip") for item in rows}
