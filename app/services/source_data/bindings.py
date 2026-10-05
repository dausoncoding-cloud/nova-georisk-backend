"""Resolve exact approved sources and fail closed on project, time and CRS/datum."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pyproj import CRS
from shapely.geometry import shape
from sqlalchemy.orm import Session

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.source_data.readiness import ReadySource, SourceNotReady, load_registered_source
from app.services.source_data.results import ReadyHazardResult, ReadyVulnerabilityResult, load_hazard_result, load_vulnerability_result
from app.services.source_data.risk_results import ReadyRiskResult, load_risk_results
from app.services.source_data.physical_results import ReadyPhysicalResult, load_physical_results
from app.services.source_data.temporal_results import ReadyAEPResult, load_aep_result
from app.services.source_data.temporal_sources import validate_annual_sources, validate_duration_sources


MODULE_SOURCE_ROLES: dict[str, dict[str, str]] = {
    "flood_change": {"before": "inundation_time_slice", "after": "inundation_time_slice"},
    "satellite_preprocessing": {},
    "hazard": {"rainfall": "rainfall_stations", "terrain": "terrain_dem", "river_network": "river_drainage_network", "land_cover": "land_cover", "soil": "soil_permeability"},
    "exposure": {"population": "population_density", "buildings": "buildings", "roads": "roads", "critical_infrastructure": "critical_infrastructure", "cropland": "cropland_fraction", "livestock": "livestock_density"},
    "vulnerability": {"indicators": "vulnerability_indicators", "boundaries": "administrative_boundaries"},
    "insecurity": {"capacity": "community_capacity_indicators", "boundaries": "administrative_boundaries"},
    "risk": {},
    "resilience": {"capacity": "community_capacity_indicators", "boundaries": "administrative_boundaries"},
    "flood_depth": {"water_surface": "water_surface_elevation", "terrain": "terrain_dem"},
    "flood_velocity": {"model_velocity": "hydraulic_model_velocity"},
    "flood_hazard_product": {},
    "flood_aep": {},
    "flood_return_period": {},
    "flood_duration": {},
    "flood_susceptibility": {},
    "flood_hazard_zonation": {},
}
MODULE_RESULT_ROLES: dict[str, dict[str, str]] = {
    "exposure": {"hazard": "source_bound_hazard"},
    "insecurity": {"vulnerability": "source_bound_vulnerability"},
    "risk": {"hazard": "source_bound_hazard", "exposure": "source_bound_exposure", "insecurity": "source_bound_insecurity"},
    "flood_hazard_product": {"depth": "source_bound_flood_depth", "velocity": "source_bound_flood_velocity"},
    "flood_return_period": {"aep": "source_bound_flood_aep"},
    "flood_susceptibility": {"hazard": "source_bound_hazard"},
    "flood_hazard_zonation": {"depth": "source_bound_flood_depth", "velocity": "source_bound_flood_velocity"},
}
OPTIONAL_SOURCE_ROLES: dict[str, dict[str, str]] = {"satellite_preprocessing": {"climate": "rainfall_stations", "soil": "soil_permeability", "population": "population_density", "roads": "roads", "rivers": "river_drainage_network", "land_cover": "land_cover", "terrain": "terrain_dem"}, "exposure": {"economic_assets": "economic_assets"}}
EXECUTABLE_MODULES = frozenset({"flood_change", "satellite_preprocessing", "hazard", "exposure", "vulnerability", "insecurity", "risk", "resilience", "flood_depth", "flood_velocity", "flood_hazard_product", "flood_aep", "flood_return_period", "flood_duration", "flood_susceptibility", "flood_hazard_zonation"})


@dataclass(frozen=True)
class ResolvedBindings:
    request: SourceBoundAnalysisRequest
    sources: dict[str, ReadySource]
    alignment: dict[str, dict]
    upstream: dict[str, ReadyHazardResult | ReadyVulnerabilityResult | ReadyRiskResult | ReadyPhysicalResult | ReadyAEPResult] = field(default_factory=dict)

    def lineage(self) -> dict:
        return {role: source.lineage() for role, source in self.sources.items()}


def binding_contract() -> dict:
    return {
        module: {
            "source_roles": roles,
            "optional_source_roles": OPTIONAL_SOURCE_ROLES.get(module, {}),
            "upstream_result_roles": MODULE_RESULT_ROLES.get(module, {}),
            "source_role_pattern": ("year_<YYYY> (at least 10 consecutive complete years)" if module == "flood_aep"
                                    else "slice_<zero-based index> (at least 3 fixed-cadence snapshots)" if module == "flood_duration"
                                    else None),
            "executable": module in EXECUTABLE_MODULES,
        }
        for module, roles in MODULE_SOURCE_ROLES.items()
    }


def resolve_bindings(db: Session, request: SourceBoundAnalysisRequest, *, root: Path | None = None,
                     aoi_geometry: dict | None = None) -> ResolvedBindings:
    required = MODULE_SOURCE_ROLES[request.module]
    if request.module == "flood_aep":
        required = {role: "annual_inundation_observation" for role in request.sources}
    elif request.module == "flood_duration":
        required = {role: "inundation_time_slice" for role in request.sources}
    optional = OPTIONAL_SOURCE_ROLES.get(request.module, {})
    if (not set(required).issubset(request.sources) or not set(request.sources).issubset(set(required) | set(optional))
            or set(request.upstream_results) != set(MODULE_RESULT_ROLES.get(request.module, {}))):
        raise SourceNotReady("Source/result roles do not match the FIRRIS module binding contract")
    if len(set(request.sources.values())) != len(request.sources):
        raise SourceNotReady("The same source dataset cannot fill multiple distinct roles")
    if request.module in {"flood_change", "satellite_preprocessing", "hazard", "exposure", "risk", "flood_depth", "flood_velocity", "flood_hazard_product", "flood_aep", "flood_return_period", "flood_duration", "flood_susceptibility", "flood_hazard_zonation"} and request.target_grid is None:
        raise SourceNotReady("Raster-backed modules require an explicit target grid")
    if request.module in {"vulnerability", "insecurity", "resilience"} and request.target_grid is not None:
        raise SourceNotReady("Survey modules use reviewed boundary spatial units, not a raster target grid")
    sources = {}
    if aoi_geometry is None:
        raise SourceNotReady("AOI geometry is required for source co-registration")
    aoi = shape(aoi_geometry)
    if aoi.is_empty or not aoi.is_valid:
        raise SourceNotReady("AOI geometry is invalid")
    aw, asouth, ae, anorth = aoi.bounds
    for role, category in {**required, **{name: optional[name] for name in request.sources if name in optional}}.items():
        source = load_registered_source(db, request.sources[role], request.project_id, root=root)
        manifest = source.manifest
        if manifest.category != category:
            raise SourceNotReady(f"Source role {role} requires category {category}")
        if (request.module not in {"flood_change", "flood_aep", "flood_duration"}
                and (manifest.temporal_coverage.start > request.period.start
                     or manifest.temporal_coverage.end < request.period.end)):
            raise SourceNotReady(f"Source role {role} does not cover the requested analysis period")
        coverage = manifest.geographic_coverage
        if not (coverage.west <= aw and coverage.south <= asouth and coverage.east >= ae and coverage.north >= anorth):
            raise SourceNotReady(f"Source role {role} does not cover the AOI")
        try:
            CRS.from_user_input(manifest.crs)
        except Exception as exc:
            raise SourceNotReady("Source CRS is invalid") from exc
        sources[role] = source
    datums = {source.manifest.vertical_datum for source in sources.values() if source.manifest.vertical_datum}
    if len(datums) > 1:
        raise SourceNotReady("Bound source vertical datums are incompatible")
    if request.target_grid:
        try:
            CRS.from_user_input(request.target_grid.crs)
        except Exception as exc:
            raise SourceNotReady("Target grid CRS is invalid") from exc
        from rasterio.warp import transform_bounds
        west, south, east, north = transform_bounds("EPSG:4326", request.target_grid.crs, *aoi.bounds, densify_pts=21)
        grid = request.target_grid
        if not (grid.west <= west and grid.south <= south and grid.east >= east and grid.north >= north):
            raise SourceNotReady("Target raster grid does not cover the complete AOI")
    if request.module == "hazard":
        grid = request.target_grid
        crs = CRS.from_user_input(grid.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
            raise SourceNotReady("Hazard requires a projected metric target grid")
        cell_x = (grid.east - grid.west) / grid.width
        cell_y = (grid.north - grid.south) / grid.height
        if abs(cell_x - cell_y) > max(cell_x, cell_y) * 1e-6:
            raise SourceNotReady("Hazard D8 flow routing requires square metric cells")
        if grid.width * grid.height > 25_000:
            raise SourceNotReady("Hazard grid exceeds the reviewed 25,000-cell execution limit")
        if request.hazard_options.drainage_window_m < cell_x:
            raise SourceNotReady("Drainage-density window must cover at least one target cell")
        if not sources["terrain"].evidence.get("checks", {}).get("hydrologic_coverage_verified"):
            raise SourceNotReady("DEM upstream hydrologic coverage requires administrator review")
        if not sources["terrain"].evidence.get("checks", {}).get("dem_conditioning_verified"):
            raise SourceNotReady("DEM hydrologic conditioning requires administrator review")
        if sources["terrain"].manifest.crs != grid.crs:
            raise SourceNotReady("DEM derivatives require the approved DEM and target grid to share a metric CRS")
        if sources["rainfall"].manifest.observation_interval_hours is None:
            raise SourceNotReady("Rainfall observation interval is required to derive mm/h intensity")
        if sources["land_cover"].manifest.land_cover_scheme is None:
            raise SourceNotReady("Land-cover source requires an exact FIRRIS scoring scheme")
    if request.module == "exposure":
        grid = request.target_grid
        crs = CRS.from_user_input(grid.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
            raise SourceNotReady("Exposure requires a projected metric target grid")
        if grid.width * grid.height > 25_000:
            raise SourceNotReady("Exposure grid exceeds the reviewed 25,000-cell execution limit")
        for role in ("buildings", "roads", "critical_infrastructure", "economic_assets"):
            if role in sources and not sources[role].evidence.get("checks", {}).get("coverage_complete_verified"):
                raise SourceNotReady(f"{role} AOI inventory completeness requires administrator review")
        for role, types in {"buildings": {"residential"},
                            "critical_infrastructure": {"school", "hospital", "power"},
                            "economic_assets": {"industrial", "commercial"}}.items():
            if role in sources and not types.issubset(set(sources[role].manifest.inventory_asset_types or [])):
                raise SourceNotReady(f"{role} lacks a reviewed required asset-type inventory")
    if request.module == "risk":
        grid = request.target_grid
        crs = CRS.from_user_input(grid.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
            raise SourceNotReady("Risk requires the exact projected metric Hazard/Exposure grid")
        if grid.width * grid.height > 25_000:
            raise SourceNotReady("Risk grid exceeds the reviewed 25,000-cell execution limit")
    if request.module in {"flood_change", "flood_depth", "flood_velocity", "flood_hazard_product", "flood_aep", "flood_return_period", "flood_duration", "flood_susceptibility", "flood_hazard_zonation"}:
        grid = request.target_grid
        crs = CRS.from_user_input(grid.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
            raise SourceNotReady("Physical flood products require a projected metric target grid")
        if grid.width * grid.height > 25_000:
            raise SourceNotReady("Physical flood product grid exceeds the reviewed 25,000-cell limit")
    if request.module == "flood_depth" and (
        not sources["water_surface"].manifest.vertical_datum
        or sources["water_surface"].manifest.vertical_datum != sources["terrain"].manifest.vertical_datum
    ):
        raise SourceNotReady("Water surface and DEM require the same explicit vertical datum")
    if request.module == "flood_velocity" and not sources["model_velocity"].evidence.get("checks", {}).get("hydraulic_model_verified"):
        raise SourceNotReady("Hydraulic-model velocity requires administrator model review")
    boundary = sources.get("boundaries")
    if boundary:
        for source in sources.values():
            if source.manifest.category.endswith("_indicators") and source.manifest.spatial_unit_reference != boundary.manifest.source_id:
                raise SourceNotReady("Survey spatial-unit reference does not match the bound boundary source")
    alignment = {}
    if request.target_grid:
        from app.services.source_data.alignment import align_raster_bundle
        raster_sources = {role: source for role, source in sources.items() if source.manifest.category in {"terrain_dem", "soil_permeability", "land_cover", "population_density", "cropland_fraction", "livestock_density"}}
        _, _, alignment = align_raster_bundle(raster_sources, request.target_grid, aoi_geometry)
    upstream = {}
    if request.module == "exposure":
        upstream["hazard"] = load_hazard_result(db, request.upstream_results["hazard"], request, root=root)
    if request.module == "insecurity":
        upstream["vulnerability"] = load_vulnerability_result(
            db, request.upstream_results["vulnerability"], request,
            boundary=sources["boundaries"], aoi_geometry=aoi_geometry, root=root,
        )
    if request.module == "risk":
        upstream.update(load_risk_results(db, request, aoi_geometry=aoi_geometry, root=root))
    if request.module == "flood_hazard_product":
        upstream.update(load_physical_results(db, request, aoi_geometry=aoi_geometry, root=root))
    if request.module == "flood_aep":
        _, _, alignment["annual_record"] = validate_annual_sources(request, sources, aoi_geometry)
    if request.module == "flood_change":
        from app.services.source_data.change import validate_change_sources
        _, _, alignment["change_record"] = validate_change_sources(request, sources, aoi_geometry)
    if request.module == "flood_duration":
        _, _, alignment["duration_series"] = validate_duration_sources(request, sources, aoi_geometry)
    if request.module == "flood_return_period":
        upstream["aep"] = load_aep_result(db, request, aoi_geometry=aoi_geometry, root=root)
    if request.module == "flood_susceptibility":
        upstream["hazard"] = load_hazard_result(db, request.upstream_results["hazard"], request, root=root)
        from app.schemas.source_data import TemporalCoverage
        meta = upstream["hazard"].result.output_files["flood_hazard"]["gis_metadata"]
        if TemporalCoverage.model_validate(meta["target_period"]) != request.period:
            raise SourceNotReady("Susceptibility predictor period must exactly match approved Hazard period")
    if request.module == "flood_hazard_zonation":
        upstream.update(load_physical_results(db, request, aoi_geometry=aoi_geometry, root=root))
    if request.module == "satellite_preprocessing":
        if not sources:
            raise SourceNotReady("Preprocessing requires explicitly bound sources")
        crs = CRS.from_user_input(request.target_grid.crs)
        if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
            raise SourceNotReady("Preprocessing requires a projected metric target grid")
        if request.target_grid.width * request.target_grid.height > 25_000:
            raise SourceNotReady("Preprocessing grid exceeds bounded 25,000-cell policy")
        if bool(request.satellite_options.terrain_products) != ("terrain" in sources):
            raise SourceNotReady("Requested terrain metrics require one explicitly bound DEM")
        for role in ("roads", "rivers"):
            if role in sources and not sources[role].evidence.get("checks", {}).get("coverage_complete_verified"):
                raise SourceNotReady("Network covariates require reviewed complete coverage")
        if "terrain" in sources:
            checks = sources["terrain"].evidence.get("checks", {})
            if not checks.get("hydrologic_coverage_verified") or not checks.get("dem_conditioning_verified"):
                raise SourceNotReady("Terrain metrics require reviewed conditioning and upstream coverage")
    return ResolvedBindings(request, sources, alignment, upstream)
