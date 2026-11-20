"""Plan catalogue seeding from the versioned data file (plans.v1.json).

Insert-only and idempotent: a plan, engine link or price that already exists is left alone, because
after the first seed prices and limits change only through the audited admin console.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.billing import BillingPlanPrice
from app.models.platform import BillingPlan, BillingPlanEngine, Engine

CATALOGUE_PATH = Path(__file__).with_name("plans.v1.json")


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
                    sort_order=item["sort_order"],
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
            if db.query(BillingPlanPrice).filter(BillingPlanPrice.plan_key == key).first() is None:
                db.add(BillingPlanPrice(
                    plan_key=key, version=1, currency=catalogue["currency"], monthly_price=item["monthly_price"],
                    top_up_credit_price=spec["top_up_credit_price"],
                    source=f"plans.v{catalogue['version']}.json", reason=catalogue["source"],
                ))
                report.prices.append(key)
    db.flush()
    return report


TOP_UP_PACK_CREDITS = 10


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
