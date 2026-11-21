"""Plan catalogue from the versioned data file (plans.v2.json; plans.v1.json is kept as history and is
what the migrations seeded).

- `seed_catalogue`: insert-only and idempotent; a plan, engine link or price that already exists is left alone.
- `apply_catalogue`: brings a database seeded from an earlier version up to this file's prices and plan limits,
  as audited changes (new price versions; plan-limit edits). Dry run unless `apply`. Operator command only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.billing import BillingPlanPrice
from app.models.platform import BillingPlan, BillingPlanEngine, Engine

CATALOGUE_PATH = Path(__file__).with_name("plans.v2.json")


@lru_cache(maxsize=1)
def load_catalogue(path: str | None = None) -> dict:
    return json.loads(Path(path or CATALOGUE_PATH).read_text(encoding="utf-8"))


def family_engines(family: str) -> list[str]:
    return list(load_catalogue()["families"][family]["engines"])


def family_of_engine(engine_key: str) -> str | None:
    for family, spec in load_catalogue()["families"].items():
        if engine_key in spec["engines"]:
            return family
    return None


@dataclass
class SeedReport:
    plans: list[str] = field(default_factory=list)
    engine_links: list[str] = field(default_factory=list)
    prices: list[str] = field(default_factory=list)


def seed_catalogue(db: Session, catalogue: dict | None = None) -> SeedReport:
    catalogue = catalogue or load_catalogue()
    report = SeedReport()
    refund_default = bool(catalogue.get("refund_on_data_failure", False))
    for family, plans in catalogue["plans"].items():
        spec = catalogue["families"][family]
        for item in plans:
            key = item["key"]
            if db.get(BillingPlan, key) is None:
                db.add(BillingPlan(
                    key=key, name=item["name"], status="active", family=family, is_custom=item["is_custom"],
                    seat_limit=item["seat_limit"], monthly_credits=item["monthly_credits"],
                    storage_bytes=item["storage_bytes"], session_limit=item["session_limit"],
                    refund_on_data_failure=item.get("refund_on_data_failure", refund_default),
                    sort_order=item["sort_order"], is_internal=item.get("is_internal", False),
                    unlimited_credits=item.get("unlimited_credits", False),
                    description=f"{spec['name']} - {item['name']}",
                    metadata_json={"catalogue_version": catalogue["version"]},
                ))
                db.flush()
                report.plans.append(key)
            for engine_key in spec["engines"]:
                if db.get(Engine, engine_key) is None:
                    continue
                if db.get(BillingPlanEngine, (key, engine_key)) is None:
                    db.add(BillingPlanEngine(plan_key=key, engine_key=engine_key))
                    report.engine_links.append(f"{key}:{engine_key}")
            if item.get("is_internal"):
                continue  # not sold: no price row, no top-up offer
            if db.query(BillingPlanPrice).filter(BillingPlanPrice.plan_key == key).first() is None:
                db.add(BillingPlanPrice(
                    plan_key=key, version=1, currency=catalogue["currency"], monthly_price=item["monthly_price"],
                    top_up_credit_price=top_up_credit_price(catalogue, family, item),
                    source=f"plans.v{catalogue['version']}.json", reason=catalogue["source"],
                ))
                report.prices.append(key)
    db.flush()
    return report


TOP_UP_PACK_CREDITS = 10
# The plan fields `apply_catalogue` keeps in line with the file (prices are handled as versions).
SYNCED_LIMITS = ("monthly_credits", "session_limit", "refund_on_data_failure")


def top_up_credit_price(catalogue: dict, family: str, item: dict) -> int | None:
    """A plan's own price per top-up credit (Q1: Researcher), else its family's."""
    if "top_up_credit_price" in item:
        return item["top_up_credit_price"]
    return catalogue["families"][family]["top_up_credit_price"]


def storage_extra_gb_price(family: str) -> int | None:
    """Q5(b): price per extra GB of storage, as data. None until decided (NOVA ARI quotes it)."""
    return load_catalogue()["families"][family].get("storage_extra_gb_price")


def plan_limits_from_file(catalogue: dict, item: dict) -> dict:
    refund_default = bool(catalogue.get("refund_on_data_failure", False))
    return {"monthly_credits": item["monthly_credits"], "session_limit": item["session_limit"],
            "refund_on_data_failure": item.get("refund_on_data_failure", refund_default)}


def apply_catalogue(db: Session, *, apply: bool, actor, catalogue: dict | None = None) -> list[dict]:
    """Differences between the database and the file, applied as audited changes when `apply`."""
    from app.services.platform_admin import actions

    catalogue = catalogue or load_catalogue()
    reason = f"Catalogue v{catalogue['version']}: {catalogue['source']}"
    changes: list[dict] = []
    for family, plans in catalogue["plans"].items():
        for item in plans:
            plan = db.get(BillingPlan, item["key"])
            if plan is None:
                changes.append({"plan": item["key"], "change": "missing (run seed first)"})
                continue
            wanted = plan_limits_from_file(catalogue, item)
            limits = {name: value for name, value in wanted.items() if getattr(plan, name) != value}
            if limits:
                changes.append({"plan": plan.key, "change": "limits",
                                "from": {name: getattr(plan, name) for name in limits}, "to": limits})
                if apply:
                    actions.update_plan_limits(db, plan.key, changes=limits, reason=reason, actor=actor)
            if item.get("is_internal"):
                continue
            current = current_price(db, plan.key)
            price = {"monthly_price": item["monthly_price"],
                     "top_up_credit_price": top_up_credit_price(catalogue, family, item)}
            if current is None or (current.monthly_price, current.top_up_credit_price) != tuple(price.values()):
                changes.append({"plan": plan.key, "change": "price",
                                "from": {"monthly_price": current.monthly_price,
                                         "top_up_credit_price": current.top_up_credit_price} if current else None,
                                "to": price})
                if apply:
                    actions.new_price_version(db, plan.key, reason=reason, actor=actor,
                                              source=f"plans.v{catalogue['version']}.json", **price)
    db.flush()
    return changes


def internal_plan_key(family: str) -> str:
    return f"{family}.internal"


def current_price(db: Session, plan_key: str, at=None) -> BillingPlanPrice | None:
    """Newest price version already in effect (versions are append-only)."""
    from datetime import datetime, timezone

    at = at or datetime.now(timezone.utc)
    return (
        db.query(BillingPlanPrice)
        .filter(BillingPlanPrice.plan_key == plan_key, BillingPlanPrice.effective_from <= at)
        .order_by(BillingPlanPrice.version.desc())
        .first()
    )
