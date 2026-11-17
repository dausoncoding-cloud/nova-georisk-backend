"""Read-only acquisition of WorldPop R2025A population over an AOI (Depth & Exposure module, plan item 2.1).

The constrained 100 m product (``WorldPop/GP/100m/R2025A/v1/pop``) is read on its native 3-arc-second grid with
Earth Engine ``computePixels`` (row blocks under the request limit), unmasked to 0 (no settlement = no people).
Nothing is exported. Sources and the year labels: docs/FRRIS_DEPTH_EXPOSURE_IMPLEMENTATION_PLAN.md §2a.3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rasterio.transform import Affine
from shapely.geometry import shape

from app.services.gee.glofas_hazard import HazardUnavailable, native_grid, row_blocks

WORLDPOP_ASSET = "WorldPop/GP/100m/R2025A/v1/pop"
WORLDPOP_RELEASE = "R2025A v1 (alpha release, September 2025)"
FIRST_YEAR, LAST_YEAR = 2015, 2030
MAX_CELLS = 6_000_000
WORLDPOP_CITATION = ("Bondarenko M., Priyatikanto R., Tejedor-Garavito N., Zhang W., McKeen T., Cunningham A., Woods T., "
                     "Hilton J., Cihan D., Nosatiuk B., Brinkhoff T., Tatem A., Sorichetta A. 2025. Constrained estimates of "
                     "2015-2030 total number of people per grid square at a resolution of 3 arc (approximately 100m at the "
                     "equator) R2025A version v1. WorldPop, University of Southampton. doi:10.5258/SOTON/WP00839")
WORLDPOP_LICENCE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
# Census inputs per country (WorldPop global2_census_data_sources_R2025A_v1.xlsx; plan §2a.3). Every year is modelled
# and scaled to UN World Population Prospects 2024 national totals; years between the inputs are interpolated, later
# years are projected.
CENSUS_INPUT_YEARS = {"TZA": (2012, 2022)}


class PopulationUnavailable(HazardUnavailable):
    """WorldPop cannot be provided for this AOI (the reason is shown to the user)."""


def population_year(event_year: int) -> int:
    """The WorldPop year used for an event: the event year, clamped to the 2015–2030 series."""
    return min(max(int(event_year), FIRST_YEAR), LAST_YEAR)


def year_status(countries: list[str], year: int) -> dict[str, Any]:
    """How the population of ``year`` was made: census-anchored, interpolated or projected (plain words for reports)."""
    known = [CENSUS_INPUT_YEARS.get(c) for c in countries]
    if not known or None in known or len(set(known)) != 1:  # every country must have the same recorded census years
        return {"status": "modelled", "census_input_years": None,
                "text": f"modelled estimate for {year} (WorldPop {WORLDPOP_RELEASE}); census input years not recorded for "
                        f"{', '.join(countries) or 'this area'}"}
    first, last = known[0]
    if year > last:
        status, words = "projected", f"a projection {year - last} year{'s' if year - last != 1 else ''} after the last census ({last})"
    elif year == last:
        status, words = "census-anchored", f"anchored on the {last} census"
    elif year == first:
        status, words = "census-anchored", f"anchored on the {first} census"
    else:
        status, words = "interpolated", f"interpolated between the {first} and {last} censuses"
    return {"status": status, "census_input_years": [first, last],
            "text": f"modelled estimate for {year}, {words}; national totals scaled to UN World Population Prospects 2024 "
                    f"(WorldPop {WORLDPOP_RELEASE})"}


@dataclass
class PopulationGrid:
    population: np.ndarray            # people per cell (0 = no settlement / no data)
    transform: Affine
    year: int
    requested_year: int
    countries: list[str]
    images: list[str] = field(default_factory=list)
    crs: str = "EPSG:4326"

    def provenance(self) -> dict[str, Any]:
        return {"asset": WORLDPOP_ASSET, "release": WORLDPOP_RELEASE, "year": self.year, "requested_year": self.requested_year,
                "countries": self.countries, "images": self.images, "crs": self.crs,
                "grid_transform": list(self.transform)[:6], "shape": list(self.population.shape),
                "resampling": "none (native grid)", "masked_cells": "no settlement: 0 people"}


def acquire_worldpop(aoi_geometry: dict, event_year: int) -> PopulationGrid:
    import ee

    from app.services.gee import auth

    auth.initialize_gee()
    year = population_year(event_year)
    aoi = ee.Geometry(aoi_geometry)
    collection = ee.ImageCollection(WORLDPOP_ASSET).filterBounds(aoi).filter(ee.Filter.eq("year", year))
    meta = collection.aggregate_array("system:index").getInfo()
    if not meta:
        raise PopulationUnavailable(f"WorldPop {WORLDPOP_RELEASE} has no population grid for this area in {year}.")
    countries = sorted({index.split("_")[0] for index in meta})
    projection = collection.first().projection().getInfo()
    sx, _, ox, _, sy, oy = projection["transform"]
    transform, width, height = native_grid(ox, oy, sx, sy, shape(aoi_geometry).bounds)
    if width * height > MAX_CELLS:
        raise PopulationUnavailable(f"The area is too large for the exposure estimate ({width * height:,} population cells; "
                                    f"limit {MAX_CELLS:,}). Split the area.")
    image = collection.mosaic().select(["population"]).toFloat().unmask(0)
    out = np.zeros((height, width), dtype=np.float32)
    for start, stop in row_blocks(height, width, 1):
        block = transform * Affine.translation(0, start)
        data = ee.data.computePixels({
            "expression": image, "fileFormat": "NUMPY_NDARRAY",
            "grid": {"dimensions": {"width": width, "height": stop - start},
                     "affineTransform": {"scaleX": block.a, "shearX": 0, "translateX": block.c,
                                         "shearY": 0, "scaleY": block.e, "translateY": block.f},
                     "crsCode": "EPSG:4326"}})
        out[start:stop] = data["population"]
    out[~np.isfinite(out) | (out < 0)] = 0
    return PopulationGrid(population=out, transform=transform, year=year, requested_year=int(event_year),
                          countries=countries, images=list(meta))
