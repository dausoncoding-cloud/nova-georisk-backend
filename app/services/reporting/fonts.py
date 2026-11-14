"""Embedded TrueType font for client PDFs.

ReportLab's built-in Helvetica is not embedded and lacks glyphs such as ≤, ≥ and κ, so viewers
may drop characters (e.g. km² rendered as 'km'). DejaVu Sans ships with matplotlib (already a
pinned dependency), so no new package or font file is added.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import matplotlib
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

REGULAR, BOLD, ITALIC, BOLD_ITALIC = "DejaVuSans", "DejaVuSans-Bold", "DejaVuSans-Oblique", "DejaVuSans-BoldOblique"
# ReportLab built-in names used by the default stylesheet, mapped to the embedded faces.
REPLACEMENTS = {"Helvetica": REGULAR, "Helvetica-Bold": BOLD, "Helvetica-Oblique": ITALIC, "Helvetica-BoldOblique": BOLD_ITALIC,
                "Times-Roman": REGULAR, "Times-Bold": BOLD, "Times-Italic": ITALIC, "Times-BoldItalic": BOLD_ITALIC}


@lru_cache(maxsize=1)
def register_fonts() -> str:
    """Register DejaVu Sans (all four faces) once; returns the regular face name."""
    directory = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    for name in (REGULAR, BOLD, ITALIC, BOLD_ITALIC):
        pdfmetrics.registerFont(TTFont(name, str(directory / f"{name}.ttf")))
    for bold, italic, face in ((0, 0, REGULAR), (1, 0, BOLD), (0, 1, ITALIC), (1, 1, BOLD_ITALIC)):
        addMapping(REGULAR, bold, italic, face)
    return REGULAR


def embed_in_styles(styles) -> None:
    """Point every paragraph style of a ReportLab stylesheet at the embedded faces."""
    register_fonts()
    for style in styles.byName.values():
        if getattr(style, "fontName", None) in REPLACEMENTS:
            style.fontName = REPLACEMENTS[style.fontName]
        if getattr(style, "bulletFontName", None) in REPLACEMENTS or getattr(style, "bulletFontName", None) == "Symbol":
            style.bulletFontName = REGULAR


def embed_in_drawing(drawing) -> None:
    """Point the strings and chart axis labels of a ReportLab drawing at the embedded face (PDF use)."""
    register_fonts()
    if drawing.__class__.__name__ == "Drawing":
        drawing.initialFontName = REGULAR  # the renderer's initial graphics state
    for item in getattr(drawing, "contents", []):
        if getattr(item, "fontName", None) is not None:
            item.fontName = REPLACEMENTS.get(item.fontName, REGULAR)
        for axis in ("xValueAxis", "yValueAxis", "categoryAxis", "valueAxis"):
            labels = getattr(getattr(item, axis, None), "labels", None)
            if labels is not None:
                labels.fontName = REGULAR
        if getattr(item, "contents", None):
            embed_in_drawing(item)


def pdf_template_kwargs() -> dict:
    """SimpleDocTemplate arguments that keep the canvas default font embedded."""
    return {"initialFontName": register_fonts()}
