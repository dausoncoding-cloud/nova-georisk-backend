"""Client scientific report for FIRRIS flood results (plan item 2.4), as PDF and DOCX.

Content comes only from what the result already holds: the computed overview (headline,
area accounting, quality gates, data sources, limitations), the accuracy assessment
(independent census first, internal agreement second), the framed maps and provenance.
Maps are embedded as delivered; captions, dates and keys are written as report text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document
from docx.shared import Inches
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.services.reporting.figures import scope_figures
from app.services.validation.accuracy_tables import reference_columns
from app.services.validation.diagnostics import LIMITATIONS as DIAGNOSTIC_LIMITATIONS

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


class _Writer:
    """Writes the same content to a ReportLab story and a python-docx document."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        for name in ("Heading1", "Heading2", "Heading3"):
            self.styles[name].keepWithNext = 1  # a heading never ends a page
        self.story: list = []
        self.doc = Document()

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
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef3")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        self.story += [table, Spacer(1, 0.3 * cm)]
        self.keep_together(start)  # never split a table from its caption or orphan its last row
        docx_table = self.doc.add_table(rows=len(data), cols=len(header))
        docx_table.style = "Table Grid"
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                docx_table.cell(r, c).text = str(value)

    def image(self, path: Path, width_cm: float, caption: str, max_height_cm: float | None = None):
        from PIL import Image
        with Image.open(path) as source:
            ratio = source.height / source.width
        if max_height_cm and width_cm * ratio > max_height_cm:
            width_cm = max_height_cm / ratio
        self.story += [PdfImage(str(path), width=width_cm * cm, height=width_cm * ratio * cm), Paragraph(escape(caption), self.styles["Italic"]),
                       Spacer(1, 0.3 * cm)]
        self.doc.add_picture(str(path), width=Inches(width_cm / 2.54))
        self.doc.add_paragraph(caption)


def internal_agreement_sentence(scope: dict) -> str:
    """Section 9 keeps one sentence on internal agreement: why it is high and why it is not accuracy."""
    labels = "the SAR screening labels" if scope["scope"] == "internal_screening" else "the supplied labels"
    return (f"Internal agreement with {labels} on {scope['n']:,} held-out pixels is {_num(scope['overall_accuracy_pct'], 1)}% "
            f"(kappa {_num(scope['cohens_kappa'], 3)}) because the classifier is trained to reproduce these labels from the same "
            "inputs, so it shows how well the labelling rule was learned and is not map accuracy (details in Appendix A).")


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
    writer.para(f"Overall accuracy {_num(scope['overall_accuracy_pct'], 1)}% · Kappa {_num(scope['cohens_kappa'], 3)} · "
                f"F1 (flood candidate) {_num(scope['f1_flooded'], 3)} · IoU {_num(scope['iou_flooded'], 3)} · "
                f"AUC {_num(scope['roc_auc'], 3)} · AP {_num(scope['average_precision'], 3)}.")
    intervals = scope.get("confidence_intervals_95")
    if intervals:
        def span(values, digits):
            return "—" if not values else f"{values[0]:.{digits}f}–{values[1]:.{digits}f}"
        writer.para(f"95% interval ({intervals['method']}): OA {span(intervals['overall_accuracy_pct'], 1)}%, "
                    f"Kappa {span(intervals['cohens_kappa'], 3)}, AUC {span(intervals['roc_auc'], 3)}.")
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
    for kind, caption in (("roc", "ROC curve with the 1:1 chance line."), ("pr", "precision–recall curve with the prevalence baseline.")):
        writer.image(figures[kind]["png"], 8, f"{short}: {caption}")


APPENDIX_GROUPS = [("client_deliverable", "Client deliverables"), ("gis_data", "GIS data"),
                   ("figures", "Figures and accuracy tables"), ("audit", "Audit and provenance")]
