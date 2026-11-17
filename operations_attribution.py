"""Documentary income/charges; native currencies remain separate without dated FX."""

from decimal import Decimal


def documented_amounts(events, start, end, *, base):
    groups = {}
    for event in events:
        if not start < event.day.isoformat() <= end:
            continue
        income = event.amount if event.kind in {"DIVIDEND", "COUPON", "INTEREST"} else Decimal(0)
        if event.kind == "REPO_MATURITY":
            income = event.interest  # Gross redemption already contains principal.
        fees = event.fee + (event.amount if event.kind == "FEE" else 0)
        tax = event.tax + (event.amount if event.kind == "TAX" else 0)
        if not (income or fees or tax):
            continue
        key = (event.asset, event.currency)
        row = groups.setdefault(
            key, {"income": Decimal(0), "fees": Decimal(0), "tax": Decimal(0), "event_ids": []}
        )
        for name, value in (("income", income), ("fees", fees), ("tax", tax)):
            row[name] += value
        row["event_ids"].append(event.id)
    return [
        {
            "instrument": asset,
            "currency": currency,
            **{name: str(row[name]) for name in ("income", "fees", "tax")},
            "net": str(row["income"] - row["fees"] - row["tax"]),
            "event_ids": row["event_ids"],
            "converted": currency == base,
        }
        for (asset, currency), row in sorted(groups.items())
    ]
