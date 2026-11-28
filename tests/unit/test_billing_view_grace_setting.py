"""Security review round 4, item 3: BILLING_VIEW_GRACE_DAYS is unset (None) or an integer >= 1; anything else stops
the application at start-up with a clear error (never a silent 0-day grace that closes viewing at once)."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

MESSAGE = "BILLING_VIEW_GRACE_DAYS must be unset or a whole number of days, 1 or more"


def test_unset_by_default():
    assert Settings(_env_file=None).billing_view_grace_days is None


@pytest.mark.parametrize("value,expected", [("1", 1), ("2", 2), ("30", 30)])
def test_whole_days_of_one_or_more_are_accepted(monkeypatch, value, expected):
    monkeypatch.setenv("BILLING_VIEW_GRACE_DAYS", value)
    assert Settings(_env_file=None).billing_view_grace_days == expected


@pytest.mark.parametrize("value", ["0", "-1", "-30"])
def test_zero_or_negative_refuses_to_start_with_a_clear_error(monkeypatch, value):
    monkeypatch.setenv("BILLING_VIEW_GRACE_DAYS", value)
    with pytest.raises(ValidationError, match=MESSAGE):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["two", "2.5", "", " "])
def test_anything_that_is_not_a_whole_number_refuses_to_start(monkeypatch, value):
    monkeypatch.setenv("BILLING_VIEW_GRACE_DAYS", value)
    with pytest.raises(ValidationError, match="billing_view_grace_days"):
        Settings(_env_file=None)