FIGURE_KINDS = {"roc": "ROC curve", "pr": "precision–recall curve", "confusion": "confusion matrix", "class_metrics": "per-class accuracy"}
TABLE_KINDS = {"confusion": "confusion matrix", "summary": "per-class accuracy summary", "roc": "ROC curve points", "pr": "precision–recall curve points"}
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
README_POINTER = ("Figures, accuracy tables, audit and provenance files are listed in README.txt inside the FIRRIS result package "
                  "(firris-result-package.zip).")


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
    lines = ["FIRRIS result package", "", "Files in this package, grouped as on the download page.", ""]
    for _, title, rows in grouped_downloads([(key, entry) for _, key, entry in files], unique=False):
        lines += [title, "-" * len(title)]
        lines += [f"{by_key[key]}  —  {label}" for key, _, label in rows]
        lines.append("")
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
    return (f"The baseline period ({baseline['start']} to {baseline['end']}) is {abs(gap):,} days {direction} the target period "
            f"({target['start']} to {target['end']}), measured between period midpoints, and {season} days apart in the annual "
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
    writer.heading("FIRRIS flood-candidate analysis — scientific report", 0)
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
        writer.para(f"Independent accuracy: {STATUS.get(status, status)}." + (f" {reason}" if reason else ""))
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
    writer.para(f"Target: {headline['target_period'] or 'not recorded'}; baseline: {headline['baseline_period'] or 'not recorded'} (end dates exclusive).")
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
                 [[g["name"], g["threshold"], g["observed"] or "—", GATE_STATUS.get(g["status"], g["status"])] for g in overview["quality_gates"]])

    start = len(writer.story)
    writer.heading("7. Main maps")
    for key, entry in sorted(map_entries.items()):
        if entry.get("delivery_type") == "map_png":
            title = (entry.get("gis_metadata") or {}).get("cartography", {}).get("title", key)
            # Two maps share one A4 page: each image is at most 10 cm tall.
            writer.image(output_directory / entry["path"], 16, f"{title}. Target {headline['target_period'] or 'not recorded'}; "
                         f"baseline {headline['baseline_period'] or 'not recorded'}.",
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
    if status != "assessed":
        writer.para(f"Independent accuracy: {STATUS.get(status, status)}." + (f" {reason}" if reason else ""))
    internal_scopes = []
    for scope in assessment.get("scopes", []):
        figures = scope_figures(output_directory, scope)
        for kind, paths in figures.items():
            figure_files[f"figure_{scope['scope']}_{kind}_png"] = (paths["png"], "image/png")
            figure_files[f"figure_{scope['scope']}_{kind}_svg"] = (paths["svg"], "image/svg+xml")
        if scope["scope"] == "independent_optical":
            _accuracy_scope(writer, scope, figures, (summary.get("independent_accuracy") or {}).get("audit_sample"))
        else:
            internal_scopes.append((scope, figures))
            writer.para(internal_agreement_sentence(scope))

    writer.heading("10. Limitations and what is not claimed")
    # The paired-observation disclaimer is generic to the diagnostics tool, not about this map.
    general = [text for text in overview["limitations"] if text != DIAGNOSTIC_LIMITATIONS[0]]
    gap = baseline_gap_text(gis_metadata.get("target_period"), gis_metadata.get("baseline_period"))
    for text in general + ([gap] if gap else []) + score_limitations(summary, assessment) + ["Flood candidates are a model classification, not confirmed flood observations.",
                                           "No result is field-verified.",
                                           "Depth, velocity, hazard, return period, exposure, vulnerability and risk are not produced: they require institutional data "
                                           "(for example surveyed river cross-sections, gauge records and asset registers) that this analysis does not have, "
                                           "and no proxy versions are made."]:
        writer.para(f"• {text}")

    writer.heading("11. Provenance summary")
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

    writer.heading("Appendix B: downloads")
    report_entries = [("scientific_report_pdf", {"format": "pdf", "label": "Scientific report (PDF)"}),
                      ("scientific_report_word", {"format": "docx", "label": "Scientific report (Word)"})]
    figure_entries = [(name, {"format": name.rsplit("_", 1)[1]}) for name in figure_files]
    _appendix(writer, downloads + report_entries + figure_entries)

    pdf = output_directory / "scientific-report.pdf"
    SimpleDocTemplate(str(pdf), pagesize=A4, title="FIRRIS scientific report", leftMargin=2 * cm, rightMargin=2 * cm).build(writer.story)
    docx = output_directory / "scientific-report.docx"
    writer.doc.save(docx)
    return {"scientific_report_pdf": (pdf, "application/pdf"),
            "scientific_report_word": (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            **figure_files}
