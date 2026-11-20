"""FRRIS Trend Analysis rules (docs/FRRIS_TREND_ANALYSIS_PLAN.md §2)."""
import json

import numpy as np
import pytest

from app.services.firris import trends


def _pts(values, start=2000, flagged=()):
    return [{"t": start + i, "value": v, "flagged": i in flagged, "flag": "no-data" if i in flagged else None}
            for i, v in enumerate(values)]


def test_percent_change_is_undefined_when_the_previous_value_is_zero():
    assert trends.percent_change(0, 5) is None
    assert trends.change({"t": 2000, "value": 0.0}, {"t": 2001, "value": 2.0})["percent_text"] == "undefined"
    assert trends.percent_change(4, 5) == pytest.approx(25.0)


def test_points_are_put_in_chronological_order():
    record = trends.series_record(key="k", title="T", indicator="I", units="km²", source="S", method="M", caveats=[],
                                  fit_trend=True, x_kind="year", points=[{"t": 2003, "value": 3}, {"t": 2001, "value": 1}])
    assert [p["t"] for p in record["points"]] == [2001, 2003]


def test_two_points_are_a_change_never_a_trend():
    summary = trends.summarise(_pts([1.0, 3.0]), units="km²", fit_trend=True)
    assert summary["kind"] == "change" and "trend" not in summary and "not a trend" in summary["text"]
    assert summary["change"]["delta"] == 2.0 and summary["change"]["percent"] == pytest.approx(200.0)


def test_no_trend_line_with_fewer_than_six_valid_points():
    summary = trends.summarise(_pts([1, 2, 3, 4, 5]), units="km²", fit_trend=True)
    assert summary["kind"] == "change" and "trend" not in summary and "fewer than 6" in summary["text"]


def test_ols_slope_equals_the_closed_form():
    values = [1.2, 1.9, 2.1, 3.4, 3.3, 4.8, 5.1]
    summary = trends.summarise(_pts(values), units="km²", fit_trend=True)
    x, y = np.arange(2000, 2007, dtype=float), np.array(values)
    b1 = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
    assert summary["kind"] == "trend"
    assert summary["trend"]["slope"] == pytest.approx(b1)
    assert summary["trend"]["slope_units"] == "km² per year"
    assert summary["trend"]["r_squared"] == pytest.approx(summary["trend"]["r"] ** 2)
    assert "not a forecast" in summary["trend"]["note"]


def test_flagged_points_are_shown_but_not_fitted():
    values = [1, 2, 3, 100, 5, 6, 7]   # the 100 is flagged (no-data) and must not pull the line
    record = trends.series_record(key="k", title="T", indicator="I", units="km²", source="S", method="M", caveats=[],
                                  fit_trend=True, x_kind="year", points=_pts(values, flagged=(3,)))
    assert record["n_points"] == 7 and record["n_flagged"] == 1
    assert record["summary"]["n_valid"] == 6 and record["summary"]["trend"]["slope"] == pytest.approx(1.0)


def test_a_series_without_a_trend_line_reports_only_the_change():
    summary = trends.summarise(_pts([3, 1, 4, 1, 5, 9, 2]), units="mm", fit_trend=False)
    assert summary["kind"] == "change" and "no trend line" in summary["text"]


def test_dates_become_decimal_years():
    assert trends._decimal_year("2024-01-01") == 2024.0
    assert 2024.49 < trends._decimal_year("2024-07-01") < 2024.51


def test_dekadal_totals_end_on_the_last_day_and_flag_incomplete_blocks():
    daily = [{"t": f"2024-05-{d:02d}", "value": 1.0} for d in range(1, 26)]  # 1–25 May
    blocks = trends.dekadal_totals(daily, "2024-05-25")
    assert [b["end"] for b in blocks] == ["2024-05-05", "2024-05-15", "2024-05-25"]
    assert blocks[-1]["value"] == 10.0 and not blocks[-1]["flagged"]
    assert blocks[0]["flagged"] and blocks[0]["value"] is None  # 26 Apr – 5 May is only partly inside the window


def test_rainfall_anomaly():
    assert trends.anomaly(940.8, 568.5)["anomaly_text"] == "+65.5% of the 1991–2020 mean"
    assert trends.anomaly(10.0, 0.0)["anomaly_percent"] is None


def test_the_record_round_trips_through_json():
    record = trends.series_record(key="k", title="T", indicator="I", units="km²", source="S", method="M", caveats=["c"],
                                  fit_trend=True, x_kind="year", points=_pts([1, 2, 4, 3, 5, 6, 8]))
    again = json.loads(json.dumps(record))
    assert again == record
    assert trends.summarise(again["points"], units="km²", fit_trend=True) == record["summary"]
