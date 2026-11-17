"""Map furniture for report-ready framed maps (Depth & Exposure module; owner review 2026-11-17).

Opt-in per layer through ``gis_metadata["furniture"]``, so existing framed maps are unchanged:

    {"title": str, "subtitle": str | None, "source": str, "legend_title": str | None, "nodata_label": str | None,
     "aoi_outline": GeoJSON geometry in EPSG:4326 | None,
     "points": {"path": "<file>.geojson", "min_confidence": 0.75, "label": str} | None}

Adds a title and subtitle above the map, the AOI outline, an optional point overlay (buildings), a north arrow, a
scale bar, a legend title and a source/attribution line. Pure drawing: no value is computed from the data here.
"""
from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from rasterio.crs import CRS

TOP_EXTRA = 170      # room for the title and subtitle
BOTTOM_EXTRA = 120   # room for the source line
CAVEAT_EXTRA = 90    # room for a caveat line (for example the flood map's commission error)
SNAP_PX = 15         # an AOI edge this close to the map frame is drawn on the frame (no double line)
INK = "#1A1A1A"
NICE_KM = (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 500)


def _font(size: int, bold: bool = False):
    from app.services.maps.cartography import _font as cartography_font
    return cartography_font(size, bold=bold)


def _to_px(lon: float, lat: float, box, bounds, crs: CRS):
    x0, y0, x1, y1 = box
    west, south, east, north = bounds
    if not crs.is_geographic:
        from pyproj import Transformer
        lon, lat = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    return x0 + (lon - west) / (east - west) * (x1 - x0), y0 + (north - lat) / (north - south) * (y1 - y0)


def _rings(geometry: dict):
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        yield from coords
    elif kind == "MultiPolygon":
        for polygon in coords:
            yield from polygon


CAVEAT_INK = "#7F1D1D"


def _snap(px: float, py: float, box) -> tuple[float, float]:
    """Put an outline point that is within SNAP_PX of the map frame exactly on the frame."""
    x0, y0, x1, y1 = box
    for edge in (x0, x1):
        if abs(px - edge) <= SNAP_PX:
            px = edge
    for edge in (y0, y1):
        if abs(py - edge) <= SNAP_PX:
            py = edge
    return px, py


def scale_bar_km(bounds, box, crs: CRS) -> tuple[float, float]:
    """(length in km, length in px) of a scale bar about a quarter of the map width."""
    west, south, east, north = bounds
    width_px = box[2] - box[0]
    if crs.is_geographic:
        km = (east - west) * 111.320 * math.cos(math.radians((south + north) / 2))
    else:
        km = (east - west) / 1000
    per_px = km / width_px
    target = km / 4
    length = max((value for value in NICE_KM if value <= target), default=NICE_KM[0])
    return length, length / per_px


