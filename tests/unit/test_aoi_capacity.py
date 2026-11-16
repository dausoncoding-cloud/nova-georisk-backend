"""P6 area playground: the capacity check uses the preflight's rule and offers trim / split / coarser options."""
import pytest
from shapely.geometry import box, mapping, shape

from app.services.firris import aoi_capacity, preflight
from app.services.firris.aoi_capacity import MAX_PARTS, assess_area

RUFIJI = {"type": "Polygon", "coordinates": [[[38.92, -7.99], [39.01, -7.99], [39.01, -7.9], [38.92, -7.9], [38.92, -7.99]]]}
# A long, diagonal shape: modest area, large bounding box (Kilombero-like).
DIAGONAL = {"type": "Polygon", "coordinates": [[[36.0, -8.6], [36.3, -8.5], [36.32, -8.2], [36.02, -8.25], [36.0, -8.6]]]}
LIMIT = preflight.REQUEST_LIMIT_BYTES


def test_uses_exactly_the_preflight_capacity_rule():
    result = assess_area(RUFIJI)
    assert result["capacity"] == preflight.capacity_estimate(shape(RUFIJI).bounds, 30.0)
    assert result["status"] == "fits" and result["message"] == "Fits comfortably in one analysis."
    assert round(result["capacity"]["estimated_request_bytes"] / 1_048_576, 1) == 10.0  # the preflight's 10.0 of 48 MiB
    assert result["area_km2"] == pytest.approx(98.8, abs=0.1) and result["trim"] is None and result["split"] is None


def test_near_the_limit_is_reported_as_near():
    # A box whose request is ~95% of the limit at 30 m.
    side = 0.0
    for step in range(1, 400):
        candidate = step * 0.001
        if preflight.capacity_estimate((0, 0, candidate, candidate), 30.0)["estimated_request_bytes"] > 0.95 * LIMIT:
            side = candidate
            break
    result = assess_area(mapping(box(30.0, -5.0, 30.0 + side, -5.0 + side)))
    assert result["status"] == "near" and "close to the limit" in result["message"]


def test_oversize_area_gets_three_options_that_each_fit():
    result = assess_area(DIAGONAL)
    assert result["status"] == "over" and result["capacity"]["estimated_request_bytes"] > LIMIT
    assert "times the 48 MiB limit" in result["message"]
    trim = result["trim"]
    assert trim["capacity"]["estimated_request_bytes"] <= LIMIT
    assert shape(trim["geometry"]).within(shape(DIAGONAL).buffer(1e-9))  # only the part of the area inside the box
    split = result["split"]
    assert 2 <= len(split["parts"]) <= MAX_PARTS
    assert all(part["capacity"]["estimated_request_bytes"] <= LIMIT for part in split["parts"])
    union = shape(split["parts"][0]["geometry"])
    for part in split["parts"][1:]:
        union = union.union(shape(part["geometry"]))
    assert union.symmetric_difference(shape(DIAGONAL)).area < 1e-9  # the parts cover the whole area, no overlap
    assert result["coarser"]["scale_m"] == 60.0 and result["coarser"]["capacity"]["estimated_request_bytes"] <= LIMIT


def test_trim_box_follows_the_requested_centre_and_stays_inside_the_bounding_box():
    west, south, east, north = shape(DIAGONAL).bounds
    centred = assess_area(DIAGONAL)["trim"]["box"]
    moved = assess_area(DIAGONAL, trim_center=[east, north])["trim"]["box"]
    assert moved != centred
    assert moved[2] == pytest.approx(east) and moved[3] == pytest.approx(north)  # clamped to the bounding box
    assert moved[2] - moved[0] == pytest.approx(centred[2] - centred[0])


def test_coarser_falls_back_to_the_preflight_suggestion_when_60_m_is_not_enough():
    huge = mapping(box(30.0, -9.0, 31.5, -7.5))
    result = assess_area(huge)
    assert result["coarser"]["scale_m"] == preflight.capacity_estimate(shape(huge).bounds, 30.0)["suggested_scale_m"]
    assert result["coarser"]["scale_m"] > 60


def test_invalid_or_oversized_geometry_is_refused_with_a_plain_message():
    with pytest.raises(ValueError, match="Polygon or MultiPolygon"):
        assess_area({"type": "Point", "coordinates": [30, -5]})
    with pytest.raises(ValueError, match="Invalid AOI geometry"):
        assess_area({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]})
    ring = [[30 + i * 1e-6, -5.0] for i in range(aoi_capacity.MAX_VERTICES)] + [[30.0, -4.0], [30.0, -5.0]]
    with pytest.raises(ValueError, match="more than 20,000 vertices"):
        assess_area({"type": "Polygon", "coordinates": [ring]})
    with pytest.raises(ValueError, match="EPSG:4326"):
        assess_area(mapping(box(500000, 9000000, 510000, 9010000)))


def test_never_calls_the_provider(monkeypatch):
    monkeypatch.setattr(preflight, "scene_availability", lambda *_: pytest.fail("provider queried"))
    assess_area(DIAGONAL)
