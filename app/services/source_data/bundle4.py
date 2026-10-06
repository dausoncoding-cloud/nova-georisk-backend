"""Reviewed source workflows for F01/F02/F03/F05/F06/F09/F10.

Uses existing FIRRIS mathematics and source-bound, reviewed policies. Missing
catalogues, soil score tables, observed records and validation are never filled
with production defaults. Synthetic fixture scores are not specification facts.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds, xy, rowcol, array_bounds
from rasterio.warp import transform_geom, reproject, Resampling
from shapely.geometry import MultiPoint, Point, shape
from shapely.ops import transform as transform_shape, unary_union

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.hydrology.interpolation import idw_interpolate, leave_one_out_cross_validate
from app.services.hydrology.kriging import fit_variogram, ordinary_kriging
from app.services.hydrology.rainfall import normalize_rainfall_index
from app.services.hydrology.water_level import interpolate_water_level
from app.services.hydrology.watershed import compute_flow_direction, _D8_NEIGHBOURS
from app.services.maps.export import RasterSpec, write_cog
from app.services.maps.flood_products import probability_to_return_period
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.alignment import align_raster_source
from app.services.reporting.complete_report import _spreadsheet_safe
from app.services.source_data.satellite_preprocessing import terrain_metrics
from app.services.statistics.correlation import correlation_report
from app.services.statistics.mlr import fit_mlr
from app.services.statistics.entropy_weight import entropy_weights, apply_weighted_index, IndicatorDirection

LIMITATIONS = ["Source readiness is administrator-reviewed evidence, not independent scientific certification.",
               "No model accuracy, calibration or live-service validation is asserted for unbound real observations."]


def clean(value):
    """Undefined diagnostics serialize as null; never fabricate a finite number."""
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def records(source):
    return list(csv.DictReader(io.StringIO(source.data.decode("utf-8-sig"))))


def stamp(row):
    return datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))


def reviewed_policy(source, reference, check):
    if (not source.evidence.get("checks", {}).get(check)
            or reference not in source.evidence.get("evidence_refs", [])):
        raise SourceNotReady("Scoring policy/catalogue needs explicit source-bound administrator review and matching evidence reference")


def grid_context(request, aoi):
    grid = request.target_grid
    if grid is None or grid.width * grid.height > 25_000:
        raise SourceNotReady("Source workflow requires a bounded 25,000-cell target grid")
    crs = CRS.from_user_input(grid.crs)
    if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
        raise SourceNotReady("Source workflow requires projected metre coordinates")
    if crs.to_epsg() is None:
        raise SourceNotReady("Source workflow exports require an identifiable EPSG CRS")
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    mask = geometry_mask([transform_geom("EPSG:4326", grid.crs, aoi)], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not mask.any():
        raise SourceNotReady("Grid has no AOI cells")
    rows, columns = np.where(mask)
    xs, ys = xy(transform, rows, columns, offset="center")
    return transform, mask, np.column_stack((xs, ys))


def snapshot_samples(source, request, queries, field):
    if request.period.start != request.period.end:
        raise SourceNotReady("Stage interpolation requires one exact observed instant, not an invented aggregate")
    selected = [row for row in records(source) if stamp(row) == request.period.start]
    if not 3 <= len(selected) <= 100 or len({row["station_id"] for row in selected}) != len(selected):
        raise SourceNotReady("Snapshot requires 3–100 unique observed stations")
    projection = Transformer.from_crs("EPSG:4326", request.target_grid.crs, always_xy=True)
    coordinates = np.asarray([projection.transform(float(row["longitude"]), float(row["latitude"])) for row in selected])
    if not np.isfinite(coordinates).all():
        raise SourceNotReady("Stage station projection is nonfinite")
    if len(np.unique(coordinates, axis=0)) != len(coordinates) or np.linalg.matrix_rank(coordinates - coordinates.mean(axis=0)) != 2:
        raise SourceNotReady("Stations must have distinct noncollinear positions")
    hull = MultiPoint(coordinates).convex_hull
    if any(not hull.covers(Point(*query)) for query in queries):
        raise SourceNotReady("Interpolation would extrapolate outside the station hull")
    values = np.asarray([float(row[field]) for row in selected])
    if not np.isfinite(values).all():
        raise SourceNotReady("Station observations are not finite")
    return selected, coordinates, values


def rainfall_products(request, sources, queries):
    from app.services.source_data.stations import rainfall_samples
    coords, values, record = rainfall_samples(sources["rainfall"], request, queries[:, 0], queries[:, 1])
    options = request.rainfall_options
    if options.method == "idw":
        power = options.power if options.power is not None else 2
        surface = idw_interpolate(coords, values, queries, power)
        cv = leave_one_out_cross_validate(coords, values, power)
        record.update(method="IDW", power=power, cross_validation=cv)
        products = {"rainfall_intensity": (surface, "mm/h")}
    else:
        if len(coords) < 6 or np.ptp(values) == 0:
            raise SourceNotReady("Kriging refitted leave-one-out QA requires at least six stations and variable observations")
        def fitted(c, v):
            try:
                variogram = fit_variogram(c, v, model=options.variogram_model or "spherical")
            except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
                raise SourceNotReady("Kriging variogram fit is unsupported by these observations") from exc
            if (not variogram.fit_converged or not np.isfinite([variogram.nugget, variogram.sill, variogram.range_]).all()
                    or variogram.sill < variogram.nugget or variogram.sill <= 0 or variogram.nugget < 0 or variogram.range_ <= 0):
                raise SourceNotReady("Kriging variogram did not converge to an admissible model")
            return variogram
        variogram = fitted(coords, values)
        surface, variance = ordinary_kriging(coords, values, queries, variogram)
        predictions = np.empty(len(values))
        folds = []
        for index in range(len(values)):
            keep = np.arange(len(values)) != index
            fold = fitted(coords[keep], values[keep])
            predictions[index] = ordinary_kriging(coords[keep], values[keep], coords[index:index+1], fold)[0][0]
            folds.append({"station_id": record["station_ids"][index], "observed_mm_h": values[index],
                          "predicted_mm_h": predictions[index], "variogram": asdict(fold)})
        if not np.isfinite(predictions).all() or (predictions < 0).any():
            raise SourceNotReady("Kriging cross-validation produced invalid rainfall intensities")
        errors = predictions - values
        cv = {"me": errors.mean(), "mae": np.abs(errors).mean(), "rmse": np.sqrt(np.mean(errors**2)),
              "r_squared": 1 - np.sum(errors**2) / np.sum((values-values.mean())**2)}
        if not np.isfinite(variance).all() or (variance < 0).any():
            raise SourceNotReady("Kriging prediction variance is invalid")
        record.update(method="ordinary_kriging", variogram=asdict(variogram), cross_validation=cv,
                      cross_validation_folds=folds,
                      validation_method="leave-one-station-out; variogram refitted independently in each training fold")
        products = {"rainfall_intensity": (surface, "mm/h"), "rainfall_kriging_variance": (variance, "(mm/h)^2")}
    if not np.isfinite(surface).all() or (surface < 0).any():
        raise SourceNotReady("Rainfall interpolation produced invalid/negative intensities; no clipping is permitted")
    products["rainfall_index"] = (normalize_rainfall_index(surface), "index_0_1")
    record["index_basis"] = {"minimum_mm_h": surface.min(), "maximum_mm_h": surface.max(), "scope": "valid AOI cells"}
    return products, record


def stage_products(request, sources, queries):
    gauges, coords, values = snapshot_samples(sources["gauges"], request, queries, "stage_m")
    thresholds = [row for row in records(sources["thresholds"]) if stamp(row) == request.period.start]
    by_id = {row["station_id"]: row for row in thresholds}
    if len(by_id) != len(thresholds) or set(by_id) != {row["station_id"] for row in gauges}:
        raise SourceNotReady("Bankfull thresholds must match every observed gauge exactly")
    for gauge in gauges:
        threshold = by_id[gauge["station_id"]]
        if any(float(threshold[key]) != float(gauge[key]) for key in ("longitude", "latitude")):
            raise SourceNotReady("Threshold station position differs from its gauge")
    datums = {source.manifest.vertical_datum for source in sources.values()}
    if None in datums or len(datums) != 1:
        raise SourceNotReady("Stage and thresholds require one shared explicit vertical datum")
    levels = {float(row["bankfull_stage_m"]) for row in thresholds}
    references = {row["threshold_reference"] for row in thresholds}
    if len(levels) != 1 or len(references) != 1:
        raise SourceNotReady("Existing stage formula requires one sourced common-datum bankfull threshold; local thresholds are unsupported")
    threshold = levels.pop()
    result = interpolate_water_level(coords, values, queries, threshold)
    return {"river_stage": (result.surface_values, "m"), "bankfull_exceedance": (result.exceedance, "m"),
            "water_level_index": (result.normalized_index, "index_0_1")}, {
                "method": "existing IDW water-level formula; power=2", "bankfull_stage_m": threshold,
                "threshold_reference": references.pop(), "vertical_datum": next(iter(datums)),
                "observed_at": request.period.start.isoformat(), "station_count": len(gauges),
                "cross_validation": leave_one_out_cross_validate(coords, values), "surface_statistics": result.summary,
                "index_basis": {"minimum_m": result.surface_values.min(), "maximum_m": result.surface_values.max(), "scope": "valid AOI cells"}}


def proximity_products(request, sources, queries):
    transformer = Transformer.from_crs("EPSG:4326", request.target_grid.crs, always_xy=True)
    raw = {}
    for role, source in sources.items():
        reviewed_policy(source, request.proximity_options.policy_reference, "scoring_policy_verified")
        if (source.manifest.proximity_scoring_policy is None
                or source.manifest.proximity_scoring_policy.model_dump() != request.proximity_options.model_dump()):
            raise SourceNotReady("Proximity normalization/directions differ from the source-reviewed policy")
        if not source.evidence.get("checks", {}).get("coverage_complete_verified"):
            raise SourceNotReady("Feature distances require reviewed inventory/network coverage completeness")
        features = json.loads(source.data)["features"]
        if any(not request.period.start <= stamp(feature["properties"]) <= request.period.end for feature in features):
            raise SourceNotReady("Proximity features are outside the declared analysis period")
        network = unary_union([transform_shape(transformer.transform, shape(feature["geometry"])) for feature in features])
        if network.is_empty:
            raise SourceNotReady("Feature-distance target inventory is empty")
        raw[role] = np.asarray([Point(*query).distance(network) for query in queries])
    frame = pd.DataFrame(raw)
    if not np.isfinite(frame.to_numpy()).all() or (frame.to_numpy() < 0).any():
        raise SourceNotReady("Projected feature distances are invalid")
    if not any(frame[key].nunique() > 1 for key in frame):
        raise SourceNotReady("All proximity indicators are constant; entropy information is absent")
    directions = {"rivers": IndicatorDirection(request.proximity_options.river_direction),
                  "services": IndicatorDirection(request.proximity_options.service_direction)}
    weighted = entropy_weights(frame, directions)
    if any(value < 0 for value in weighted.weights.values()) or not np.isclose(sum(weighted.weights.values()), 1):
        raise SourceNotReady("Proximity entropy weights are invalid")
    products = {f"distance_to_{role}": (values, "m") for role, values in raw.items()}
    products["feature_proximity_index"] = (apply_weighted_index(weighted.normalized_data, weighted.weights).to_numpy(), "index_0_1")
    return products, {"method": "projected Euclidean point-to-full-source geometry distance; existing entropy weighting",
                      "policy": request.proximity_options.model_dump(), "directions": {role: direction.value for role, direction in directions.items()},
                      "weights": weighted.weights, "entropy": weighted.entropy,
                      "normalization_ranges_m": {role: {"min": frame[role].min(), "max": frame[role].max()} for role in frame},
                      "limitation": "Comparative proximity index, not inundation, service capacity or an independently calibrated flood-risk score"}


def soil_products(request, source, aoi):
    policy = source.manifest.soil_scoring_policy
    reviewed_policy(source, policy.specification_reference, "scoring_policy_verified")
    raw, mask, alignment = align_raster_source(source, request.target_grid, aoi)
    values = raw[mask]
    if not np.equal(values, np.floor(values)).all() or not set(map(str, np.unique(values.astype(int)))).issubset(policy.classes):
        raise SourceNotReady("Unknown or nonintegral soil texture code; no fallback score is permitted")
    scored = np.full(raw.shape, np.nan)
    for code, item in policy.classes.items():
        scored[mask & (raw == int(code))] = item.score
    return {"soil_texture_class": (raw, "class_code"), "soil_infiltration_score": (scored, policy.score_units)}, {
        "method": "exact lookup of five source-declared reviewed class scores; no inferred permeability or normalization",
        "soil_scoring_policy": policy.model_dump(), "alignment": alignment,
        "class_cell_counts": {code: int(np.count_nonzero(values == int(code))) for code in policy.classes},
        "limitations": ["Policy reference and administrative review do not independently establish specification/scientific validity", "Authoritative five-class mapping and source soil observations must be supplied and reviewed externally"]}


def watershed_products(request, sources, aoi, transform, mask):
    source = sources["terrain"]
    metrics, record = terrain_metrics(source, request.target_grid, aoi, ["twi", "flow_direction", "flow_accumulation"])
    if not sources["outlets"].evidence.get("checks", {}).get("coverage_complete_verified"):
        raise SourceNotReady("Watershed outlets require reviewed coverage completeness")
    with MemoryFile(source.data) as memory, memory.open() as raster:
        dem = raster.read(1)
        flow = compute_flow_direction(dem)
        reverse = {}
        offsets = {code: (dr, dc) for dr, dc, code in _D8_NEIGHBOURS}
        for row, column in np.ndindex(dem.shape):
            if flow[row, column]:
                dr, dc = offsets[flow[row, column]]
                reverse.setdefault((row+dr, column+dc), []).append((row, column))
        features = json.loads(sources["outlets"].data)["features"]
        if len(features) > 100 or len({feature["properties"]["outlet_id"] for feature in features}) != len(features):
            raise SourceNotReady("Outlet identifiers must be unique and bounded to 100")
        projection = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
        products = {name: (values, "dimensionless" if name == "twi" else record["units"][name]) for name, values in metrics.items()}
        native = {}
        outlets = []
        occupied = set()
        for index, feature in enumerate(features):
            if not request.period.start <= stamp(feature["properties"]) <= request.period.end:
                raise SourceNotReady("Watershed outlet observation is outside the analysis period")
            point = shape(feature["geometry"])
            x, y = projection.transform(point.x, point.y)
            row, column = rowcol(raster.transform, x, y)
            if not 0 <= row < raster.height or not 0 <= column < raster.width or (row, column) in occupied:
                raise SourceNotReady("Outlets must occupy distinct valid native DEM cells; no snapping is performed")
            occupied.add((row, column))
            basin = np.zeros(dem.shape, dtype="uint8")
            queue = [(row, column)]
            while queue:
                cell = queue.pop()
                if basin[cell]:
                    continue
                basin[cell] = 1
                queue.extend(reverse.get(cell, []))
            destination = np.full(mask.shape, -9999, dtype="float64")
            reproject(basin, destination, src_transform=raster.transform, src_crs=raster.crs,
                      dst_transform=transform, dst_crs=request.target_grid.crs, dst_nodata=-9999, resampling=Resampling.nearest)
            destination[~mask] = np.nan
            key = f"watershed_{index+1}"
            products[key] = (destination, "binary_upstream_membership_0_1")
            native[key] = (basin, RasterSpec(raster.transform, raster.crs.to_epsg()))
            outlets.append({"product_key": key, "outlet_id": feature["properties"]["outlet_id"],
                            "native_row": int(row), "native_column": int(column), "upstream_cells": int(basin.sum()),
                            "upstream_area_m2": int(basin.sum()) * abs(raster.transform.a * raster.transform.e)})
    record.update(outlets=outlets, delineation="reverse traversal of full reviewed native D8 network; includes outlet cell; nested catchments retained independently",
                  outlet_policy="containing native cell; no nearest-stream snapping", external_limit="Conditioning, outlet location and upstream completeness require independent hydrologic review")
    return products, record, native


def frequency_tables(request, sources, aoi):
    start, end = request.period.start, request.period.end
    if (start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0)
            or start != datetime(start.year, 1, 1, tzinfo=timezone.utc)
            or end != datetime(end.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            or not 10 <= end.year-start.year+1 <= 100):
        raise SourceNotReady("Frequency requires 10–100 complete consecutive UTC calendar years")
    discharge = sources["discharge"]
    if discharge.manifest.observation_interval_hours != 24 or not discharge.evidence.get("checks", {}).get("annual_record_complete_verified"):
        raise SourceNotReady("Discharge frequency requires reviewed complete daily records; subdaily flood peaks are not inferred")
    if (not sources["inventory"].evidence.get("checks", {}).get("coverage_complete_verified")
            or not sources["inventory"].evidence.get("checks", {}).get("annual_record_complete_verified")):
        raise SourceNotReady("Historical inventory requires reviewed temporal/spatial completeness")
    if any(not source.manifest.historical_record_definition for source in sources.values()):
        raise SourceNotReady("Historical discharge/inventory require explicit sourced record/event definitions")
    station_rows = {}
    for row in records(discharge):
        if start <= stamp(row) <= end:
            station_rows.setdefault(row["station_id"], []).append(row)
    if not station_rows or len(station_rows) > 100:
        raise SourceNotReady("Frequency requires a bounded observed discharge station record")
    total_days = (datetime(end.year+1, 1, 1, tzinfo=timezone.utc)-start).days
    annual, frequencies = [], []
    for station, observations in sorted(station_rows.items()):
        observations.sort(key=stamp)
        if len(observations) != total_days or any(stamp(row) != start+timedelta(days=index) for index, row in enumerate(observations)):
            raise SourceNotReady("Daily discharge record has a gap, duplicate or incompatible cadence")
        locations = {(float(row["longitude"]), float(row["latitude"])) for row in observations}
        if len(locations) != 1 or not shape(aoi).covers(Point(*next(iter(locations)))):
            raise SourceNotReady("Discharge station location must be fixed within the AOI")
        maxima = []
        for year in range(start.year, end.year+1):
            maximum = max(float(row["discharge_m3_s"]) for row in observations if stamp(row).year == year)
            maxima.append(maximum)
            longitude, latitude = next(iter(locations))
            annual.append({"station_id": station, "longitude": longitude, "latitude": latitude, "year": year, "annual_maximum_daily_discharge_m3_s": maximum})
        for threshold in sorted(set(maxima)):
            count = sum(value >= threshold for value in maxima)
            probability = count / len(maxima)
            frequencies.append({"station_id": station, "observed_threshold_m3_s": threshold, "annual_exceedance_count": count,
                                "record_length_years": len(maxima), "empirical_aep": probability,
                                "empirical_recurrence_years": probability_to_return_period(probability)})
    features = json.loads(sources["inventory"].data)["features"]
    inventory, ids = [], set()
    per_year = {year: set() for year in range(start.year, end.year+1)}
    for feature in features:
        props = feature["properties"]
        event_start = datetime.fromisoformat(props["start_at"].replace("Z", "+00:00"))
        event_end = datetime.fromisoformat(props["end_at"].replace("Z", "+00:00"))
        if not start <= event_start <= event_end <= end:
            raise SourceNotReady("Inventory event is censored outside the complete frequency interval")
        if not shape(feature["geometry"]).intersects(shape(aoi)):
            continue
        if props["event_id"] in ids:
            raise SourceNotReady("Inventory event IDs are duplicated; consolidate vetted event footprints")
        ids.add(props["event_id"])
        inventory.append(feature)
        for year in range(event_start.year, event_end.year+1):
            per_year[year].add(props["event_id"])
    counts = [{"year": year, "distinct_observed_events": len(events)} for year, events in per_year.items()]
    event_aep = sum(bool(events) for events in per_year.values()) / len(per_year)
    return {"annual_discharge_maxima": annual, "discharge_empirical_frequency": frequencies,
            "inventory_by_year": counts}, {"method": "empirical count of complete years with annual maximum daily discharge >= an observed threshold / N; T=1/AEP",
            "record_definitions": {role: source.manifest.historical_record_definition for role, source in sources.items()},
            "record_length_years": len(per_year), "inventory_annual_probability": event_aep,
            "inventory_empirical_recurrence_years": probability_to_return_period(event_aep) if event_aep else None,
            "limitations": ["No parametric tail fit or extrapolation beyond observed discharge thresholds", "Daily maxima are not instantaneous flood peaks", "Inventory recurrence applies to any vetted AOI event, not per-pixel inundation", "Station discharges and inventory events are not assumed causally matched"]}, inventory


def predictor_tables(request, source, aoi):
    reviewed_policy(source, source.manifest.predictor_catalogue_reference, "predictor_catalogue_verified")
    definitions = source.manifest.predictor_definitions
    options = request.predictor_options
    required = {options.response, *options.predictor_order}
    if set(definitions) != required or definitions[options.response].role != "response" or any(definitions[key].role != "predictor" for key in options.predictor_order):
        raise SourceNotReady("MLR selection must account for every reviewed declared predictor and response")
    samples, identities = {}, {}
    for row in records(source):
        key = row["sample_id"]
        identity = (stamp(row), float(row["longitude"]), float(row["latitude"]))
        if not request.period.start <= identity[0] <= request.period.end or not shape(aoi).covers(Point(identity[1:])):
            raise SourceNotReady("Predictor observation is outside AOI/analysis period")
        if key in identities and identities[key] != identity:
            raise SourceNotReady("Sample predictor timestamps/positions differ; no synthetic joining is allowed")
        identities[key] = identity
        if row["variable"] in samples.setdefault(key, {}):
            raise SourceNotReady("Duplicate sample-variable observation")
        samples[key][row["variable"]] = float(row["value"])
    if not 10 <= len(samples) <= 10_000 or any(set(values) != required for values in samples.values()):
        raise SourceNotReady("MLR requires 10–10,000 complete sourced sample rows; no imputation")
    order = sorted(samples, key=lambda key: (identities[key][0], key))
    frame = pd.DataFrame([samples[key] for key in order], index=order)
    if not np.isfinite(frame.to_numpy()).all() or any(frame[key].nunique() < 2 for key in required):
        raise SourceNotReady("MLR requires finite nonconstant predictors and response")
    split = int(len(frame)*(1-options.holdout_fraction))
    if len(frame)-split < 2 or identities[order[split-1]][0] >= identities[order[split]][0]:
        raise SourceNotReady("Chronological holdout needs disjoint observed times; no split within the same instant")
    train, holdout = frame.iloc[:split], frame.iloc[split:]
    if any(train[key].nunique() < 2 for key in required):
        raise SourceNotReady("Training variables are constant; selection/diagnostics are undefined")
    report = correlation_report(train)
    selected, selection = [], []
    for predictor in options.predictor_order:
        candidate = selected+[predictor]
        design = np.column_stack((np.ones(len(train)), train[candidate].to_numpy()))
        if (len(train) <= len(candidate)+1 or np.linalg.matrix_rank(design) != len(candidate)+1
                or not np.isfinite(design.T @ design).all()
                or np.linalg.matrix_rank(design.T @ design) != len(candidate)+1):
            selection.append({"predictor": predictor, "accepted": False, "reason": "insufficient residual degrees of freedom or numerically rank-deficient OLS normal equations", "vif": None})
            continue
        vifs = {}
        for column in candidate:
            others = [key for key in candidate if key != column]
            r2 = fit_mlr(train[column], train[others]).r_squared if others else 0
            vifs[column] = 1/(1-r2) if r2 < 1 else float("inf")
        accepted = all(value <= options.vif_limit for value in vifs.values())
        selection.append({"predictor": predictor, "accepted": accepted, "reason": "declared order; all candidate VIF within declared bound" if accepted else "candidate design exceeds declared VIF bound", "vif": vifs})
        if accepted:
            selected = candidate
    if not selected:
        raise SourceNotReady("No predictor passes the declared rank/VIF selection policy")
    fitted = fit_mlr(train[options.response], train[selected])
    if (not np.isfinite([coefficient.coefficient for coefficient in fitted.coefficients]).all()
            or not np.isfinite(fitted.fitted_values).all() or not np.isfinite(fitted.residuals).all()):
        raise SourceNotReady("MLR returned nonfinite fitted scientific outputs")
    predictions = fitted.predict(holdout[selected])
    if not np.isfinite(predictions).all():
        raise SourceNotReady("MLR returned nonfinite holdout predictions")
    errors = predictions-holdout[options.response].to_numpy()
    ss_total = np.sum((holdout[options.response]-holdout[options.response].mean())**2)
    metrics = {"rmse": np.sqrt(np.mean(errors**2)), "mae": np.abs(errors).mean(),
               "r_squared": 1-np.sum(errors**2)/ss_total if ss_total else None}
    return {"raw_observations": [{"sample_id": key, "observed_at": identities[key][0].isoformat(), "longitude": identities[key][1], "latitude": identities[key][2], **samples[key]} for key in order],
            "training_fit": [{"sample_id": key, "fitted": fitted.fitted_values[index], "residual": fitted.residuals[index]} for index, key in enumerate(train.index)],
            "coefficients": [{**asdict(coefficient), "units": definitions[options.response].unit if coefficient.variable == "Intercept"
                              else f"{definitions[options.response].unit} / {definitions[coefficient.variable].unit}"} for coefficient in fitted.coefficients],
            "holdout_predictions": [{"sample_id": key, "observed": holdout.loc[key, options.response], "predicted": predictions[index]} for index, key in enumerate(holdout.index)]}, {
                "predictor_definitions": {key: definition.model_dump() for key, definition in definitions.items()},
                "predictor_catalogue_reference": source.manifest.predictor_catalogue_reference,
                "selection": selection, "selected_predictors": selected, "vif_limit": options.vif_limit,
                "training_correlations": {"pairs": [asdict(pair) for pair in report.pairs], "matrix": report.matrix.to_dict()},
                "fit_diagnostics": {"r_squared": fitted.r_squared, "adjusted_r_squared": fitted.adjusted_r_squared, "f_statistic": fitted.f_statistic, "f_p_value": fitted.f_p_value},
                "holdout_metrics": metrics, "holdout_count": len(holdout), "training_count": len(train),
                "selection_basis": "training-only correlation/VIF; deterministic declared predictor order; chronological observed-time holdout",
                "limitations": ["Holdout diagnostics describe only the bound source observations, not independent or operational validation", "Spatial/temporal dependence and extrapolation validity require external review", "Catalogue completeness and variable encodings require source-bound administrator review; unavailable authoritative observations are never fabricated"]}


def compute_bundle4(request, sources, aoi):
    module = request.module
    products, tables, vectors, native = {}, {}, {}, {}
    context = None
    if module not in {"predictor_mlr", "historical_frequency"}:
        context = grid_context(request, aoi)
        transform, mask, queries = context
        if module == "rainfall_interpolation":
            products, processing = rainfall_products(request, sources, queries)
        elif module == "river_stage":
            products, processing = stage_products(request, sources, queries)
        elif module == "feature_proximity":
            products, processing = proximity_products(request, sources, queries)
        elif module == "watershed":
            products, processing, native = watershed_products(request, sources, aoi, transform, mask)
        elif module == "soil_infiltration":
            products, processing = soil_products(request, sources["soil"], aoi)
        else:
            raise SourceNotReady("Unsupported source workflow")
    elif module == "historical_frequency":
        tables, processing, inventory = frequency_tables(request, sources, aoi)
        vectors["historical_inventory"] = {"type": "FeatureCollection", "features": inventory}
    else:
        tables, processing = predictor_tables(request, sources["observations"], aoi)
    for name, (values, units) in products.items():
        selected = values[context[1]] if values.ndim == 2 else values
        # TWI and flat/sink derivative metadata retain their established semantics.
        if not np.isfinite(selected).all():
            raise SourceNotReady(f"Derived {name} does not cover finite AOI cells")
    return products, tables, vectors, native, clean(processing), context


def validate_bundle4(request, sources, aoi):
    try:
        compute_bundle4(request, sources, aoi)
    except SourceNotReady:
        raise
    except (ValueError, np.linalg.LinAlgError, FloatingPointError, OverflowError) as exc:
        raise SourceNotReady("Source observations cannot support the requested numerical workflow") from exc


def execute_bundle4(bindings, aoi_geometry, output_directory, result_version, *, task_id):
    request = bindings.request
    products, tables, vectors, native, processing, context = compute_bundle4(request, bindings.sources, aoi_geometry)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    entries = {}
    period = request.period.model_dump(mode="json")
    metadata = {"target_period": period}
    if context:
        transform, mask, _ = context
        grid = request.target_grid
        metadata.update(crs=grid.crs, nodata=-9999, bounds=[grid.west, grid.south, grid.east, grid.north],
                        width=grid.width, height=grid.height, transform=list(transform)[:6],
                        spatial_resolution={"x": transform.a, "y": -transform.e, "unit": "m"})
        spec = RasterSpec(transform, CRS.from_user_input(grid.crs).to_epsg())
        for key, (values, units) in products.items():
            raster = np.full(mask.shape, -9999, dtype="int32" if key == "soil_texture_class" else "float32")
            raster[mask] = values[mask] if values.ndim == 2 else values
            if not np.isfinite(raster[mask]).all() or (raster[mask] == -9999).any():
                raise SourceNotReady("Scientific raster values are incompatible with the float32/nodata export contract")
            path = output_directory / (key+".cog.tif")
            write_cog(str(path), raster, spec, nodata=-9999)
            gis = {**metadata, "units": units, "product_key": key, "vertical_datum": next((source.manifest.vertical_datum for source in bindings.sources.values() if source.manifest.vertical_datum), None)}
            entries[key] = artifact_entry(path, label=key.replace("_", " "), media_type="image/tiff", artifact_type="raster", role="product", product_key=key, delivery_type="cog", format_name="cog", result_version=result_version, gis_metadata=gis, layer={"layer_type": "raster", "crs": grid.crs, "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north}, "units": units, "nodata": -9999, "renderable": True, "available_delivery_types": ["cog"], "planned_delivery_types": []})
        for key, (array, native_spec) in native.items():
            path = output_directory / (key+"-native.cog.tif")
            write_cog(str(path), array, native_spec, nodata=255)
            entries[key+"_native"] = artifact_entry(path, label=key+" full native catchment", media_type="image/tiff", artifact_type="raster", role="product", product_key=key+"_native", delivery_type="cog", format_name="cog", result_version=result_version,
                gis_metadata={"crs": f"EPSG:{native_spec.crs_epsg}", "units": "binary_upstream_membership_0_1", "nodata": 255, "target_period": period,
                              "width": array.shape[1], "height": array.shape[0], "transform": list(native_spec.transform)[:6],
                              "bounds": list(array_bounds(*array.shape, native_spec.transform)),
                              "spatial_resolution": {"x": native_spec.transform.a, "y": -native_spec.transform.e, "unit": "m"},
                              "spatial_support": "full reviewed native DEM; includes upstream catchment outside AOI"})
    for key, data in tables.items():
        path = output_directory / (key+".csv")
        _spreadsheet_safe(pd.DataFrame(clean(data))).to_csv(path, index=False)
        entries[key] = artifact_entry(path, label=key.replace("_", " "), media_type="text/csv", artifact_type="metadata", role="product", product_key=key, format_name="csv", result_version=result_version,
                                     gis_metadata={"target_period": period, "measurement_definitions": processing.get("predictor_definitions", processing.get("record_definitions", {})), "method": processing.get("method", processing.get("selection_basis"))})
    for key, data in vectors.items():
        path = output_directory / (key+".geojson")
        path.write_text(json.dumps(data, allow_nan=False))
        entries[key] = artifact_entry(path, label=key.replace("_", " "), media_type="application/geo+json", artifact_type="vector", role="product", product_key=key, format_name="geojson", result_version=result_version, gis_metadata={"crs": "EPSG:4326", "units": "event_polygon", "target_period": period})
    summary = {"status": "completed", "module": request.module, "processing": processing,
               "limitations": LIMITATIONS, "products": {key: {"units": units, "min": float(values[context[1]].min()) if values.ndim == 2 else float(values.min()), "max": float(values[context[1]].max()) if values.ndim == 2 else float(values.max()), "mean": float(values[context[1]].mean()) if values.ndim == 2 else float(values.mean())} for key, (values, units) in products.items()}}
    provenance = {"engine_key": "firris", "module": request.module, "source_bindings": bindings.lineage(),
                  "processing": processing, "analysis_readiness_rechecked_at_execution": True,
                  "raw_source_policy": "registered immutable source bytes retained; raw observations/distances/surfaces retained alongside derived indices",
                  "validation_limitations": LIMITATIONS}
    summary = clean(summary)
    exports = build_result_exports(output_directory, task_id=task_id, project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris", engine_version="source-bound-bundle4-v1", result_type="source_bound_"+request.module,
                                  result_version=result_version, summary=summary, provenance=provenance, gis_metadata=metadata, product_entries=entries)
    return EngineExecutionOutput("source_bound_"+request.module, summary, provenance, {**entries, **exports})
