"""FRRIS v1.1: exposure by administrative unit, the pure core (docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md §3–§4).

No Earth Engine and no database here: the boundary units come from a BoundarySource, people from the WorldPop grid
already read by Exposure, buildings from the same server-side ``count`` function. The rule that matters:

    for every extent, Σ over units + "Outside any unit" = the AOI total reported by Exposure
    (buildings exactly; people within max(0.5 person, 0.01% of the total)).

People use the same sub-cell sampling as ``exposure.extent_fraction``: each sub-cell inside the AOI ∩ extent carries the
label of the one unit piece that contains its centre (pieces are disjoint), or the "outside" label. The per-unit
fractions therefore add up to the AOI fraction by construction; the check guards against any later change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import GeometryCollection, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

Level = Literal["L1", "L2", "L3"]
LEVEL_NAMES = {"L1": "Region", "L2": "District", "L3": "Ward"}
OUTSIDE_ID = "_outside"
OUTSIDE_NAME = "Outside any unit"
WARDS_NOT_PROVIDED = "Ward boundaries not yet provided"
PEOPLE_TOLERANCE_ABS = 0.5
PEOPLE_TOLERANCE_REL = 1e-4  # 0.01%
_EQUAL_AREA = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform  # WGS 84 / NSIDC EASE-Grid 2.0


def area_km2(geometry) -> float:
    return shapely_transform(_EQUAL_AREA, geometry).area / 1e6 if not geometry.is_empty else 0.0


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    level: Level
    geometry: Any                    # full unit polygon, EPSG:4326 (not clipped)
    code: str | None = None
    parent: str | None = None        # e.g. the region of a district


@dataclass
class BoundaryUnits:
    level: Level
    units: list[Unit]
    provenance: dict[str, Any]


@dataclass
class NotProvided:
    level: Level
    reason: str
    provenance: dict[str, Any] = field(default_factory=dict)


class BoundarySource(Protocol):
    level: Level

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided: ...


@dataclass(frozen=True)
class Piece:
    unit: Unit | None                # None for "Outside any unit"
    geometry: Any                    # disjoint piece inside the AOI
    area_in_aoi_km2: float
    share_of_unit_in_aoi: float | None

    @property
    def id(self) -> str:
        return self.unit.id if self.unit else OUTSIDE_ID


def disjoint_pieces(units: list[Unit], aoi_geometry: dict) -> list[Piece]:
    """Units clipped to the AOI and made disjoint, plus the "Outside any unit" piece (possibly empty).

    Overlap rule (recorded in provenance): where boundary polygons overlap, the overlap goes to the unit with the
    larger area inside the AOI; ties go to the lower unit id.
    """
    aoi = shape(aoi_geometry).buffer(0)
    clipped = [(unit, unit.geometry.buffer(0).intersection(aoi)) for unit in units]
    clipped = [(unit, geometry) for unit, geometry in clipped if not geometry.is_empty and geometry.area > 0]
    clipped.sort(key=lambda item: (-area_km2(item[1]), item[0].id))
    pieces, taken = [], GeometryCollection()
    for unit, geometry in clipped:
        piece = geometry.difference(taken) if not taken.is_empty else geometry
        if piece.is_empty:
            continue
        taken = unary_union([taken, piece]) if not taken.is_empty else piece
        full = area_km2(unit.geometry.buffer(0))
        inside = area_km2(piece)
        pieces.append(Piece(unit, piece, inside, inside / full if full else None))
    outside = aoi.difference(taken) if not taken.is_empty else aoi
    pieces.append(Piece(None, outside, area_km2(outside), None))
    return pieces


def unit_fractions(transform: Affine, shape_: tuple[int, int], aoi_geometry: dict, pieces: list[Piece], *,
                   include: list[tuple[np.ndarray, Affine]] = (), subcells: int | None = None,
                   chunk_rows: int = 64) -> dict[str, np.ndarray]:
    """Per piece: the fraction of each target cell inside AOI ∩ extent ∩ piece (same sampling as extent_fraction)."""
    from app.services.firris.exposure import sample_mask
    height, width = shape_
    k = subcells or (10 if height * width <= 300_000 else 5)
    out = {piece.id: np.zeros(shape_, dtype=np.float64) for piece in pieces}
    real = [piece for piece in pieces if piece.unit is not None and not piece.geometry.is_empty]
    for r0 in range(0, height, chunk_rows):
        r1 = min(height, r0 + chunk_rows)
        fine = transform * Affine.translation(0, r0) * Affine.scale(1 / k)
        rows_f, cols_f = (r1 - r0) * k, width * k
        inside = rasterize([(aoi_geometry, 1)], out_shape=(rows_f, cols_f), transform=fine, fill=0, dtype="uint8").astype(bool)
        if include:
            cc, rr = np.meshgrid(np.arange(cols_f) + 0.5, np.arange(rows_f) + 0.5)
            xs, ys = fine * (cc, rr)
            for mask, mask_transform in include:
                inside &= sample_mask(mask, mask_transform, np.asarray(xs), np.asarray(ys))
        labels = np.zeros((rows_f, cols_f), dtype=np.int32)  # 0 = outside any unit
        if real:
            labels = rasterize([(mapping(piece.geometry), index + 1) for index, piece in enumerate(real)],
                               out_shape=(rows_f, cols_f), transform=fine, fill=0, dtype="int32")
        for index, piece in enumerate([None, *real]):
            hit = inside & (labels == index)
            key = OUTSIDE_ID if piece is None else piece.id
            out[key][r0:r1] = hit.reshape(r1 - r0, k, width, k).mean(axis=(1, 3))
    return out


def people_tolerance(total: float) -> float:
    return max(PEOPLE_TOLERANCE_ABS, PEOPLE_TOLERANCE_REL * abs(total))


def check_sums(rows: list[dict], totals: dict[str, dict]) -> dict[str, Any]:
    """The invariant per extent: Σ units (incl. outside) vs the AOI totals of Exposure."""
    result = {"ok": True, "extents": {}}
    for extent, total in totals.items():
        people = sum(row["extents"][extent]["people"] for row in rows if extent in row["extents"])
        people_ok = abs(people - total["people"]) <= people_tolerance(total["people"])
        entry = {"people_units": people, "people_total": total["people"], "people_ok": people_ok}
        if total.get("buildings") is not None:
            counts = [row["extents"][extent].get("buildings") for row in rows if extent in row["extents"]]
            if all(c is not None for c in counts):
                units_sum = sum(c for c in counts)
                entry.update(buildings_units=units_sum, buildings_total=total["buildings"],
                             buildings_ok=units_sum == total["buildings"])
            else:
                entry.update(buildings_ok=None)
        entry["ok"] = people_ok and entry.get("buildings_ok") is not False
        result["extents"][extent] = entry
        result["ok"] = result["ok"] and entry["ok"]
    return result


def level_breakdown(source_result: BoundaryUnits | NotProvided, *, population, aoi_geometry: dict,
                    extents: list[tuple[str, str, np.ndarray | None, Affine | None]], totals: dict[str, dict],
                    count: Callable | None, extent_geometries: dict[str, Any]) -> dict[str, Any]:
    """One level's table: rows per unit (plus "Outside any unit"), per extent people and buildings, and the check.

    ``extents``: (key, label, mask or None for the whole area, mask transform) as in exposure_rows.
    ``totals``: per extent {"people": float, "buildings": int | None} from the Exposure rows (≥ 0.75 buildings).
    ``count``: server-side Open Buildings count(geometry) -> {"0.75": {"count": int}, "0.65": {...}}, or None.
    """
    if isinstance(source_result, NotProvided):
        return {"level": source_result.level, "level_name": LEVEL_NAMES[source_result.level], "status": "not_provided",
                "reason": source_result.reason, "provenance": source_result.provenance}
    pieces = disjoint_pieces(source_result.units, aoi_geometry)
    pop, pop_t = population.population, population.transform
    rows = []
    for piece in pieces:
        unit = piece.unit
        rows.append({"unit_id": piece.id, "name": unit.name if unit else OUTSIDE_NAME, "code": unit.code if unit else None,
                     "parent": unit.parent if unit else None, "area_in_aoi_km2": piece.area_in_aoi_km2,
                     "share_of_unit_in_aoi": piece.share_of_unit_in_aoi, "extents": {}})
    for key, label, mask, mask_t in extents:
        fractions = unit_fractions(pop_t, pop.shape, aoi_geometry, pieces, include=[] if mask is None else [(mask, mask_t)])
        extent_geometry = extent_geometries.get(key)
        for row, piece in zip(rows, pieces):
            values: dict[str, Any] = {"people": float((pop * fractions[piece.id]).sum())}
            if count is not None and extent_geometry is not None and totals.get(key, {}).get("buildings") is not None:
                geometry = piece.geometry.intersection(extent_geometry) if key != "whole_area" else piece.geometry
                if geometry.is_empty:
                    values.update(buildings=0, buildings_065=0)
                else:
                    counted = count(geometry)
                    values.update(buildings=int(counted["0.75"]["count"]), buildings_065=int(counted["0.65"]["count"]))
            row["extents"][key] = values
    check = check_sums(rows, totals)
    outside = next(row for row in rows if row["unit_id"] == OUTSIDE_ID)
    shown = [row for row in rows if row["unit_id"] != OUTSIDE_ID]
    if any(abs(v["people"]) > 0 or v.get("buildings") for v in outside["extents"].values()) or outside["area_in_aoi_km2"] > 1e-6:
        shown.append(outside)
    record = {"level": source_result.level, "level_name": LEVEL_NAMES[source_result.level],
              "status": "assessed" if check["ok"] else "not_available",
              "reason": None if check["ok"] else ("The units do not add up to the area totals for this level; the "
                                                   "breakdown is withheld rather than rescaled."),
              "rows": shown, "check": check, "provenance": source_result.provenance,
              "overlap_rule": "Overlapping boundary areas go to the unit with the larger area inside the AOI; ties to the lower unit id."}
    return record
