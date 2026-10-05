"""Metadata-driven FIRRIS cartographic PNG/PDF exports.

These are presentation artifacts, not new scientific layers. The underlying
protected raster/vector product, nodata, lineage and uncertainty remain in the
Result and its package.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from pyproj import CRS, Geod, Transformer
from rasterio.warp import transform_bounds
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from shapely.geometry import shape

from app.platform.result_exports import artifact_entry


MAP_KEYS = frozenset({
    "flood_extent", "flood_depth", "flood_velocity", "flood_hazard",
    "flood_hazard_physical", "flood_probability", "flood_aep",
    "flood_return_period", "flood_duration", "flood_exposure",
    "flood_vulnerability", "flood_risk", "flood_susceptibility",
    "flood_hazard_zonation",
})
_GEOD = Geod(ellps="WGS84")
_SIZE = (2200, 1550)
_MAP = (115, 180, 1480, 1235)
_NAVY = "#102A43"
_GREY = "#526477"


def _font(size: int, *, bold: bool = False):
    configured = os.environ.get("NOVA_MAP_FONT_BOLD_PATH" if bold else "NOVA_MAP_FONT_PATH")
    candidates = (
        Path(configured) if configured else None,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        if path is not None and path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _bounds(value) -> tuple[float, float, float, float]:
    if isinstance(value, dict):
        value = [value.get(key) for key in ("west", "south", "east", "north")]
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("Map product requires four real GIS bounds")
    bounds = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in bounds) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("Map product GIS bounds are invalid")
    return bounds


def _legend(value) -> list[dict]:
    if isinstance(value, dict):
        value = value.get("entries")
    if not isinstance(value, list) or not value:
        raise ValueError("Map product lacks a product-specific legend")
    out = []
    for item in value:
        if not isinstance(item, dict) or not item.get("label"):
            raise ValueError("Map product legend is malformed")
        color = item.get("color") or item.get("color_hex")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise ValueError("Map product legend color is invalid")
        out.append({"label": str(item["label"]), "color": color,
                    "min": item.get("min"), "max": item.get("max")})
    return out


def _source(output_directory: Path, entry: dict) -> Path:
    name = entry.get("path")
    if not isinstance(name, str):
        raise ValueError("Map source artifact path is missing")
    root = output_directory.resolve()
    path = (root / name).resolve(strict=True)
    path.relative_to(root)
    if not path.is_file():
        raise ValueError("Map source artifact is unavailable")
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    digest = checksum.hexdigest()
    if digest != entry.get("checksum_sha256"):
        raise ValueError("Map source artifact checksum changed before export")
    return path


def _class_codes(values: np.ndarray, bands: list[dict], key: str) -> np.ndarray:
    if key == "flood_hazard_zonation":
        codes = values.astype("int16")
        if not np.all(values == codes) or not np.isin(codes, range(1, len(bands) + 1)).all():
            raise ValueError("Zonation class codes do not match the recorded legend")
        return codes
    if len(bands) == 2 and key == "flood_extent":
        if not np.isin(values, [0, 1]).all():
            raise ValueError("Flood Extent must have binary classes")
        return values.astype("int16") + 1
    maxima = []
    for band in bands[:-1]:
        upper = band["max"]
        if upper is None:
            # Legacy RF legend encodes numerical breaks in its label.
            numbers = re.findall(r"\d+(?:\.\d+)?", band["label"])
            if len(numbers) < 2:
                raise ValueError("Legend has no numeric class breaks")
            upper = float(numbers[-1])
        maxima.append(float(upper))
    if maxima != sorted(maxima):
        raise ValueError("Map legend breaks are not ordered")
    return np.searchsorted(maxima, values, side="left").astype("int16") + 1


def _paint_raster(path: Path, meta: dict, bands: list[dict], key: str, size: tuple[int, int]):
    with rasterio.open(path) as raster:
        if raster.count != 1 or raster.crs is None:
            raise ValueError("Cartographic source must be a one-band georeferenced raster")
        bounds = (raster.bounds.left, raster.bounds.bottom, raster.bounds.right, raster.bounds.top)
        declared = meta.get("bounds") or meta.get("bounding_box")
        if declared is not None and not np.allclose(bounds, _bounds(declared), rtol=0, atol=1e-4):
            raise ValueError("Artifact and declared GIS bounds differ")
        if meta.get("crs") and CRS.from_user_input(meta["crs"]) != raster.crs:
            raise ValueError("Artifact and declared CRS differ")
        if meta.get("nodata") != raster.nodata:
            raise ValueError("Artifact and declared nodata differ")
        source = raster.read(1, masked=True)
        valid = ~np.ma.getmaskarray(source)
        observed = np.asarray(source.data, dtype=float)
        if not valid.any() or not np.isfinite(observed[valid]).all():
            raise ValueError("Map raster has no finite observed pixels")
        codes = np.zeros(observed.shape, dtype="int16")
        codes[valid] = _class_codes(observed[valid], bands, key)
        rgba = np.zeros((raster.height, raster.width, 4), dtype="uint8")
        for index, band in enumerate(bands, 1):
            color = tuple(bytes.fromhex(band["color"][1:])) + (255,)
            rgba[valid & (codes == index)] = color
        image = Image.fromarray(rgba, "RGBA").resize(size, Image.Resampling.NEAREST)
        return image, CRS.from_user_input(raster.crs), bounds


def _paint_vector(path: Path, meta: dict, bands: list[dict], key: str, size: tuple[int, int]):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("type") != "FeatureCollection" or not raw.get("features"):
        raise ValueError("Cartographic GeoJSON must contain features")
    crs = CRS.from_user_input(meta.get("crs", "EPSG:4326"))
    if crs != CRS.from_epsg(4326):
        raise ValueError("GeoJSON cartography requires explicit WGS84 coordinates")
    geometries = [shape(feature["geometry"]) for feature in raw["features"]]
    bounds = _bounds(meta.get("bounds") or meta.get("bounding_box"))
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    field = {"flood_vulnerability": "fvi_index"}.get(key, "value")
    for feature, geometry in zip(raw["features"], geometries):
        score = feature.get("properties", {}).get(field)
        if score is None:
            raise ValueError("Vector map is missing the reviewed spatial-unit score")
        code = int(_class_codes(np.asarray([float(score)]), bands, key)[0])
        color = bands[code - 1]["color"]
        polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
        for polygon in polygons:
            if polygon.geom_type != "Polygon":
                raise ValueError("Vector map requires polygon spatial units")
            points = [((x - bounds[0]) / (bounds[2] - bounds[0]) * size[0],
                       (bounds[3] - y) / (bounds[3] - bounds[1]) * size[1])
                      for x, y in polygon.exterior.coords]
            draw.polygon(points, fill=color, outline=_NAVY, width=2)
            for ring in polygon.interiors:
                hole = [((x - bounds[0]) / (bounds[2] - bounds[0]) * size[0],
                         (bounds[3] - y) / (bounds[3] - bounds[1]) * size[1])
                        for x, y in ring.coords]
                draw.polygon(hole, fill=(0, 0, 0, 0))
    return image, crs, bounds


def _pixel(x: float, y: float, bounds, frame=_MAP):
    return (frame[0] + (x - bounds[0]) / (bounds[2] - bounds[0]) * (frame[2] - frame[0]),
            frame[1] + (bounds[3] - y) / (bounds[3] - bounds[1]) * (frame[3] - frame[1]))


def _nice_step(span: float) -> float:
    value = span / 5
    magnitude = 10 ** math.floor(math.log10(max(value, 1e-9)))
    return next(scale * magnitude for scale in (1, 2, 5, 10) if scale * magnitude >= value)


def _graticule(draw: ImageDraw.ImageDraw, crs: CRS, bounds):
    west, south, east, north = transform_bounds(crs, "EPSG:4326", *bounds, densify_pts=21)
    to_map = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    font = _font(19)
    for axis, low, high in (("lon", west, east), ("lat", south, north)):
        step = _nice_step(high - low)
        value = math.ceil(low / step) * step
        while value <= high:
            points = []
            for other in np.linspace(south if axis == "lon" else west,
                                     north if axis == "lon" else east, 65):
                x, y = to_map.transform(value, other) if axis == "lon" else to_map.transform(other, value)
                if math.isfinite(x) and math.isfinite(y):
                    px, py = _pixel(x, y, bounds)
                    if _MAP[0] <= px <= _MAP[2] and _MAP[1] <= py <= _MAP[3]:
                        points.append((px, py))
            if len(points) > 1:
                draw.line(points, fill=(26, 73, 114, 75), width=2)
                anchor = points[-1] if axis == "lon" else points[0]
                label = f"{value:.3g}°" + ("E" if axis == "lon" and value >= 0 else
                                          "W" if axis == "lon" else
                                          "N" if value >= 0 else "S")
                draw.text((min(max(anchor[0], _MAP[0] + 4), _MAP[2] - 95),
                           min(max(anchor[1], _MAP[1] + 4), _MAP[3] - 25)),
                          label, font=font, fill=_NAVY)
            value += step
    return (west, south, east, north)


def _north_and_scale(draw: ImageDraw.ImageDraw, crs: CRS, bounds):
    midx, midy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    to_geo = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    from_geo = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    lon, lat = to_geo.transform(midx, midy)
    north_x, north_y = from_geo.transform(lon, min(89.9, lat + 0.01))
    dx, dy = north_x - midx, north_y - midy
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("True north cannot be derived from the artifact CRS")
    ux, uy = dx / length, -dy / length
    base = (_MAP[2] - 95, _MAP[1] + 130)
    tip = (base[0] + ux * 85, base[1] + uy * 85)
    draw.line([base, tip], fill=_NAVY, width=8)
    draw.polygon([tip, (tip[0] - uy * 14 - ux * 25, tip[1] + ux * 14 - uy * 25),
                  (tip[0] + uy * 14 - ux * 25, tip[1] - ux * 14 - uy * 25)], fill=_NAVY)
    draw.text((tip[0] - 14, tip[1] - 42), "N", font=_font(36, bold=True), fill=_NAVY)
    # Geodesic distance at the scale-bar latitude, valid for projected and
    # geographic CRSs; local scale is deliberately labelled approximate.
    y = bounds[1] + 0.08 * (bounds[3] - bounds[1])
    x0, x1 = bounds[0] + 0.08 * (bounds[2] - bounds[0]), bounds[0] + 0.34 * (bounds[2] - bounds[0])
    lon0, lat0 = to_geo.transform(x0, y)
    lon1, lat1 = to_geo.transform(x1, y)
    distance = _GEOD.inv(lon0, lat0, lon1, lat1)[2]
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("Map scale cannot be derived from CRS/geodesy")
    step = 10 ** math.floor(math.log10(distance))
    nice = max(candidate for candidate in (step, 2 * step, 5 * step, 10 * step) if candidate <= distance)
    px = (x1 - x0) / (bounds[2] - bounds[0]) * (_MAP[2] - _MAP[0]) * nice / distance
    x, py = _pixel(x0, y, bounds)
    draw.rectangle((x, py - 16, x + px / 2, py), fill=_NAVY)
    draw.rectangle((x + px / 2, py - 16, x + px, py), fill="white", outline=_NAVY, width=2)
    draw.line((x, py - 17, x + px, py - 17), fill=_NAVY, width=2)
    label = f"0                 {nice / 1000:g} km" if nice >= 1000 else f"0                 {nice:g} m"
    draw.text((x, py + 6), label + "  (approx. at bar latitude)", font=_font(18), fill=_NAVY)
    return {"distance_m": nice, "bar_width_px": px, "method": "WGS84 geodesic at scale-bar latitude"}


def _locator(draw: ImageDraw.ImageDraw, aoi_bounds):
    box = (1580, 955, 2070, 1200)
    draw.rounded_rectangle(box, radius=12, fill="white", outline="#8AA3B8", width=2)
    draw.text((1600, 970), "GLOBAL LOCATION", font=_font(23, bold=True), fill=_NAVY)
    globe = (1605, 1010, 2045, 1165)
    draw.rectangle(globe, fill="#EAF3F8", outline=_GREY, width=2)
    for longitude in (-120, -60, 0, 60, 120):
        x = globe[0] + (longitude + 180) / 360 * (globe[2] - globe[0])
        draw.line((x, globe[1], x, globe[3]), fill="#B9CFDC", width=1)
    for latitude in (-60, -30, 0, 30, 60):
        y = globe[1] + (90 - latitude) / 180 * (globe[3] - globe[1])
        draw.line((globe[0], y, globe[2], y), fill="#B9CFDC", width=1)
    lon, lat = (aoi_bounds[0] + aoi_bounds[2]) / 2, (aoi_bounds[1] + aoi_bounds[3]) / 2
    x = globe[0] + (lon + 180) / 360 * (globe[2] - globe[0])
    y = globe[1] + (90 - lat) / 180 * (globe[3] - globe[1])
    draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="#D00000", outline="white", width=2)
    draw.text((1605, 1175), f"AOI center {lat:.3f}°, {lon:.3f}° - schematic locator",
              font=_font(17), fill=_GREY)


def _wrapped(draw, text: str, x: int, y: int, width: int, font, *, fill=_NAVY, line_height=31):
    words = text.split()
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_height
            line = word
    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _render(output_directory: Path, key: str, entry: dict, provenance: dict, version: int):
    source = _source(output_directory, entry)
    meta = entry.get("gis_metadata") or {}
    bands = _legend(meta.get("legend") or (entry.get("layer") or {}).get("legend"))
    map_size = (_MAP[2] - _MAP[0], _MAP[3] - _MAP[1])
    if entry.get("artifact_type") == "raster":
        layer, crs, bounds = _paint_raster(source, meta, bands, key, map_size)
    elif entry.get("artifact_type") == "vector":
        layer, crs, bounds = _paint_vector(source, meta, bands, key, map_size)
    else:
        raise ValueError("Map source must be a raster or polygon layer")
    sheet = Image.new("RGB", _SIZE, "#F5F8FB")
    draw = ImageDraw.Draw(sheet, "RGBA")
    draw.rectangle((0, 0, _SIZE[0], 135), fill=_NAVY)
    title = key.replace("_", " ").title()
    draw.text((100, 42), title, font=_font(49, bold=True), fill="white")
    draw.text((1500, 65), f"FIRRIS  •  Result version {version}", font=_font(26), fill="white")
    draw.rectangle(_MAP, fill="white", outline=_NAVY, width=5)
    sheet.paste(layer, (_MAP[0], _MAP[1]), layer)
    draw = ImageDraw.Draw(sheet, "RGBA")
    geographic = _graticule(draw, crs, bounds)
    scale_info = _north_and_scale(draw, crs, bounds)
    draw.rectangle(_MAP, outline=_NAVY, width=5)  # neatline
    draw.rounded_rectangle((1540, 180, 2110, 920), radius=16, fill="white", outline="#A9BDCE", width=2)
    draw.text((1580, 215), "LEGEND", font=_font(30, bold=True), fill=_NAVY)
    y = 270
    for band in bands:
        draw.rectangle((1585, y, 1635, y + 36), fill=band["color"], outline=_NAVY, width=1)
        y = _wrapped(draw, band["label"], 1655, y + 2, 400, _font(23), line_height=29) + 16
    period = meta.get("target_period") or meta.get("analysis_period")
    if isinstance(period, dict):
        period_label = f"{period.get('start', 'unknown')} to {period.get('end', 'unknown')}"
    else:
        period_label = "not supplied"
    horizontal_datum = crs.datum.name
    vertical_datum = meta.get("vertical_datum") or meta.get("source_dem_vertical_datum")
    if vertical_datum is None and meta.get("datum") not in (None, horizontal_datum):
        vertical_datum = meta["datum"]
    operation = crs.coordinate_operation
    if operation is None:
        projection = "Geographic (unprojected)"
    else:
        projection = operation.name
        if not projection or projection.lower() == "unnamed":
            projection = operation.method_name or crs.name
    details = [
        f"Units: {meta.get('units') or (entry.get('layer') or {}).get('units') or 'not supplied'}",
        f"CRS: {crs.to_string()}",
        f"Horizontal datum: {horizontal_datum}",
        f"Vertical datum: {vertical_datum or 'not applicable / not supplied'}",
        f"Projection: {projection}",
        f"Nodata: {meta.get('nodata', 'not applicable')}",
        f"Period: {period_label}",
        f"Acquisition: {meta.get('acquisition_date') or 'not supplied'}",
        f"Producer: {meta.get('producer') or provenance.get('producer') or 'not supplied'}",
    ]
    y = max(y + 25, 590)
    for line in details:
        y = _wrapped(draw, line, 1580, y, 495, _font(18), line_height=24) + 4
    aoi_bounds = _bounds(meta.get("aoi_bounds_wgs84") or geographic)
    _locator(draw, aoi_bounds)
    draw.line((100, 1300, 2100, 1300), fill="#A9BDCE", width=3)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    digest = hashlib.sha256(json.dumps(provenance, sort_keys=True, default=str).encode()).hexdigest()
    notes = [
        f"Created: {created}   |   AOI WGS84: {aoi_bounds[0]:.4f}, {aoi_bounds[1]:.4f}, {aoi_bounds[2]:.4f}, {aoi_bounds[3]:.4f}",
        f"Source artifact SHA-256: {entry['checksum_sha256']}   |   Provenance SHA-256: {digest}",
        "Source QA, uncertainty, units, nodata and full lineage are preserved in the protected Result package.",
    ]
    method = meta.get("zone_break_policy") or meta.get("methodology") or ""
    if method:
        notes.append(f"Method: {method}")
    for line_no, line in enumerate(notes):
        _wrapped(draw, line, 105, 1320 + line_no * 47, 1990, _font(21), line_height=27)
    png = output_directory / f"{key}-cartographic-map.png"
    pdf = output_directory / f"{key}-cartographic-map.pdf"
    png_meta = PngImagePlugin.PngInfo()
    layout = {"title": title, "neatline": True, "north_arrow": "true north from CRS",
              "scale_bar": scale_info, "graticule": True, "locator": "global WGS84 graticule with AOI center",
              "labelled_coordinates": True, "created_at": created, "projection": projection,
              "horizontal_datum": horizontal_datum, "vertical_datum": vertical_datum,
              "source_artifact_sha256": entry["checksum_sha256"], "provenance_sha256": digest}
    png_meta.add_text("NOVA_GIS_METADATA", json.dumps({"source": meta, "cartography": layout},
                                                     sort_keys=True, default=str))
    sheet.save(png, pnginfo=png_meta, optimize=True)
    pdf_canvas = canvas.Canvas(str(pdf), pagesize=(1100, 775))
    pdf_canvas.drawImage(ImageReader(sheet), 0, 0, width=1100, height=775)
    pdf_canvas.setTitle(title)
    pdf_canvas.setAuthor(str(meta.get("producer") or provenance.get("producer") or "NOVA GeoRisk"))
    pdf_canvas.setSubject(f"Protected FIRRIS cartographic export; source SHA-256 {entry['checksum_sha256']}")
    pdf_canvas.showPage()
    pdf_canvas.save()
    carto_meta = {**meta, "cartography": layout}
    return {
        f"{key}_map_png": artifact_entry(png, label=f"{title} cartographic map PNG",
            media_type="image/png", artifact_type="report", result_version=version,
            role="export", product_key=key, delivery_type="map_png", format_name="png",
            gis_metadata=carto_meta),
        f"{key}_map_pdf": artifact_entry(pdf, label=f"{title} cartographic map PDF",
            media_type="application/pdf", artifact_type="report", result_version=version,
            role="export", product_key=key, delivery_type="map_pdf", format_name="pdf",
            gis_metadata=carto_meta),
    }


def build_cartographic_exports(output_directory: Path, *, product_entries: dict[str, dict],
                               provenance: dict, result_version: int) -> dict[str, dict]:
    """Render at most one final map per supported product key."""
    grouped: dict[str, list[tuple[str, dict]]] = {}
    for name, entry in product_entries.items():
        key = entry.get("product_key")
        if (entry.get("role") == "product" and key in MAP_KEYS
                and entry.get("artifact_type") in {"raster", "vector"}
                and (entry.get("layer") or {}).get("renderable") is True):
            grouped.setdefault(key, []).append((name, entry))
    maps: dict[str, dict] = {}
    for key, candidates in grouped.items():
        candidates.sort(key=lambda pair: (pair[0] != key, pair[1].get("format") != "cog",
                                          pair[1].get("artifact_type") != "raster"))
        maps.update(_render(output_directory, key, candidates[0][1], provenance, result_version))
    return maps
