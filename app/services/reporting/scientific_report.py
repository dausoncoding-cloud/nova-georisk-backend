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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.services.reporting.figures import scope_figures

STATUS = {"not_assessable": "not assessable", "insufficient_reference_samples": "insufficient reference samples",
          "not_performed": "not performed", "assessed": "assessed"}
GATE_STATUS = {"pass": "Pass", "fail": "Fail", "not_recorded": "Not recorded", "not_applicable": "Not applicable"}
NOT_IN_RELEASE = "Not part of this release. Water delineation and trend outputs are delivered in Bundle 3 of the remediation plan."


def _num(value, digits=2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


class _Writer:
    """Writes the same content to a ReportLab story and a python-docx document."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.story: list = []
        self.doc = Document()

    def heading(self, text: str, level: int = 1):
        self.story.append(Paragraph(escape(text), self.styles["Heading1" if level == 0 else "Heading2" if level == 1 else "Heading3"]))
        self.doc.add_heading(text, level=level)

    def para(self, text: str):
        self.story.append(Paragraph(escape(text), self.styles["BodyText"]))
        self.doc.add_paragraph(text)

    def table(self, header: list[str], rows: list[list[str]], caption: str | None = None):
        if caption:
            self.para(caption)
        data = [header] + rows
        cell = self.styles["BodyText"].clone("cell", fontSize=7, leading=8.5)
        table = Table([[Paragraph(escape(str(value)), cell) for value in row] for row in data], repeatRows=1)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef3")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        self.story += [table, Spacer(1, 0.3 * cm)]
        docx_table = self.doc.add_table(rows=len(data), cols=len(header))
        docx_table.style = "Table Grid"
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                docx_table.cell(r, c).text = str(value)

    def image(self, path: Path, width_cm: float, caption: str):
        from PIL import Image
        with Image.open(path) as source:
            ratio = source.height / source.width
        self.story += [PdfImage(str(path), width=width_cm * cm, height=width_cm * ratio * cm), Paragraph(escape(caption), self.styles["Italic"]),
                       Spacer(1, 0.3 * cm)]
        self.doc.add_picture(str(path), width=Inches(width_cm / 2.54))
        self.doc.add_paragraph(caption)


def _accuracy_scope(writer: _Writer, scope: dict, figures: dict[str, dict[str, Path]], wording: str | None):
    writer.heading(scope["title"], 2)
    if wording:
        writer.para(wording)
    method = (f"Census of n = {scope['n']:,} eligible pixels not used for training." if scope["method"] == "census"
              else f"Held-out sample, n = {scope['n']:,}.")
    writer.para(f"Reference: {scope['reference_basis']}. {method}")
    matrix = scope["confusion_matrix"]
    rows = []
    for label, name in (("1", "Classified: flood candidate"), ("0", "Classified: not flood candidate")):
        values = matrix["classified"][label]
        ua = values["users_accuracy"]
        rows.append([name, f"{values['reference_1']:,}", f"{values['reference_0']:,}", f"{values['total']:,}", f"{ua['fraction']} ({_num(ua['pct'], 1)}%)"])
    rows.append(["Total", f"{matrix['reference_totals']['1']:,}", f"{matrix['reference_totals']['0']:,}", f"{matrix['reference_totals']['all']:,}", ""])
    pa = matrix["producers_accuracy"]
    rows.append(["Producer's accuracy", f"{pa['1']['fraction']} ({_num(pa['1']['pct'], 1)}%)", f"{pa['0']['fraction']} ({_num(pa['0']['pct'], 1)}%)", "", ""])
    writer.table(["Classified \\ Reference", "Reference: flood candidate", "Reference: not flood candidate", "Total", "User's accuracy"], rows,
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
        writer.para(scope["interval_note"] + ".")
    for kind, caption in (("roc", "ROC curve with the 1:1 chance line."), ("pr", "Precision–recall curve with the prevalence baseline.")):
        writer.image(figures[kind]["png"], 8, f"{scope['title']}: {caption}")


def build_scientific_report(output_directory: Path, *, ids: dict[str, str], names: dict[str, str | None], result_version: int,
                            summary: dict, provenance: dict, gis_metadata: dict, map_entries: dict[str, dict],
                            download_labels: list[str]) -> dict[str, tuple[Path, str]]:
    from app.api.v1.result_overview import build_result_overview

    overview = build_result_overview(SimpleNamespace(engine_key="firris", summary=summary, provenance=provenance))
    if overview is None:
        return {}
    assessment = (summary.get("validation_dashboard") or {}).get("accuracy_assessment") or {}
    writer = _Writer()
    writer.heading("FIRRIS flood-candidate analysis — scientific report", 0)
    project = names.get("project") or f"Project ID {ids['project']}"
    aoi = names.get("aoi") or f"AOI ID {ids['aoi']}"
    writer.para(f"Project: {project}")
    writer.para(f"Area of interest: {aoi}")
    writer.para(f"Result version {result_version} · generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    writer.heading("1. Executive summary")
    writer.para(overview["headline"]["text"])
    status = assessment.get("independent_status") or (summary.get("independent_accuracy") or {}).get("status") or "not_performed"
    reason = assessment.get("independent_reason") or (summary.get("independent_accuracy") or {}).get("reason")
    writer.para(f"Independent accuracy: {STATUS.get(status, status)}." + (f" {reason}" if reason and status != "assessed" else ""))

    area = overview["area_accounting"]
    writer.heading("2. Study area")
    box = gis_metadata.get("bounding_box") or {}
    writer.para(f"{aoi}. Estimated AOI area {_num(area['aoi_area_km2_estimate'])} km² ({area['aoi_cells'] or '—'} cells); "
                f"bounding box {box.get('west')}, {box.get('south')} to {box.get('east')}, {box.get('north')} ({gis_metadata.get('crs', 'CRS not recorded')}).")

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
        writer.para(f"Independent optical reference: {policy.get('definition')}. Scene policy: {policy.get('scene_policy')}.")

    writer.heading("6. Quality gates")
    writer.table(["Gate", "Threshold", "Observed", "Status"],
                 [[g["name"], g["threshold"], g["observed"] or "—", GATE_STATUS.get(g["status"], g["status"])] for g in overview["quality_gates"]])

    writer.heading("7. Main maps")
    for key, entry in sorted(map_entries.items()):
        if entry.get("delivery_type") == "map_png":
            title = (entry.get("gis_metadata") or {}).get("cartography", {}).get("title", key)
            writer.image(output_directory / entry["path"], 16, f"{title}. Target {headline['target_period'] or 'not recorded'}; "
                         f"baseline {headline['baseline_period'] or 'not recorded'}. Coordinates and colour scale are on the map frame.")

    writer.heading("8. Water delineation")
    writer.para(NOT_IN_RELEASE)
    writer.heading("9. Trend outputs")
    writer.para(NOT_IN_RELEASE)

    writer.heading("10. Area statistics")
    writer.table(["Quantity", "Value"], [
        ["Valid analysed area", f"{_num(area['valid_area_km2'])} km² ({_num(area['valid_pct_of_aoi'])}% of AOI)"],
        ["Excluded (no valid data)", f"{_num(area['excluded_area_km2_estimate'])} km² ({area['excluded_cells'] if area['excluded_cells'] is not None else '—'} cells)"],
        ["Flood candidates", f"{_num(area['flood_candidate_area_km2'])} km² ({_num(area['flood_candidate_pct_of_valid'])}% of valid; {_num(area['flood_candidate_pct_of_aoi'])}% of AOI)"]])
    writer.para(area["method_note"])

    figure_files: dict[str, tuple[Path, str]] = {}
    writer.heading("11. Accuracy assessment")
    if status != "assessed":
        writer.para(f"Independent accuracy: {STATUS.get(status, status)}." + (f" {reason}" if reason else ""))
    for scope in assessment.get("scopes", []):
        figures = scope_figures(output_directory, scope)
        for kind, paths in figures.items():
            figure_files[f"figure_{scope['scope']}_{kind}_png"] = (paths["png"], "image/png")
            figure_files[f"figure_{scope['scope']}_{kind}_svg"] = (paths["svg"], "image/svg+xml")
        _accuracy_scope(writer, scope, figures, assessment.get("independent_wording") if scope["scope"] == "independent_optical" else None)

    writer.heading("12. Limitations and what is not claimed")
    for text in overview["limitations"] + ["Flood candidates are a model classification, not confirmed flood observations.",
                                           "No result is field-verified.",
                                           "Depth, velocity, hazard, return period, exposure, vulnerability and risk are not produced (client decision D2)."]:
        writer.para(f"• {text}")

    writer.heading("13. Provenance summary")
    writer.table(["Item", "Value"], [
        ["Science version", str(provenance.get("science_version", "not recorded"))],
        ["Workflow version", str(provenance.get("workflow_version", "not recorded"))],
        ["Model", str(model.get("model_key", "not recorded"))],
        ["Sentinel-2 degraded-MSI scene threshold", f"{(summary.get('quality') or {}).get('degraded_msi_max_pct', 0)}%"],
        ["Datasets", ", ".join(provenance.get("datasets") or []) or "not recorded"],
        ["Full provenance", "provenance.json in the result package"]])

    writer.heading("Appendix: downloads")
    for label in download_labels:
        writer.para(f"• {label}")

    pdf = output_directory / "scientific-report.pdf"
    SimpleDocTemplate(str(pdf), pagesize=A4, title="FIRRIS scientific report", leftMargin=2 * cm, rightMargin=2 * cm).build(writer.story)
    docx = output_directory / "scientific-report.docx"
    writer.doc.save(docx)
    return {"scientific_report_pdf": (pdf, "application/pdf"),
            "scientific_report_word": (docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            **figure_files}
