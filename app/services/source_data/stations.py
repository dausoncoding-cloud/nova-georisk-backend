"""Shared reviewed rainfall series support; used by Hazard and geostatistical products."""
import csv
import io
from datetime import datetime
import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint, Point
from app.services.source_data.readiness import SourceNotReady


def rainfall_samples(source, request, x, y):
    interval = source.manifest.observation_interval_hours
    if interval is None or source.manifest.units != "mm":
        raise SourceNotReady("Rainfall observations need approved millimetres and a positive observation interval")
    records: dict[str, list[tuple[datetime, float]]] = {}
    locations: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(source.data.decode("utf-8-sig"))):
        stamp = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if not request.period.start <= stamp <= request.period.end:
            continue
        station = row["station_id"]
        coordinate = (float(row["longitude"]), float(row["latitude"]))
        if station in locations and locations[station] != coordinate:
            raise SourceNotReady("Rainfall station coordinates change within the analysis period")
        locations[station] = coordinate
        records.setdefault(station, []).append((stamp, float(row["rainfall_mm"])))
    if not 3 <= len(records) <= 100:
        raise SourceNotReady("Rainfall IDW cross-validation requires at least three observed stations")
    timestamps = None
    for observations in records.values():
        observed = sorted(stamp for stamp, _ in observations)
        if timestamps is not None and observed != timestamps:
            raise SourceNotReady("Rainfall stations do not share a complete observation schedule")
        timestamps = observed
    if timestamps[0] != request.period.start:
        raise SourceNotReady("Rainfall observations do not begin at the requested period")
    if len(timestamps) > 1 and any(abs((b - a).total_seconds() / 3600 - interval) > 1e-6 for a, b in zip(timestamps, timestamps[1:])):
        raise SourceNotReady("Rainfall cadence disagrees with the approved observation interval")
    if (request.period.end - timestamps[-1]).total_seconds() / 3600 > interval:
        raise SourceNotReady("Rainfall observations do not cover the requested period")
    transformer = Transformer.from_crs("EPSG:4326", request.target_grid.crs, always_xy=True)
    stations = sorted(records)
    coordinates = np.array([transformer.transform(*locations[station]) for station in stations], dtype=float)
    if not np.isfinite(coordinates).all():
        raise SourceNotReady("Rainfall station projection is nonfinite")
    if len(np.unique(coordinates, axis=0)) != len(coordinates) or np.linalg.matrix_rank(coordinates - coordinates.mean(axis=0)) < 2:
        raise SourceNotReady("Rainfall stations must not be collinear or co-located")
    station_hull = MultiPoint([tuple(point) for point in coordinates]).convex_hull
    if any(not station_hull.covers(Point(float(cx), float(cy))) for cx, cy in zip(x, y)):
        raise SourceNotReady("Rainfall IDW would extrapolate beyond the approved station network")
    intensities = np.array([np.mean([mm / interval for _, mm in records[station]]) for station in stations], dtype=float)
    if not np.isfinite(intensities).all() or (intensities < 0).any():
        raise SourceNotReady("Observed rainfall intensity is invalid")
    return coordinates, intensities, {"station_count": len(stations), "station_ids": stations,
        "observation_count_per_station": len(timestamps), "observation_interval_hours": interval,
        "station_locations_wgs84": locations,
        "period_aggregation": "arithmetic mean of observed rainfall_mm / declared interval_hours on shared complete schedule",
        "spatial_support": "projected metre coordinates; AOI cell centres within station convex hull"}