def decorate(sheet: Image.Image, box, bounds, crs: CRS, furniture: dict[str, Any], output_directory: Path,
             legend_x: int) -> Image.Image:
    draw = ImageDraw.Draw(sheet)
    x0, y0, x1, y1 = box
    # AOI outline (drawn over the map, under the furniture).
    for ring in _rings(furniture.get("aoi_outline") or {}):
        points = [_snap(*_to_px(lon, lat, box, bounds, crs), box) for lon, lat in ring]
        if len(points) > 1:
            draw.line(points + [points[0]], fill=INK, width=4, joint="curve")
    # Point overlay (for example buildings above a confidence threshold).
    overlay = furniture.get("points") or {}
    drawn = 0
    if overlay.get("path"):
        path = output_directory / overlay["path"]
        if path.is_file():
            for feature in json.loads(path.read_text(encoding="utf-8")).get("features", []):
                if (feature.get("properties") or {}).get("confidence", 1) < overlay.get("min_confidence", 0):
                    continue
                px, py = _to_px(*feature["geometry"]["coordinates"][:2], box, bounds, crs)
                if x0 <= px <= x1 and y0 <= py <= y1:
                    draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=INK, outline="white", width=1)
                    drawn += 1
    # North arrow (top right, inside the frame).
    ax, ay = x1 - 70, y0 + 40
    draw.rounded_rectangle((ax - 40, ay - 22, ax + 40, ay + 120), radius=10, fill="white", outline=INK, width=2)
    draw.polygon([(ax, ay - 8), (ax - 22, ay + 62), (ax, ay + 48), (ax + 22, ay + 62)], fill=INK)
    draw.text((ax, ay + 72), "N", font=_font(36, bold=True), fill=INK, anchor="ma")
    # Scale bar (bottom left, inside the frame).
    km, px = scale_bar_km(bounds, box, crs)
    sx, sy = x0 + 40, y1 - 60
    draw.rounded_rectangle((sx - 20, sy - 60, sx + px + 70, sy + 30), radius=10, fill="white", outline=INK, width=2)
    half = px / 2
    draw.rectangle((sx, sy - 10, sx + half, sy + 10), fill=INK)
    draw.rectangle((sx + half, sy - 10, sx + px, sy + 10), fill="white", outline=INK, width=2)
    label = f"{km:g} km"
    draw.text((sx, sy - 18), "0", font=_font(28), fill=INK, anchor="mb")
    draw.text((sx + half, sy - 18), f"{km / 2:g}", font=_font(28), fill=INK, anchor="mb")
    draw.text((sx + px, sy - 18), label, font=_font(28), fill=INK, anchor="mb")
    # Title and subtitle (above the map).
    draw.text((x0, 20), furniture.get("title") or "", font=_font(44, bold=True), fill=INK, anchor="la")
    if furniture.get("subtitle"):
        draw.text((x0, 82), furniture["subtitle"], font=_font(32), fill="#333333", anchor="la")
    # Legend title (above the colour key) and the point-overlay key.
    if furniture.get("legend_title"):
        draw.text((legend_x, y0 - 18), furniture["legend_title"], font=_font(32, bold=True), fill=INK, anchor="ls")
    if overlay.get("label"):
        ly = y0 + 70 * furniture.get("_legend_rows", 0) + 22
        draw.ellipse((legend_x + 20, ly - 10, legend_x + 40, ly + 10), fill=INK, outline="white", width=1)
        draw.text((legend_x + 80, ly), overlay["label"], font=_font(34), fill=INK, anchor="lm")
    # Source / attribution line (bottom) and, above it, the caveat line; both wrapped to the sheet width.
    width_chars = max(60, int(sheet.size[0] / 15))
    source_lines = textwrap.wrap(furniture.get("source") or "", width_chars)
    for index, line in enumerate(source_lines):
        draw.text((x0, sheet.size[1] - 30 - (len(source_lines) - 1 - index) * 34), line, font=_font(26), fill="#333333", anchor="ls")
    if furniture.get("caveat"):
        caveat_lines = textwrap.wrap(furniture["caveat"], max(50, int(sheet.size[0] / 17)))
        base = sheet.size[1] - 30 - len(source_lines) * 34 - 18
        for index, line in enumerate(caveat_lines):
            draw.text((x0, base - (len(caveat_lines) - 1 - index) * 36), line, font=_font(28, bold=True), fill=CAVEAT_INK, anchor="ls")
    furniture["_drawn_points"] = drawn
    return sheet


def pdf_from_png(path: Path, sheet: Image.Image, title: str) -> None:
    """The framed map as a one-page PDF identical to the PNG (furniture included)."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    pt = 72 / 300
    width, height = sheet.size
    pdf = canvas.Canvas(str(path), pagesize=(width * pt, height * pt))
    pdf.setTitle(title)
    pdf.drawImage(ImageReader(sheet.convert("RGB")), 0, 0, width=width * pt, height=height * pt)
    pdf.showPage()
    pdf.save()
