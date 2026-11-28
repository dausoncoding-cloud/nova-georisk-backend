"""Fix round r5, item 6: a documented way to make the production test organisation (Internal plan) for the TZS 500
Abliner live test, and nothing more: no members, no engine access, never a customer organisation."""
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.models.abliner import PaymentIntent
from app.models.billing import CreditLedgerEntry, PlatformAudit
from app.models.identity import Organization, OrganizationMembership
from app.models.platform import OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.services.abliner.cli import _test_payment
from app.services.abliner.client import AblinerClient
from app.services.billing import cli, test_organization
from app.services.platform_admin import access
from tests.integration.test_billing_credits import _tenant


def _run(db, capsys, *argv):
    parsed = SimpleNamespace(slug=test_organization.DEFAULT_SLUG, reason=None, apply=False)
    for item in argv:
        key, _, value = item.partition("=")
        setattr(parsed, key, True if value == "" else value)
    return cli.run_test_organization(db, parsed)


def test_dry_run_writes_nothing(db_session, capsys):
    report = _run(db_session, capsys)
    assert (report["mode"], report["action"], report["subscription_id"]) == ("dry-run", "create", None)
    assert db_session.query(Organization).filter_by(slug=test_organization.DEFAULT_SLUG).count() == 0


def test_apply_needs_a_reason(db_session, capsys):
    with pytest.raises(SystemExit, match="--reason is required"):
        _run(db_session, capsys, "apply=")


def test_creates_an_internal_plan_organisation_with_no_members_or_engines_once(db_session, capsys):
    report = _run(db_session, capsys, "apply=", "reason=TZS 500 Abliner live test")
    assert (report["mode"], report["action"], report["plan_key"]) == ("apply", "created", "frris_wrris.internal")
    db_session.expire_all()
    org = db_session.query(Organization).filter_by(slug=test_organization.DEFAULT_SLUG).one()
    sub = db_session.query(OrganizationSubscription).filter_by(organization_id=org.id).one()
    assert str(sub.id) == report["subscription_id"] and str(org.id) == report["organization_id"]
    assert (sub.family, sub.plan_key, sub.status, sub.source) == ("frris_wrris", "frris_wrris.internal",
                                                                    SubscriptionStatus.ACTIVE, "test-organization")
    assert sub.metadata_json == {"test_organization": True, "purpose": "abliner-live-test"}
    assert db_session.query(OrganizationMembership).filter_by(organization_id=org.id).count() == 0
    assert db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=org.id).count() == 0
    actions = {row.action: row for row in db_session.query(PlatformAudit).filter_by(organization_id=org.id)}
    assert set(actions) == {"organization.test_created", "subscription.test_created"}
    assert all(row.actor_label == "operator command: create-test-organization" and row.reason == "TZS 500 Abliner live test"
               for row in actions.values())
    again = _run(db_session, capsys, "apply=", "reason=again")
    assert (again["action"], again["subscription_id"]) == ("exists", report["subscription_id"])
    assert db_session.query(Organization).filter_by(slug=test_organization.DEFAULT_SLUG).count() == 1
    assert db_session.query(PlatformAudit).filter_by(organization_id=org.id).count() == 2


def test_a_customer_organisation_with_that_slug_is_never_touched(db_session, capsys):
    t = _tenant(db_session, "customer-co")
    with pytest.raises(SystemExit, match="is not this command's test organisation"):
        _run(db_session, capsys, "apply=", "reason=x", "slug=customer-co")
    db_session.expire_all()
    assert db_session.query(OrganizationSubscription).filter_by(organization_id=t.org.id).count() == 1
    with pytest.raises(SystemExit, match="Invalid slug"):
        _run(db_session, capsys, "slug=Bad Slug!")


def test_the_live_test_payment_runs_on_it_and_adds_no_credits(db_session, capsys, monkeypatch):
    report = _run(db_session, capsys, "apply=", "reason=TZS 500 Abliner live test")
    admin = _tenant(db_session, "rp-testorg-admin", plan_key="frris_wrris.internal")
    access.grant(db_session, email=None, user_id=admin.user.id, reason="operator", operator="test")
    db_session.commit()
    sent = []
    fake = AblinerClient(transport=httpx.MockTransport(
        lambda request: sent.append(json.loads(request.content)) or httpx.Response(
            201, json={"status": "success", "data": {"id": "tx_live", "status": "pending"}})))
    args = SimpleNamespace(subscription_id=__import__("uuid").UUID(report["subscription_id"]), admin_email=admin.user.email,
                           operator="Owner", phone=None, apply=True)
    monkeypatch.setattr(get_settings(), "abliner_payments_enabled", False)  # the live test runs before the switch
    monkeypatch.setattr(get_settings(), "abliner_api_key", SecretStr("tsl_live_TEST_placeholder"))
    monkeypatch.setattr(get_settings(), "abliner_webhook_secret", SecretStr("whsec_TEST_placeholder"))  # deposits need it
    assert _test_payment(db_session, args, ask=lambda _prompt: "0712345678", client=fake) == 0
    intent = db_session.query(PaymentIntent).filter_by(subscription_id=args.subscription_id, purpose="test").one()
    assert (intent.amount, intent.credits, intent.status) == (500, None, "pending"), (intent.failure_code, sent)
    assert sent[0]["amount"] == 500
    assert db_session.query(CreditLedgerEntry).filter_by(subscription_id=args.subscription_id).count() == 0
