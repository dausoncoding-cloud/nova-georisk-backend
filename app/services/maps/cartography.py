"""Metadata-driven FIRRIS map exports: simple framed maps (client decision D5) and GIS-ready layers.

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
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from pyproj import CRS
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
_NAVY = "#102A43"


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


_DPI = 300
_MAP_MAX = (1800, 1500)
_MARGIN_LEFT, _MARGIN_TOP, _MARGIN_BOTTOM, _GAP, _PANEL = 230, 60, 120, 70, 560
_RANGE_LABEL = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*[–-]\s*-?\d+(?:\.\d+)?\s*$")
_CLASS_VALUE_KEYS = {"flood_extent"}


def _nice_step(span: float) -> float:
    value = span / 5
    magnitude = 10 ** math.floor(math.log10(max(value, 1e-9)))
    return next(scale * magnitude for scale in (1, 2, 5, 10) if scale * magnitude >= value)


def _is_continuous(bands: list[dict]) -> bool:
    return len(bands) > 1 and all(_RANGE_LABEL.match(band["label"]) for band in bands)


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(bytes.fromhex(color[1:]))


def _ramp(t: np.ndarray, stops: list[str]) -> np.ndarray:
    """Linear interpolation of colour stops over t in [0, 1]."""
    colors = np.asarray([_rgb(stop) for stop in stops], dtype=float)
    position = np.clip(t, 0, 1) * (len(colors) - 1)
    low = np.floor(position).astype(int)
    high = np.minimum(low + 1, len(colors) - 1)
    weight = (position - low)[..., None]
    return (colors[low] * (1 - weight) + colors[high] * weight).round().astype("uint8")


def _read_raster(path: Path, meta: dict):
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
        return observed, valid, CRS.from_user_input(raster.crs), bounds, raster.transform


def _map_only_rgba(observed, valid, bands, key, continuous):
    """Native-resolution RGBA of the layer only: no frame, text or legend; no data is transparent."""
    rgba = np.zeros(observed.shape + (4,), dtype="uint8")
    if continuous:
        low, high = float(observed[valid].min()), float(observed[valid].max())
        t = (observed - low) / (high - low) if high > low else np.zeros_like(observed)
        rgba[..., :3] = _ramp(t, [band["color"] for band in bands])
        rgba[..., 3] = np.where(valid, 255, 0)
        return rgba, (low, high)
    codes = np.zeros(observed.shape, dtype="int16")
    codes[valid] = _class_codes(observed[valid], bands, key)
    for index, band in enumerate(bands, 1):
        rgba[valid & (codes == index)] = _rgb(band["color"]) + (255,)
    return rgba, None


def _fit(width: float, height: float) -> tuple[int, int]:
    scale = min(_MAP_MAX[0] / width, _MAP_MAX[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _coordinate_labels(crs: CRS, bounds, box) -> list[dict]:
    x0, y0, x1, y1 = box
    west, south, east, north = bounds
    labels = []
    for axis, low, high in (("x", west, east), ("y", south, north)):
        step = _nice_step(high - low)
        decimals = max(0, -math.floor(math.log10(step)))
        value = math.ceil(low / step) * step
        while value <= high + 1e-12:
            if crs.is_geographic:
                hemisphere = ("E" if value >= 0 else "W") if axis == "x" else ("N" if value >= 0 else "S")
                text = f"{abs(value):.{decimals}f}°{hemisphere}"
            else:
                text = f"{value:,.{decimals}f} m {'E' if axis == 'x' else 'N'}"
            position = (x0 + (value - west) / (east - west) * (x1 - x0)) if axis == "x" else (y0 + (north - value) / (north - south) * (y1 - y0))
            labels.append({"axis": axis, "value": round(value, 10), "text": text, "position_px": position})
            value += step
    return labels


def _scale(bands, continuous, value_range, units, has_nodata) -> dict:
    if continuous:
        low, high = value_range
        return {"kind": "gradient", "min": low, "max": high, "unit": units, "stops": [band["color"] for band in bands],
                "labels": [f"{high:.2f}", f"{low:.2f}", units]}
    classes = [{"label": band["label"], "color": band["color"]} for band in bands]
    if has_nodata:
        classes.append({"label": "No data", "color": "#FFFFFF"})
    return {"kind": "class_key", "classes": classes}


def _draw_png(map_rgba: Image.Image, box, sheet_size, labels, scale) -> Image.Image:
    sheet = Image.new("RGB", sheet_size, "white")
    sheet.paste(map_rgba, (box[0], box[1]), map_rgba)
    draw = ImageDraw.Draw(sheet)
    draw.rectangle(box, outline="black", width=3)
    font = _font(34)
    for label in labels:
        if label["axis"] == "x":
            x = label["position_px"]
            draw.line((x, box[3], x, box[3] + 18), fill="black", width=3)
            draw.text((x, box[3] + 24), label["text"], font=font, fill="black", anchor="ma")
        else:
            y = label["position_px"]
            draw.line((box[0] - 18, y, box[0], y), fill="black", width=3)
            draw.text((box[0] - 24, y), label["text"], font=font, fill="black", anchor="rm")
    panel_x = box[2] + _GAP
    if scale["kind"] == "gradient":
        height = min(box[3] - box[1], 900)
        ramp = _ramp(np.linspace(1, 0, height), scale["stops"])
        sheet.paste(Image.fromarray(np.repeat(ramp[:, None, :], 70, axis=1), "RGB"), (panel_x, box[1]))
        draw.rectangle((panel_x, box[1], panel_x + 70, box[1] + height), outline="black", width=2)
        draw.text((panel_x + 90, box[1]), scale["labels"][0], font=font, fill="black", anchor="lm")
        draw.text((panel_x + 90, box[1] + height), scale["labels"][1], font=font, fill="black", anchor="lm")
        draw.text((panel_x, box[1] + height + 30), scale["labels"][2], font=font, fill="black")
    else:
        for index, item in enumerate(scale["classes"]):
            y = box[1] + index * 70
            draw.rectangle((panel_x, y, panel_x + 60, y + 44), fill=item["color"], outline="black", width=2)
            draw.text((panel_x + 80, y + 22), item["label"], font=font, fill="black", anchor="lm")
    return sheet


def _draw_pdf(path: Path, map_rgba: Image.Image, box, sheet_size, labels, scale, title: str):
    pt = 72 / _DPI
    width, height = sheet_size
    flip = lambda y: (height - y) * pt  # noqa: E731
    pdf = canvas.Canvas(str(path), pagesize=(width * pt, height * pt))
    pdf.setTitle(title)
    background = Image.new("RGB", map_rgba.size, "white")
    background.paste(map_rgba, (0, 0), map_rgba)
    pdf.drawImage(ImageReader(background), box[0] * pt, flip(box[3]), width=(box[2] - box[0]) * pt, height=(box[3] - box[1]) * pt)
    pdf.setLineWidth(0.8)
    pdf.rect(box[0] * pt, flip(box[3]), (box[2] - box[0]) * pt, (box[3] - box[1]) * pt)
    pdf.setFont("Helvetica", 8)
    for label in labels:
        if label["axis"] == "x":
            x = label["position_px"] * pt
            pdf.line(x, flip(box[3]), x, flip(box[3] + 18))
            pdf.drawCentredString(x, flip(box[3] + 50), label["text"])
        else:
            y = flip(label["position_px"])
            pdf.line((box[0] - 18) * pt, y, box[0] * pt, y)
            pdf.drawRightString((box[0] - 24) * pt, y - 3, label["text"])
    panel_x = (box[2] + _GAP) * pt
    if scale["kind"] == "gradient":
        bar = min(box[3] - box[1], 900)
        steps = 100
        colors = _ramp(np.linspace(1, 0, steps), scale["stops"])
        for index, color in enumerate(colors):
            pdf.setFillColorRGB(*(channel / 255 for channel in color))
            pdf.rect(panel_x, flip(box[1] + (index + 1) * bar / steps), 70 * pt, bar / steps * pt + 0.2, stroke=0, fill=1)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.rect(panel_x, flip(box[1] + bar), 70 * pt, bar * pt, stroke=1, fill=0)
        pdf.drawString(panel_x + 90 * pt, flip(box[1]) - 3, scale["labels"][0])
        pdf.drawString(panel_x + 90 * pt, flip(box[1] + bar) - 3, scale["labels"][1])
        pdf.drawString(panel_x, flip(box[1] + bar + 60), scale["labels"][2])
    else:
        for index, item in enumerate(scale["classes"]):
            y = box[1] + index * 70
            pdf.setFillColorRGB(*(channel / 255 for channel in _rgb(item["color"])))
            pdf.rect(panel_x, flip(y + 44), 60 * pt, 44 * pt, stroke=1, fill=1)
            pdf.setFillColorRGB(0, 0, 0)
            pdf.drawString(panel_x + 80 * pt, flip(y + 30), item["label"])
    pdf.showPage()
    pdf.save()


def _qml(bands, continuous, value_range, class_values) -> str:
    from xml.sax.saxutils import quoteattr
    if class_values is not None:
        entries = "".join(f'<paletteEntry value="{value}" color="{band["color"].lower()}" alpha="255" label={quoteattr(band["label"])}/>'
                          for value, band in zip(class_values, bands))
        renderer = f'<rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1"><colorPalette>{entries}</colorPalette></rasterrenderer>'
    else:
        low, high = value_range if value_range else (0.0, 1.0)
        mode = "INTERPOLATED" if continuous else "DISCRETE"
        values = np.linspace(low, high, len(bands)) if continuous else [band["max"] if band["max"] is not None else high for band in bands]
        items = "".join(f'<item value="{float(value)!r}" color="{band["color"].lower()}" alpha="255" label={quoteattr(band["label"])}/>'
                        for value, band in zip(values, bands))
        renderer = (f'<rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="{low!r}" classificationMax="{high!r}">'
                    f'<rastershader><colorrampshader colorRampType="{mode}" clip="0">{items}</colorrampshader></rastershader></rasterrenderer>')
    return f'<qgis version="3.28" styleCategories="Symbology"><pipe>{renderer}</pipe></qgis>\n'


def _clr(bands, continuous, value_range, class_values) -> str:
    if class_values is not None:
        pairs = zip(class_values, bands)
    else:
        low, high = value_range if value_range else (0.0, 1.0)
        pairs = zip(np.linspace(low, high, len(bands)), bands)
    return "\n".join(f"{value:g} {' '.join(str(channel) for channel in _rgb(band['color']))}" for value, band in pairs) + "\n"


def _readme(key: str, title: str, meta: dict, provenance: dict, continuous: bool, crs: CRS) -> str:
    from app.services.reporting.data_sources import credit, datasets_with_companions
    lines = [f"{title} ({key})", "",
             f"{key}.png  map-only image at the delivered raster grid; no data is transparent.",
             f"{key}.pgw / {key}.prj  world file and projection, so the PNG opens georeferenced in GIS software.",
             f"{key}.qml (QGIS) / {key}.clr (ArcGIS)  colour styles for the delivered GeoTIFF/COG of this product.", "",
             f"CRS: {crs.to_string()}", f"Units: {meta.get('units', 'not recorded')}",
             f"Representation: {'continuous values' if continuous else 'classes'}"]
    for name, label in (("target_period", "Target period"), ("baseline_period", "Baseline period")):
        period = provenance.get(name) or {}
        if period.get("start") and period.get("end"):
            lines.append(f"{label}: {period['start']} to {period['end']} (end-exclusive)")
    lines += ["", "Credits:"] + [f"- {credit(dataset)}" for dataset in dict.fromkeys(datasets_with_companions(provenance))]
    return "\n".join(lines) + "\n"


def _render(output_directory: Path, key: str, entry: dict, provenance: dict, version: int):
    source = _source(output_directory, entry)
    meta = entry.get("gis_metadata") or {}
    bands = _legend(meta.get("legend") or (entry.get("layer") or {}).get("legend"))
    title = str(meta.get("display_label") or key.replace("_", " ").title())
    continuous = _is_continuous(bands)
    entries: dict[str, dict] = {}
    if entry.get("artifact_type") == "raster":
        observed, valid, crs, bounds, transform = _read_raster(source, meta)
        rgba, value_range = _map_only_rgba(observed, valid, bands, key, continuous)
        native = Image.fromarray(rgba, "RGBA")
        map_size = _fit(*native.size)
        has_nodata = True
    else:
        continuous = False
        value_range = None
        probe, crs, bounds = _paint_vector(source, meta, bands, key, (100, 100))
        map_size = _fit(bounds[2] - bounds[0], bounds[3] - bounds[1])
        native = None
        has_nodata = False
    if entry.get("artifact_type") == "raster":
        map_image = native.resize(map_size, Image.Resampling.NEAREST)
    else:
        map_image, _, _ = _paint_vector(source, meta, bands, key, map_size)
    box = (_MARGIN_LEFT, _MARGIN_TOP, _MARGIN_LEFT + map_size[0], _MARGIN_TOP + map_size[1])
    scale = _scale(bands, continuous, value_range, str(meta.get("units", "")), has_nodata)
    panel_height = 960 if scale["kind"] == "gradient" else 70 * len(scale["classes"])
    sheet_size = (box[2] + _GAP + _PANEL, max(box[3], box[1] + panel_height) + _MARGIN_BOTTOM)
    labels = _coordinate_labels(crs, bounds, box)
    created = datetime.now(timezone.utc).isoformat()
    layout = {"style": "simple framed map (client decision D5)", "title": title,
              "elements": ["map", "neatline", "coordinate_labels", "colour_scale"],
              "map_box_px": list(box), "sheet_px": list(sheet_size), "dpi": _DPI, "crs": crs.to_string(), "bounds": list(bounds),
              "coordinate_labels": [{k: v for k, v in label.items() if k != "position_px"} for label in labels],
              "colour_scale": scale, "created_at": created, "source_artifact_sha256": entry["checksum_sha256"],
              "provenance_sha256": hashlib.sha256(json.dumps(provenance, sort_keys=True, default=str).encode()).hexdigest()}
    png = output_directory / f"{key}-map.png"
    pdf = output_directory / f"{key}-map.pdf"
    info = PngImagePlugin.PngInfo()
    info.add_text("NOVA_GIS_METADATA", json.dumps({"source": meta, "cartography": layout}, sort_keys=True, default=str))
    _draw_png(map_image, box, sheet_size, labels, scale).save(png, pnginfo=info, dpi=(_DPI, _DPI), optimize=True)
    _draw_pdf(pdf, map_image, box, sheet_size, labels, scale, title)
    carto_meta = {**meta, "cartography": layout}
    entries[f"{key}_map_png"] = artifact_entry(png, label=f"{title} map PNG (framed, 300 dpi)", media_type="image/png",
        artifact_type="report", result_version=version, role="export", product_key=key, delivery_type="map_png", format_name="png", gis_metadata=carto_meta)
    entries[f"{key}_map_pdf"] = artifact_entry(pdf, label=f"{title} map PDF (framed)", media_type="application/pdf",
        artifact_type="report", result_version=version, role="export", product_key=key, delivery_type="map_pdf", format_name="pdf", gis_metadata=carto_meta)
    if native is not None:
        class_values = [0, 1] if key in _CLASS_VALUE_KEYS else (list(range(1, len(bands) + 1)) if key == "flood_hazard_zonation" else None)
        package = output_directory / f"{key}-gis-layer.zip"
        buffer = BytesIO()
        native.save(buffer, format="PNG")
        world = [transform.a, transform.d, transform.b, transform.e, transform.c + transform.a / 2, transform.f + transform.e / 2]
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{key}.png", buffer.getvalue())
            archive.writestr(f"{key}.pgw", "\n".join(repr(float(value)) for value in world) + "\n")
            archive.writestr(f"{key}.prj", crs.to_wkt("WKT1_GDAL") + "\n")
            archive.writestr(f"{key}.qml", _qml(bands, continuous, value_range, class_values))
            archive.writestr(f"{key}.clr", _clr(bands, continuous, value_range, class_values))
            archive.writestr("README.txt", _readme(key, title, meta, provenance, continuous, crs))
        entries[f"{key}_gis_layer"] = artifact_entry(package, label=f"{title} GIS-ready layer (PNG + world file + QGIS/ArcGIS styles)",
            media_type="application/zip", artifact_type="report", result_version=version, role="export", product_key=key,
            delivery_type="gis_layer_zip", format_name="zip", gis_metadata={"crs": crs.to_string(), "bounds": list(bounds), "units": meta.get("units")})
    return entries


def build_cartographic_exports(output_directory: Path, *, product_entries: dict[str, dict],
                               provenance: dict, result_version: int) -> dict[str, dict]:
    """Render at most one simple framed map (and GIS-ready layer) per supported product key."""
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
