"""Client scientific report for FRRIS flood results (plan item 2.4), as PDF and DOCX.

Content comes only from what the result already holds: the computed overview (headline,
area accounting, quality gates, data sources, limitations), the accuracy assessment
(independent census first, internal agreement second), the framed maps and provenance.
Maps are embedded as delivered; captions, dates and keys are written as report text.
"""
from __future__ import annotations
from app.services.reporting.dates import period_dict_text

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document
from docx.shared import Cm, Inches
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.services.reporting.figures import multi_roc_figure, multi_roc_panels_figure, scope_figures
from app.services.reporting.fonts import embed_in_styles, register_fonts
from app.services.validation.accuracy_tables import reference_columns
from app.services.validation.auc_presentation import scope_auc
from app.services.validation.diagnostics import LIMITATIONS as DIAGNOSTIC_LIMITATIONS
from app.services.validation.multi_roc import record_summary_rows

STATUS = {"not_assessable": "not assessable", "insufficient_reference_samples": "insufficient reference samples",
          "not_performed": "not performed", "assessed": "assessed"}
GATE_STATUS = {"pass": "Pass", "fail": "Fail", "not_recorded": "Not recorded", "not_applicable": "Not applicable"}
# Outputs this report does not contain yet; listed by name only, never as empty sections.
NOT_INCLUDED = ["Water delineation", "Trend analysis", "Permanent and seasonal water classes (JRC) on the main map"]
SCOPE_SHORT = {"independent_optical": "Independent optical reference", "internal_screening": "Internal agreement (not independent)",
               "internal_supplied": "Internal agreement with supplied labels (not independent)"}


def _num(value, digits=2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _count(value) -> str:
    return "—" if value is None else f"{int(value):,}"


def fraction_text(fraction: str | None) -> str:
    """'2807/5736' -> '2,807/5,736'."""
    if not fraction:
        return "—"
    numerator, denominator = fraction.split("/")
    return f"{int(numerator):,}/{int(denominator):,}"


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence(text: str) -> str:
    text = text.strip()
    return (text[:1].upper() + text[1:]).rstrip(".") + "."


def share_phrase(pct: float) -> str:
    """Plain-language share for an accuracy percentage."""
    if pct < 10:
        return "very little"
    if pct < 25:
        return "less than a quarter"
    if pct < 40:
        return "about a third"
    if pct < 60:
        return "about half"
    if pct < 75:
        return "about two thirds"
    if pct < 90:
        return "most"
    return "nearly all"


def _independent_summary(scope: dict) -> list[str]:
    flood = next(row for row in scope["per_class"] if row["class_label"] == "1")
    ua, pa = flood["users_accuracy_pct"], flood["producers_accuracy_pct"]
    lines = [f"Independent accuracy against the Sentinel-2 optical reference (census, n = {scope['n']:,} pixels not used for training): "
             f"overall accuracy {_num(scope['overall_accuracy_pct'], 1)}%, kappa {_num(scope['cohens_kappa'], 3)}, "
             f"F1 {_num(scope['f1_flooded'], 3)}; flood candidate user's accuracy {_num(ua, 1)}% and producer's accuracy {_num(pa, 1)}%."]
    if ua is not None and pa is not None:
        lines.append(f"In plain terms, the model detects {share_phrase(pa)} of the new open water seen by the optical reference, "
                     f"and {share_phrase(ua)} of its flood-candidate pixels are new open water in the optical reference.")
    return lines


# A4 with 2 cm side margins leaves a 16.6 cm PDF frame (ReportLab pads 6 pt) and Word's default page 16.5 cm;
# figures are drawn at 16 cm (1:1) and never exceed these limits, so nothing is clipped or rescaled by a viewer.
FIGURE_MAX_WIDTH_CM = 16.0
FIGURE_MAX_HEIGHT_CM = 20.5  # frame height 24.2 cm (PDF) / 22.9 cm (Word) less room for a caption


class _Writer:
    """Writes the same content to a ReportLab story and a python-docx document."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        embed_in_styles(self.styles)  # embedded DejaVu Sans: ², ≤, ≥, κ, – and · always render
        for name in ("Heading1", "Heading2", "Heading3"):
            self.styles[name].keepWithNext = 1  # a heading never ends a page
        self.story: list = []
        self.doc = Document()
        section = self.doc.sections[0]  # the same page as the PDF: A4, 2 cm side margins (17 cm text width)
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.0)
        self.figures = 0  # figures are numbered in order: "Figure 1.", "Figure 2.", …

    @property
    def next_figure(self) -> int:
        return self.figures + 1

    def heading(self, text: str, level: int = 1):
        self.story.append(Paragraph(escape(text), self.styles["Heading1" if level == 0 else "Heading2" if level == 1 else "Heading3"]))
        self.doc.add_heading(text, level=level)

    def para(self, text: str):
        self.story.append(Paragraph(escape(text), self.styles["BodyText"]))
        self.doc.add_paragraph(text)

    def keep_together(self, start: int):
        """Keep everything added since `start` on one PDF page (moves to the next page if needed)."""
        while start > 0 and isinstance(self.story[start - 1], Paragraph) and getattr(self.story[start - 1].style, "keepWithNext", 0):
            start -= 1  # take the heading along: keepWithNext does not bind to a KeepTogether block
        self.story[start:] = [KeepTogether(self.story[start:])]

    def table(self, header: list[str], rows: list[list[str]], caption: str | None = None):
        start = len(self.story)
        if caption:
            self.para(caption)
        data = [header] + rows
        cell = self.styles["BodyText"].clone("cell", fontSize=7, leading=8.5)
        table = Table([[Paragraph(escape(str(value)), cell) for value in row] for row in data], repeatRows=1)
        table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), register_fonts()), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef3")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        self.story += [table, Spacer(1, 0.3 * cm)]
        self.keep_together(start)  # never split a table from its caption or orphan its last row
        docx_table = self.doc.add_table(rows=len(data), cols=len(header))
        docx_table.style = "Table Grid"
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                docx_table.cell(r, c).text = str(value)

    def image(self, path: Path, width_cm: float, caption: str, max_height_cm: float | None = None) -> int:
        """Add a numbered figure ("Figure N. caption"), never wider or taller than the page allows; returns N."""
        from PIL import Image
        with Image.open(path) as source:
            ratio = source.height / source.width
        width_cm = min(width_cm, FIGURE_MAX_WIDTH_CM)
        limit = min(max_height_cm or FIGURE_MAX_HEIGHT_CM, FIGURE_MAX_HEIGHT_CM)
        if width_cm * ratio > limit:
            width_cm = limit / ratio
        self.figures += 1
        caption = f"Figure {self.figures}. {caption}"
        start = len(self.story)
        self.story += [PdfImage(str(path), width=width_cm * cm, height=width_cm * ratio * cm), Paragraph(escape(caption), self.styles["Italic"]),
                       Spacer(1, 0.3 * cm)]
        self.keep_together(start)  # a figure is never separated from its caption
        self.doc.add_picture(str(path), width=Inches(width_cm / 2.54))
        self.doc.add_paragraph(caption)
        return self.figures


def write_pdf(writer: "_Writer", path: Path) -> None:
    SimpleDocTemplate(str(path), pagesize=A4, title="FRRIS scientific report", leftMargin=2 * cm, rightMargin=2 * cm,
                      initialFontName=register_fonts()).build(writer.story)


def internal_agreement_sentence(scope: dict) -> str:
    """Section 9 keeps one sentence on internal agreement: why it is high and why it is not accuracy."""
    labels = "the SAR screening labels" if scope["scope"] == "internal_screening" else "the supplied labels"
    return (f"Internal agreement with {labels} on {scope['n']:,} held-out pixels is {_num(scope['overall_accuracy_pct'], 1)}% "
            f"(kappa {_num(scope['cohens_kappa'], 3)}) because the classifier is trained to reproduce these labels from the same "
            "inputs, so it shows how well the labelling rule was learned and is not map accuracy (details in Appendix A).")


VARIABLE_ROC_TITLE = "ROC by variable — vs Sentinel-2 reference (independent)"


def variable_roc_caption(record: dict, context: dict, *, panels: bool = False, combined: int | None = None) -> str:
    """Full caption: what is measured, the reference, n, area and dates."""
    from app.services.firris.variable_roc import MODEL_SCORE, model_label

    model = next((c["label"] for c in record.get("curves") or [] if c["name"] == MODEL_SCORE), model_label(None))
    where = (f"{context.get('aoi') or 'the area of interest'}"
             + (f" ({_num(context['area_km2'])} km²)" if context.get("area_km2") is not None else "")
             + f"; target {context.get('target') or 'not recorded'}, baseline {context.get('baseline') or 'not recorded'}")
    head = (f"ROC by variable, one panel per variable: the same curves and AUCs as Figure {combined}. " if panels and combined
            else "ROC by variable, one panel per variable. " if panels
            else f"ROC by variable: the {model} (the map's model score) and each model variable. ")
    measured = ("Measured against the independent Sentinel-2 optical flood reference (MNDWI change; not a model input; "
                f"not field-verified) on n = {record['n']:,} eligible pixels not used for training, the same pixels as the "
                f"accuracy census ({record['positives']:,} flood, {record['negatives']:,} not flood), in {where}. ")
    how = ("Each AUC is exact and comes from the continuous values, not from classes; directions (lower or higher = flood) "
           "were fixed before the analysis. Dashed grey line: random classifier (AUC 0.500). ")
    tail = ("Each panel gives the AUC with its direction and n; the circle on the model panel is the map's operating point "
            "(t = 0.50); a panel that is not assessable gives the reason instead of a curve." if panels
            else "Legend ordered by AUC, high to low; the circle is the map's operating point (t = 0.50). Threshold tables: "
                 "workbook sheet \"ROC thresholds by variable\" and the CSV in the result package; summary in Appendix C.")
    return head + measured + how + tail


def variable_roc_section(writer: "_Writer", output_directory: Path, record: dict, *, same_reason: str | None = None,
                         context: dict | None = None) -> dict[str, tuple[Path, str]]:
    """r5.3: one chart with the model score and each variable against the Sentinel-2 reference, or why not."""
    from app.services.firris.variable_roc import MODEL_SCORE, OPERATING_POINT_NOTE

    context = context or {}
    writer.heading("ROC by variable (independent Sentinel-2 reference)", 2)
    if record.get("status") != "assessed":
        reason = record.get("reason")
        writer.para("Multi-variable ROC: not assessable, for the same reason as the independent accuracy above."
                    if reason and reason == same_reason else f"Multi-variable ROC: not assessable. {_sentence(reason or 'reason not recorded')}")
        return {}
    paths = multi_roc_figure(record, output_directory / "figure-independent_optical-roc_by_variable", title=VARIABLE_ROC_TITLE,
                             model=MODEL_SCORE, note=OPERATING_POINT_NOTE, positive="flood")
    panels = multi_roc_panels_figure(record, output_directory / "figure-independent_optical-roc_by_variable_panels",
                                     title=VARIABLE_ROC_TITLE + ", one panel per variable", model=MODEL_SCORE, positive="flood")
    rows = record_summary_rows(record)
    missing = [f"{row['label']}: {row['reason']}" for row in rows if row["status"] != "assessed"]
    number = writer.next_figure
    writer.para(f"Figure {number} shows each curve from the continuous value on the same {record['n']:,} census pixels as the "
                "accuracy above (eligible pixels not used for training), never binary classes; each AUC is exact. The model "
                "curve is the ROC reported above. The variables are model inputs: their curves show how well each one alone "
                "separates the Sentinel-2 flood reference; they are not separate models. Directions (lower or higher = flood) "
                "were fixed before the analysis; an AUC below 0.5 means the variable runs opposite to that direction in this "
                "area. Appendix C shows the same curves one panel per variable."
                + (f" Not assessable: {'; '.join(missing)}." if missing else ""))
    writer.image(paths["png"], FIGURE_MAX_WIDTH_CM, variable_roc_caption(record, context))
    return {"figure_independent_optical_roc_by_variable_png": (paths["png"], "image/png"),
            "figure_independent_optical_roc_by_variable_svg": (paths["svg"], "image/svg+xml"),
            "figure_independent_optical_roc_by_variable_panels_png": (panels["png"], "image/png"),
            "figure_independent_optical_roc_by_variable_panels_svg": (panels["svg"], "image/svg+xml"),
            "_combined_figure_number": number}


def variable_roc_appendix(writer: "_Writer", record: dict, panels: Path | None = None, *, context: dict | None = None,
                          combined: int | None = None) -> None:
    if record.get("status") != "assessed":
        return
    writer.heading("Appendix C: ROC by variable — threshold summary", 1)
    if panels is not None and panels.exists():
        writer.image(panels, FIGURE_MAX_WIDTH_CM, variable_roc_caption(record, context or {}, panels=True, combined=combined))
    def pair(tpr, fpr):
        return "—" if tpr is None else f"TPR {tpr:.3f}, FPR {fpr:.3f}"
    rows = []
    for row in record_summary_rows(record):
        best = "—" if row["best_threshold"] is None else f"{row['best_threshold']:.4g} ({pair(row['best_tpr'], row['best_fpr'])})"
        rows.append([row["label"], row["positive_when"].replace("score", "flood when value"),
                     f"{row['auc']:.3f}" if row["auc"] is not None else "not assessable", best,
                     pair(row["operating_point_tpr"], row["operating_point_fpr"]) if row["operating_point_tpr"] is not None else "—"])
    writer.table(["Variable", "Direction", "AUC", "Highest TPR − FPR on the grid (threshold)", "Operating point (t = 0.50)"], rows,
                 caption=f"Against the Sentinel-2 reference, census of n = {record['n']:,} pixels "
                         f"({record['positives']:,} flood, {record['negatives']:,} not flood).")
    writer.para("Thresholds: the model score uses 0.99 to 0.01 in steps of 0.01; each variable uses the 1st to 99th "
                "percentiles of its values on these pixels. The full tables (threshold, TP, FP, TN, FN, TPR, FPR) are in the "
                "workbook sheet \"ROC thresholds by variable\" and in accuracy-independent_optical-roc-by-variable.csv.")


def _accuracy_scope(writer: _Writer, scope: dict, figures: dict[str, dict[str, Path]], audit: dict | None, title: bool = True):
    if title:
        writer.heading(scope["title"], 2)
    independent = scope["scope"] == "independent_optical"
    method = (f"Census of n = {scope['n']:,} eligible pixels not used for training." if scope["method"] == "census"
              else f"Held-out sample, n = {scope['n']:,}.")
    stated = "not field-verified" in scope["reference_basis"].lower()
    writer.para(f"Reference: {scope['reference_basis']}. {method}" + (" Not field-verified." if independent and not stated else ""))
    matrix = scope["confusion_matrix"]
    rows = []
    for label, name in (("1", "Classified: flood candidate"), ("0", "Classified: not flood candidate")):
        values = matrix["classified"][label]
        ua = values["users_accuracy"]
        rows.append([name, f"{values['reference_1']:,}", f"{values['reference_0']:,}", f"{values['total']:,}", f"{fraction_text(ua['fraction'])} ({_num(ua['pct'], 1)}%)"])
    rows.append(["Total", f"{matrix['reference_totals']['1']:,}", f"{matrix['reference_totals']['0']:,}", f"{matrix['reference_totals']['all']:,}", ""])
    pa = matrix["producers_accuracy"]
    rows.append(["Producer's accuracy", f"{fraction_text(pa['1']['fraction'])} ({_num(pa['1']['pct'], 1)}%)",
                 f"{fraction_text(pa['0']['fraction'])} ({_num(pa['0']['pct'], 1)}%)", "", ""])
    writer.table(["Classified \\ Reference", *reference_columns(scope["scope"]), "Total", "User's accuracy"], rows,
                 caption="Confusion matrix (classified × reference).")
    writer.table(["Class", "Area (ha)", "Omission error (%)", "Commission error (%)", "User's accuracy (%)", "Producer's accuracy (%)", "F1"],
                 [[row["class_name"], _num(row["area_ha"]), _num(row["omission_error_pct"], 1), _num(row["commission_error_pct"], 1),
                   _num(row["users_accuracy_pct"], 1), _num(row["producers_accuracy_pct"], 1), _num(row["f1_score"], 3)] for row in scope["per_class"]],
                 caption="Per-class accuracy summary.")
    auc = scope_auc(scope)
    writer.para(f"Overall accuracy {_num(scope['overall_accuracy_pct'], 1)}% · Kappa {_num(scope['cohens_kappa'], 3)} · "
                f"F1 (flood candidate) {_num(scope['f1_flooded'], 3)} · IoU {_num(scope['iou_flooded'], 3)} · "
                f"AP {_num(scope['average_precision'], 3)}.")
    writer.table(["Quantity", "Value"], [
        ["Reference", auc.label],
        ["ROC AUC", f"{auc.value:.3f}" if auc.assessable else "not assessable"],
        ["95% interval", (f"{auc.interval[0]:.3f}–{auc.interval[1]:.3f}" if auc.interval else _capitalised(auc.interval_note or "—"))
         if auc.assessable else "—"],
        ["Reference classes", f"{auc.positives:,} positive, {auc.negatives:,} negative"],
        *([] if auc.assessable else [["Why not assessable", _sentence(auc.reason)]]),
    ], caption="ROC AUC (area under the ROC curve), labelled by the reference it is measured against.")
    if auc.caveat:
        writer.para(auc.caveat)
    intervals = scope.get("confidence_intervals_95")
    if intervals:
        def span(values, digits):
            return "—" if not values else f"{values[0]:.{digits}f}–{values[1]:.{digits}f}"
        writer.para(f"95% interval ({intervals['method']}): OA {span(intervals['overall_accuracy_pct'], 1)}%, "
                    f"Kappa {span(intervals['cohens_kappa'], 3)}.")
    else:
        writer.para(_sentence(scope["interval_note"]))
    weighted = (audit or {}).get("weighted_estimates") if independent else None
    if weighted:
        per_class = audit.get("per_class") or {}
        writer.para(f"Audit sample (stratified by reference class, {_count(per_class.get('1'))} + {_count(per_class.get('0'))} pixels; "
                    f"area-weighted estimates, Olofsson et al. 2014): overall accuracy {_num(weighted.get('overall_accuracy_pct'), 1)}%, "
                    f"kappa {_num(weighted.get('cohens_kappa'), 3)}, flood candidate user's accuracy {_num(weighted.get('users_accuracy_flooded_pct'), 1)}% "
                    f"and producer's accuracy {_num(weighted.get('producers_accuracy_flooded_pct'), 1)}%. "
                    "The audit sample is for visual checking; the census metrics are the reported accuracy.")
    short = SCOPE_SHORT.get(scope["scope"], scope["title"])
    roc_caption = (f"ROC curve ({auc.label}) with the 1:1 chance line." if auc.assessable
                   else f"ROC: {auc.label} not assessable; no curve is drawn.")
    for kind, caption in (("roc", roc_caption), ("pr", "precision–recall curve with the prevalence baseline.")):
        writer.image(figures[kind]["png"], 8, f"{short}: {caption}")


APPENDIX_GROUPS = [("client_deliverable", "Client deliverables"), ("gis_data", "GIS data"),
                   ("figures", "Figures and accuracy tables"), ("audit", "Audit and provenance")]
def _gate_row(gate: dict, independent_status: str) -> list[str]:
    """A quality-gate row; backlog §4.7 items 20 and 21 (no repeated reason text, 'not applicable' when no scene)."""
    from app.api.v1.result_overview import NO_SCENE_TEXT
    observed, status = gate["observed"] or "—", GATE_STATUS.get(gate["status"], gate["status"])
    if gate["status"] == "not_applicable" and gate["observed"] == NO_SCENE_TEXT:
        observed, status = "—", "Not applicable (no compliant scene)"
    elif gate["name"] == "Independent reference" and independent_status != "assessed":
        observed = f"{STATUS.get(independent_status, independent_status)} (reason in section 9)"
    return [gate["name"], gate["threshold"], observed, status]


NOT_PRODUCED_WITH_HAZARD = ("Observed flood depth, velocity, exposure, vulnerability and risk are not produced. The modelled "
                            "river-flood hazard in section {hazard} (GloFAS) is undefended model context, not an observation of this event.")
NOT_PRODUCED_WITH_EXPOSURE = ("Observed flood depth, velocity, vulnerability and risk are not produced. The modelled river-flood "
                              "hazard (section {hazard}) is undefended model context, and the exposure (section {exposure}) is an "
                              "estimate of people and buildings inside each extent, not of people affected or damage.")
FIGURE_KINDS = {"modelled_hazard_depth_by_return_period": "Modelled flood hazard — depth by return period",
                "modelled_hazard_aep": "Modelled flood hazard — AEP and probability of at least one occurrence",
                "roc_by_variable_panels": "ROC by variable, one panel per variable", "roc_by_variable": "ROC by variable",
                "roc": "ROC curve", "pr": "precision–recall curve", "confusion": "confusion matrix", "class_metrics": "per-class accuracy"}
TABLE_KINDS = {"roc_by_variable": "ROC threshold table by variable", "roc_auc_by_variable": "ROC AUC by variable",
               "confusion": "confusion matrix", "summary": "per-class accuracy summary", "roc": "ROC curve points", "pr": "precision–recall curve points"}
APPENDIX_LABELS = {
    "validation_confusion_counts_plot": "Internal validation: confusion counts plot (SVG)",
    "validation_class_imbalance_plot": "Internal validation: class support plot (SVG)",
    "validation_roc_plot": "Internal validation: ROC plot (SVG)",
    "validation_precision_recall_plot": "Internal validation: precision–recall plot (SVG)",
    "validation_threshold_f1_plot": "Internal validation: F1 by threshold plot (SVG)",
    "validation_roc_data": "Internal validation: ROC points (CSV)",
    "validation_precision_recall_data": "Internal validation: precision–recall points (CSV)",
    "validation_thresholds_data": "Internal validation: threshold sweep (CSV)",
    "acquired_feature_stack": "Received Earth Engine export, as downloaded",
    "extracted_feature_stack": "Received Earth Engine export, extracted GeoTIFF",
    "source_sar_baseline": "Sentinel-1 VV composite, baseline period (COG)",
    "source_sar_target": "Sentinel-1 VV composite, target period (COG)",
    "source_mndwi_baseline": "Sentinel-2 MNDWI, baseline period (COG)",
    "source_mndwi_target": "Sentinel-2 MNDWI, target period (COG)",
    "jrc_occurrence": "JRC surface-water occurrence (COG)",
    "optical_reference": "Independent optical reference layer (COG)",
}
FORMAT_SUFFIXES = {" gpkg": " (GeoPackage)", " kml": " (KML)", " shapefile_zip": " (Shapefile)"}


def figure_label(name: str) -> str:
    """'figure_independent_optical_roc_png' -> 'Independent optical reference — ROC curve (PNG, 300 dpi)'."""
    stem, fmt = name.removeprefix("figure_").rsplit("_", 1)
    scope = next((s for s in SCOPE_SHORT if stem.startswith(s + "_")), None)
    kind = stem.removeprefix(scope + "_") if scope else stem
    prefix = SCOPE_SHORT[scope] + " — " if scope else ""
    text = f"{prefix}{FIGURE_KINDS.get(kind, kind.replace('_', ' '))} ({'PNG, 300 dpi' if fmt == 'png' else fmt.upper()})"
    return text[:1].upper() + text[1:]


def appendix_label(key: str, entry: dict) -> str:
    if key in APPENDIX_LABELS:
        return APPENDIX_LABELS[key]
    if key.startswith("figure_"):
        return figure_label(key)
    if key.startswith("accuracy_"):
        scope = next((s for s in SCOPE_SHORT if key.startswith(f"accuracy_{s}_")), None)
        if scope:
            kind = key.removeprefix(f"accuracy_{scope}_")
            return f"{SCOPE_SHORT[scope]} — {TABLE_KINDS.get(kind, kind)} (CSV)"
    label = str(entry.get("label") or key.replace("_", " "))
    for raw, suffix in FORMAT_SUFFIXES.items():
        if label.endswith(raw):
            label = label[: -len(raw)] + suffix
    return label[:1].upper() + label[1:]


def _client_rank(key: str, entry: dict) -> int:
    if key.startswith("scientific_report"):
        return 0
    if entry.get("delivery_type") in {"map_png", "map_pdf"}:
        return 1
    return 3 if key == "report_package" else 2


# The report lists what a client opens first; everything else is listed in the package README.
REPORT_APPENDIX_GROUPS = ("client_deliverable", "gis_data")
README_POINTER = ("Figures, accuracy tables, audit and provenance files are listed in README.txt inside the FRRIS result package "
                  "(frris-result-package.zip).")


def grouped_downloads(downloads: list[tuple[str, dict]], *, unique: bool = True) -> list[tuple[str, str, list[tuple[str, dict, str]]]]:
    """Downloads by group (download-page order) with readable labels; unique=True drops repeated labels."""
    from app.api.v1.serializers import deliverable_group

    grouped: dict[str, list[tuple[str, dict]]] = {}
    for key, entry in downloads:
        grouped.setdefault(deliverable_group(key, entry), []).append((key, entry))
    result = []
    for group, title in APPENDIX_GROUPS:
        items = sorted(grouped.get(group, []), key=lambda item: _client_rank(*item)) if group == "client_deliverable" else grouped.get(group, [])
        rows: list[tuple[str, dict, str]] = []
        for key, entry in items:
            label = appendix_label(key, entry)
            if label in [row[2] for row in rows] and entry.get("format"):
                label = f"{label} ({str(entry['format']).upper()})"
            if not unique or label not in [row[2] for row in rows]:
                rows.append((key, entry, label))
        if rows:
            result.append((group, title, rows))
    return result


def _appendix(writer: _Writer, downloads: list[tuple[str, dict]]):
    for group, title, rows in grouped_downloads(downloads):
        if group in REPORT_APPENDIX_GROUPS:
            writer.heading(title, 2)
            for _, _, label in rows:
                writer.para(f"• {label}")
    writer.para(README_POINTER)


def package_readme(files: list[tuple[str, str, dict]]) -> str:
    """README.txt for the result package: every file (archive name) by download group, with its label."""
    by_key = {key: arcname for arcname, key, _ in files}
    lines = ["FRRIS result package", "", "Files in this package, grouped as on the download page.", ""]
    for _, title, rows in grouped_downloads([(key, entry) for _, key, entry in files], unique=False):
        lines += [title, "-" * len(title)]
        lines += [f"{by_key[key]}  —  {label}" for key, _, label in rows]
        lines.append("")
    from app.services.firris.hazard_sources import GLOFAS_DATABASE_NOTICE, GLOFAS_DERIVED_KEYS, GLOFAS_PRODUCED_WORK_NOTICE
    derived = sorted(arcname for arcname, key, _ in files if key.startswith(GLOFAS_DERIVED_KEYS))
    if derived:  # ODbL v1.0: derivative databases say so, with no added restrictions; Produced Works carry the notice
        lines += ["Licence note: GloFAS-derived data", "-" * 33, GLOFAS_DATABASE_NOTICE,
                  "These files are available under ODbL v1.0:"] + [f"  {name}" for name in derived] + [
                  f"Maps, graphs and the report made from them carry the notice: \"{GLOFAS_PRODUCED_WORK_NOTICE}\".", ""]
    return "\n".join(lines)


def scene_selection_text(quality: dict) -> str:
    """Sentinel-2 scene and pixel rules in words, from the values recorded for the run."""
    cloud, degraded = quality.get("max_cloud_pct"), quality.get("degraded_msi_max_pct")
    scene = (f"cloud cover ≤ {cloud:g}%" if cloud is not None else "cloud cover threshold not recorded") + " and " + (
        f"degraded MSI ≤ {degraded:g}%" if degraded is not None else "degraded-MSI threshold not recorded")
    return (f"Sentinel-2 scene selection: {scene} per scene, in both periods (applied in the scene query and checked for every "
            "scene). Within the scenes used, clouds, cloud shadow, cirrus, snow and saturated or defective pixels (SCL class 1) "
            "are masked per pixel.")


def _midpoint(period: dict | None):
    from datetime import date
    if not period or not period.get("start") or not period.get("end"):
        return None
    start, end = date.fromisoformat(str(period["start"])[:10]), date.fromisoformat(str(period["end"])[:10])
    return start + (end - start) / 2


def baseline_gap_text(target: dict | None, baseline: dict | None, *, max_days: int = 90, max_season_days: int = 45) -> str | None:
    """Limitation when the baseline is far from the target or at another time of year (from the run's periods)."""
    target_mid, baseline_mid = _midpoint(target), _midpoint(baseline)
    if target_mid is None or baseline_mid is None:
        return None
    gap = (target_mid - baseline_mid).days
    offset = abs(target_mid.timetuple().tm_yday - baseline_mid.timetuple().tm_yday)
    season = min(offset, 365 - offset)
    if abs(gap) <= max_days and season <= max_season_days:
        return None
    direction = "before" if gap >= 0 else "after"
    return (f"The baseline period ({period_dict_text(baseline)}) is {abs(gap):,} days {direction} the target period "
            f"({period_dict_text(target)}), measured between period midpoints, and {season} days apart in the annual "
            "cycle; seasonal changes in vegetation, soil moisture and standing water can therefore be mixed with flooding in the "
            "change signal.")


def score_limitations(summary: dict, assessment: dict) -> list[str]:
    """Plan review defect 12: near-binary Random Forest scores and tied ROC operating points, from the run."""
    distribution = ((summary.get("products") or {}).get("flood_probability") or {}).get("score_distribution")
    if not distribution:
        return []
    lines = [f"Random Forest confidence scores are near-binary: {distribution['exact_0_pct']:.1f}% of valid pixels score exactly 0 "
             f"and {distribution['exact_1_pct']:.1f}% exactly 1 ({distribution['between_pct']:.1f}% in between). The training labels "
             "come from the deterministic SAR screening rule, which the classifier reproduces almost exactly. The model and its "
             "scores are reported unchanged."]
    independent = next((s for s in assessment.get("scopes", []) if s["scope"] == "independent_optical"), None)
    points = [(p["fpr"], p["tpr"]) for p in (independent or {}).get("roc", []) if p["fpr"] is not None and p["tpr"] is not None]
    inner = [point for point in points if point[0] < 1]
    if independent and independent.get("roc_auc") and inner:
        fpr, tpr = max(inner)
        segment = (1 - fpr) * (tpr + 1) / 2
        lines.append(f"Pixels tied at the lowest score form one straight ROC segment from false positive rate {fpr:.3f} to 1; "
                     f"that segment contributes {segment:.3f} of the independent AUC {independent['roc_auc']:.3f}. "
                     "ROC and precision–recall curves therefore have few distinct operating points.")
    return lines


def build_scientific_report(output_directory: Path, *, ids: dict[str, str], names: dict[str, str | None], result_version: int,
                            summary: dict, provenance: dict, gis_metadata: dict, map_entries: dict[str, dict],
                            downloads: list[tuple[str, dict]], sample_report: bool = False) -> dict[str, tuple[Path, str]]:
    from app.api.v1.result_overview import build_result_overview

    overview = build_result_overview(SimpleNamespace(engine_key="firris", summary=summary, provenance=provenance))
    if overview is None:
        return {}
    assessment = (summary.get("validation_dashboard") or {}).get("accuracy_assessment") or {}
    writer = _Writer()
    writer.heading("FRRIS flood-candidate analysis — scientific report", 0)
    project = names.get("project") or f"Project ID {ids['project']}"
    aoi = names.get("aoi") or f"AOI ID {ids['aoi']}"
    if sample_report:
        writer.para("Sample report")
    if names.get("organization"):
        writer.para(f"Prepared by: {names['organization']}")
    writer.para(f"Project: {project}")
    writer.para(f"Area of interest: {aoi}")
    writer.para(f"Result version {result_version} · generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    writer.heading("1. Executive summary")
    writer.para(overview["headline"]["text"])
    status = assessment.get("independent_status") or (summary.get("independent_accuracy") or {}).get("status") or "not_performed"
    reason = assessment.get("independent_reason") or (summary.get("independent_accuracy") or {}).get("reason")
    independent = next((s for s in assessment.get("scopes", []) if s["scope"] == "independent_optical"), None)
    if status == "assessed" and independent:
        for line in _independent_summary(independent):
            writer.para(line)
    else:
        # Backlog §4.7 item 21: the full reason is given once, in section 9.
        writer.para(f"Independent accuracy: {STATUS.get(status, status)}" + ("; the reason is given in section 9." if reason else "."))
    writer.heading("Scope of this report: not included in this version", 2)
    for name in NOT_INCLUDED:
        writer.para(f"• {name}")

    area = overview["area_accounting"]
    writer.heading("2. Study area")
    box = gis_metadata.get("bounding_box") or {}
    corner = lambda value: "—" if value is None else f"{value:.5f}"  # noqa: E731 - ~1 m at the equator
    writer.para(f"{aoi}. Estimated AOI area {_num(area['aoi_area_km2_estimate'])} km² ({_count(area['aoi_cells'])} cells); "
                f"bounding box {corner(box.get('west'))}, {corner(box.get('south'))} to {corner(box.get('east'))}, {corner(box.get('north'))} "
                f"({gis_metadata.get('crs', 'CRS not recorded')}).")

    writer.heading("3. Target and baseline periods")
    headline = overview["headline"]
    target_text = period_dict_text(provenance.get("target_period")) or "not recorded"
    baseline_text = period_dict_text(provenance.get("baseline_period")) or "not recorded"
    writer.para(f"Target: {target_text}; baseline: {baseline_text}. Both periods include their last day.")
    writer.table(["Dataset", "Scene dates"], [[s["dataset"], ", ".join(s["scene_dates"]) or "static product"] for s in overview["data_sources"]])

    writer.heading("4. Input data")
    writer.table(["Dataset", "Role", "Resolution", "Credit"], [[s["dataset"], s["role"], s["resolution"], s["credit"]] for s in overview["data_sources"]])

    writer.heading("5. Method")
    validation = provenance.get("validation") or {}
    basis = validation.get("reference_basis") or {}
    model = summary.get("model") or {}
    writer.para(f"Screening labels: {basis.get('rule') or 'not recorded'}.")
    writer.para(f"Classifier: {model.get('algorithm', 'not recorded')} on features {', '.join(model.get('feature_names') or []) or 'not recorded'}; "
                f"split: {basis.get('split_method', 'not recorded')}.")
    policy = provenance.get("optical_reference_policy") or {}
    if policy:
        writer.para(f"Independent optical reference: {policy.get('definition')}.")
    writer.para(scene_selection_text(summary.get("quality") or {}))

    writer.heading("6. Quality gates")
    writer.table(["Gate", "Threshold", "Observed", "Status"],
                 [_gate_row(g, status) for g in overview["quality_gates"]])

    start = len(writer.story)
    writer.heading("7. Main maps")
    from app.services.reporting.exposure_report import exposure_section, is_exposure_map
    from app.services.reporting.hazard_report import hazard_section, is_hazard_map
    for key, entry in sorted(map_entries.items()):
        # Modelled hazard and exposure maps go in their own sections after the accuracy assessment.
        if entry.get("delivery_type") == "map_png" and not is_hazard_map(key) and not is_exposure_map(key):
            title = (entry.get("gis_metadata") or {}).get("cartography", {}).get("title", key)
            # Two maps share one A4 page: each image is at most 10 cm tall.
            writer.image(output_directory / entry["path"], 16, f"{title}. Target {target_text}; baseline {baseline_text}.",
                         max_height_cm=10)
    writer.keep_together(start)

    writer.heading("8. Area statistics")
    writer.table(["Quantity", "Value"], [
        ["Valid analysed area", f"{_num(area['valid_area_km2'])} km² ({_num(area['valid_pct_of_aoi'])}% of AOI)"],
        ["Excluded (no valid data)", f"{_num(area['excluded_area_km2_estimate'])} km² ({_count(area['excluded_cells'])} cells)"],
        ["Flood candidates", f"{_num(area['flood_candidate_area_km2'])} km² ({_num(area['flood_candidate_pct_of_valid'])}% of valid; {_num(area['flood_candidate_pct_of_aoi'])}% of AOI)"]])
    writer.para(area["method_note"])

    figure_files: dict[str, tuple[Path, str]] = {}
    writer.heading("9. Accuracy assessment")
    variable_record = (summary.get("independent_accuracy") or {}).get("variable_roc") or {}
    roc_context = {"aoi": aoi, "area_km2": area.get("aoi_area_km2_estimate"), "target": target_text, "baseline": baseline_text}
    if status != "assessed":
        writer.para(f"Independent accuracy: {STATUS.get(status, status)}." + (f" {reason}" if reason else ""))
        if variable_record:
            figure_files.update(variable_roc_section(writer, output_directory, variable_record, same_reason=reason, context=roc_context))
    internal_scopes = []
    for scope in assessment.get("scopes", []):
        figures = scope_figures(output_directory, scope)
        for kind, paths in figures.items():
            figure_files[f"figure_{scope['scope']}_{kind}_png"] = (paths["png"], "image/png")
            figure_files[f"figure_{scope['scope']}_{kind}_svg"] = (paths["svg"], "image/svg+xml")
        if scope["scope"] == "independent_optical":
            _accuracy_scope(writer, scope, figures, (summary.get("independent_accuracy") or {}).get("audit_sample"))
            if variable_record:
                figure_files.update(variable_roc_section(writer, output_directory, variable_record, same_reason=reason, context=roc_context))
        else:
            internal_scopes.append((scope, figures))
            writer.para(internal_agreement_sentence(scope))

    # Depth & Exposure module: sections after the accuracy assessment, before the limitations (owner, 2026-11-17).
    # Numbered from the run, so a report without them keeps "10. Limitations" and "11. Provenance summary".
    number = 10
    sections = {}
    if summary.get("modelled_flood_hazard"):
        sections["hazard"] = number
        figure_files.update(hazard_section(writer, output_directory, summary.get("modelled_flood_hazard"), map_entries, aoi=aoi,
                                           number=number, exposure=summary.get("flood_exposure")))
        number += 1
    if summary.get("flood_exposure"):
        sections["exposure"] = number
        exposure_section(writer, output_directory, summary.get("flood_exposure"), map_entries, number=number)
        number += 1
    writer.heading(f"{number}. Limitations and what is not claimed")
    # The paired-observation disclaimer is generic to the diagnostics tool, not about this map.
    general = [(f"Independent accuracy: {STATUS.get(status, status)} (reason in section 9)."
                if text.startswith("Independent accuracy:") and status != "assessed" else text)
               for text in overview["limitations"] if text != DIAGNOSTIC_LIMITATIONS[0]]
    gap = baseline_gap_text(gis_metadata.get("target_period"), gis_metadata.get("baseline_period"))
    for text in general + ([gap] if gap else []) + score_limitations(summary, assessment) + ["Flood candidates are a model classification, not confirmed flood observations.",
                                           "No result is field-verified.",
                                           NOT_PRODUCED_WITH_EXPOSURE.format(**sections) if (summary.get("flood_exposure") or {}).get("status") == "assessed" else
                                           NOT_PRODUCED_WITH_HAZARD.format(**sections) if (summary.get("modelled_flood_hazard") or {}).get("status") == "assessed" else
                                           "Depth, velocity, hazard, return period, exposure, vulnerability and risk are not produced: they require institutional data "
                                           "(for example surveyed river cross-sections, gauge records and asset registers) that this analysis does not have, "
                                           "and no proxy versions are made."]:
        writer.para(f"• {text}")

    writer.heading(f"{number + 1}. Provenance summary")
    writer.table(["Item", "Value"], [
        ["Science version", str(provenance.get("science_version", "not recorded"))],
        ["Workflow version", str(provenance.get("workflow_version", "not recorded"))],
        ["Model", str(model.get("model_key", "not recorded"))],
        ["Sentinel-2 degraded-MSI scene threshold", f"{(summary.get('quality') or {}).get('degraded_msi_max_pct', 0)}%"],
        ["Datasets", ", ".join(provenance.get("datasets") or []) or "not recorded"],
        ["Full provenance", "provenance.json in the result package"]])

    for scope, figures in internal_scopes:
        writer.heading("Appendix A: " + scope["title"], 1)
        _accuracy_scope(writer, scope, figures, None, title=False)
        if scope["scope"] == "internal_screening":
            from app.services.firris.variable_roc import HOLDOUT_NOTE
            writer.para(HOLDOUT_NOTE)

    writer.heading("Appendix B: downloads")
    report_entries = [("scientific_report_pdf", {"format": "pdf", "label": "Scientific report (PDF)"}),
                      ("scientific_report_word", {"format": "docx", "label": "Scientific report (Word)"})]
    combined_figure = figure_files.pop("_combined_figure_number", None)
    figure_entries = [(name, {"format": name.rsplit("_", 1)[1]}) for name in figure_files]
    _appendix(writer, downloads + report_entries + figure_entries)
    panels = figure_files.get("figure_independent_optical_roc_by_variable_panels_png")
    variable_roc_appendix(writer, variable_record, panels[0] if panels else None, context=roc_context, combined=combined_figure)

    pdf = output_directory / "scientific-report.pdf"
    write_pdf(writer, pdf)
    docx = output_directory / "scientific-report.docx"
    writer.doc.save(docx)
    return {"scientific_report_pdf": (pdf, "application/pdf"),
            "scientific_report_word": (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            **figure_files}
